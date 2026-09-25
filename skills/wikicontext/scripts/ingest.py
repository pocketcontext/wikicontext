"""Preserve originals and ingest addressable evidence; synthesis belongs to the skill."""
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

import wc

AUDIO = {'.mp3', '.m4a', '.wav', '.flac', '.ogg', '.webm', '.mp4', '.mpeg', '.mpga', '.opus'}
TEXT = {'.txt', '.md', '.markdown', '.csv', '.json', '.rst', '.log'}
MAX_SOURCE = 100 * 1024 * 1024


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def rows(cfg, sql):
    result = wc.must(cfg, 'POST', '/api/context/query', {'sql': sql})
    if result.get('truncated'):
        raise wc.Fail(1, 'Evidence query was truncated; no ingestion writes attempted from incomplete results.')
    return [dict(zip(result['columns'], row)) for row in result['rows']]


def multipart(fields, field, filename, content, media='application/octet-stream'):
    boundary = 'wikicontext-' + secrets.token_hex(24)
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    # Filename is generated locally, never an unsanitized source label.
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\nContent-Type: {media}\r\n\r\n'.encode())
    parts.extend([content, f'\r\n--{boundary}--\r\n'.encode()])
    return b''.join(parts), 'multipart/form-data; boundary=' + boundary


def upload_source(cfg, path, content, digest, title):
    # Refresh through the normal authenticated client before using its cached token.
    wc.must(cfg, 'POST', '/api/context/query', {'sql': 'SELECT 1'})
    session = wc.load_session(cfg)
    if not session:
        session = wc.login(cfg)
    fields = {'title': title or path.stem, 'original_name': path.name,
              'media_type': mimetypes.guess_type(path.name)[0] or 'application/octet-stream'}
    suffix = path.suffix.lower() if path.suffix.lower().lstrip('.').isalnum() else '.bin'
    body, media = multipart(fields, 'original', digest + suffix, content)
    request = urllib.request.Request(cfg['url'] + wc.records('sources'), data=body,
                                    headers={'Authorization': session['token'], 'Content-Type': media,
                                             'User-Agent': wc.USER_AGENT}, method='POST')
    try:
        with wc.opener.open(request, timeout=180) as response:
            return json.load(response)
    except (OSError, ValueError) as error:
        # A concurrent upload or lost response can already have persisted this exact original.
        found = rows(cfg, 'SELECT id, sha256 FROM sources WHERE sha256 = ' + literal(digest) + ' LIMIT 1')
        if found:
            return found[0]
        status = getattr(error, 'code', None)
        raise wc.Fail(1, f'Original upload failed (HTTP {status or "transport error"}); retry ingestion.') from None


def command(args):
    if not shutil.which(args[0]):
        raise wc.Fail(2, f'{args[0]} is required for this source type; original remains stored for retry.')
    try:
        return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600).stdout
    except (OSError, subprocess.SubprocessError):
        raise wc.Fail(1, f'{args[0]} failed; original remains stored for retry.') from None


def duration(path):
    try:
        value = float(command(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(path)]))
        if not math.isfinite(value) or value <= 0:
            raise ValueError()
        return value
    except ValueError:
        raise wc.Fail(1, 'Cannot verify audio duration; no audio sent to Groq.') from None


def transcribe(path):
    key = wc.hide(os.environ.get('WIKICONTEXT_GROQ_API_KEY'))
    if not key:
        raise wc.Fail(2, 'Set WIKICONTEXT_GROQ_API_KEY to transcribe audio; original remains stored.')
    with tempfile.TemporaryDirectory(prefix='wikicontext-audio-') as folder:
        derivative = Path(folder) / 'audio.ogg'
        original_duration = duration(path)
        command(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(path), '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'libopus', '-b:a', '16k', str(derivative)])
        if abs(duration(derivative) - original_duration) > 1:
            raise wc.Fail(1, 'Derivative duration differs by more than one second; no audio sent to Groq.')
        if derivative.stat().st_size > 25_000_000:
            raise wc.Fail(2, 'Audio derivative exceeds conservative 25 MB Groq limit; no audio sent. Supply approved split sources or a separately extracted rendition.')
        body, media = multipart({'model': 'whisper-large-v3-turbo', 'response_format': 'verbose_json', 'timestamp_granularities[]': 'segment'}, 'file', 'audio.ogg', derivative.read_bytes(), 'audio/ogg')
        request = urllib.request.Request('https://api.groq.com/openai/v1/audio/transcriptions', data=body,
                                        headers={'Authorization': 'Bearer ' + key, 'Content-Type': media}, method='POST')
        try:
            with wc.opener.open(request, timeout=600) as response:
                result = json.load(response)
        except (OSError, ValueError):
            raise wc.Fail(1, 'Groq transcription failed; original remains stored. Retry after checking provider availability and credentials.') from None
    segments = result.get('segments') if isinstance(result, dict) else None
    if not isinstance(segments, list) or not segments:
        raise wc.Fail(1, 'Groq returned no timestamped segments; original remains stored.')
    output = []
    for segment in segments:
        try:
            start, end, body = float(segment['start']), float(segment['end']), segment['text']
            if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start <= end <= original_duration + 2 or not isinstance(body, str):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise wc.Fail(1, 'Groq returned an invalid transcript segment; retry transcription.') from None
        output.extend(chunks(body, f'seconds {start:.3f}-{end:.3f}'))
    return output


def chunks(text, locator):
    return [{'locator': f'{locator}; characters {offset + 1}-{min(offset + 24000, len(text))}', 'body': text[offset:offset + 24000]}
            for offset in range(0, len(text), 24000) if text[offset:offset + 24000].strip()]


def extract(path, content):
    suffix = path.suffix.lower()
    if suffix in TEXT:
        try:
            return 'text', 'utf-8 text / wikicontext-1', chunks(content.decode('utf-8-sig'), 'document')
        except UnicodeDecodeError:
            raise wc.Fail(2, 'Text source is not UTF-8; provide an explicitly converted source without replacing the original.') from None
    if suffix == '.pdf':
        output = command(['pdftotext', '-layout', str(path), '-']).decode('utf-8')
        passages = []
        for number, page in enumerate(output.split('\f'), 1):
            passages.extend(chunks(page, f'page {number}'))
        return 'text', 'pdftotext / wikicontext-1', passages
    if suffix in AUDIO:
        return 'transcript', 'groq/whisper-large-v3-turbo / wikicontext-1', transcribe(path)
    raise wc.Fail(2, f'Unsupported source extension {suffix or "(none)"}; original stored, extraction incomplete. Supply a supported source or explicitly prepare a rendition.')


def ingest(cfg, path, title=None, version='v1'):
    path = Path(path).resolve()
    if not version or len(version) > 100:
        raise wc.Fail(2, 'Rendition version must contain 1–100 characters.')
    if not path.is_file() or path.stat().st_size > MAX_SOURCE:
        raise wc.Fail(2, 'Source must be a regular file no larger than 100 MiB.')
    content = path.read_bytes()
    if len(content) > MAX_SOURCE:
        raise wc.Fail(2, 'Source exceeds 100 MiB; no upload attempted.')
    if not content or content.startswith(b'version https://git-lfs.github.com/spec/v1\n'):
        raise wc.Fail(2, 'Source is empty or a Git LFS pointer; retrieve actual source bytes first.')
    digest = hashlib.sha256(content).hexdigest()
    found = rows(cfg, 'SELECT id, sha256 FROM sources WHERE sha256 = ' + literal(digest) + ' LIMIT 1')
    source = found[0] if found else upload_source(cfg, path, content, digest, title)
    if source.get('sha256') != digest:
        raise wc.Fail(1, 'Server original checksum differs; stop and investigate before extraction.')
    # A complete immutable rendition can be reused even on a different machine.
    kind_hint = 'transcript' if path.suffix.lower() in AUDIO else 'text'
    completed = rows(cfg, 'SELECT id, notes FROM renditions WHERE source = ' + literal(source['id']) + ' AND kind = ' + literal(kind_hint) + ' AND version_label = ' + literal(version) + ' LIMIT 1')
    if completed:
        try:
            expected = json.loads(completed[0]['notes'])['passages']
        except (ValueError, KeyError, TypeError):
            expected = None
        if type(expected) is int and expected > 0:
            counts = rows(cfg, 'SELECT COUNT(*) AS count, MIN(ordinal) AS first, MAX(ordinal) AS last FROM passages WHERE rendition = ' + literal(completed[0]['id']))[0]
            if counts == {'count': expected, 'first': 1, 'last': expected}:
                return {'source': source['id'], 'rendition': completed[0]['id'], 'passages': expected, 'sha256': digest, 'status': 'extracted', 'next': 'Synthesize cited page revisions in a staging ingestion run, then publish.'}
    # Cache only extraction output, with a restrictive mode. Identity and server scope prevent cross-workspace reuse.
    key = hashlib.sha256((cfg['url'] + '\n' + cfg['email'] + '\n' + digest + '\n' + version + '\n' + path.suffix.lower()).encode()).hexdigest()
    base = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'wikicontext' / 'extractions'
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(base, 0o700)
    cache = base / (key + '.json')
    if cache.exists():
        try:
            kind, processor, passages = json.loads(cache.read_text())
        except (ValueError, OSError):
            raise wc.Fail(1, 'Extraction cache is unreadable; investigate before retrying.') from None
    else:
        # Tools operate on an immutable local snapshot of the exact uploaded bytes.
        with tempfile.TemporaryDirectory(prefix='wikicontext-source-') as folder:
            snapshot = Path(folder) / ('source' + path.suffix.lower())
            snapshot.write_bytes(content)
            kind, processor, passages = extract(snapshot, content)
        if not passages:
            raise wc.Fail(1, 'Extraction returned no text (scanned PDFs require OCR); original remains stored.')
        with tempfile.NamedTemporaryFile(mode='w', dir=base, delete=False) as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump([kind, processor, passages], handle, ensure_ascii=False)
        os.replace(handle.name, cache)
    manifest = json.dumps({'passages': len(passages), 'sha256': hashlib.sha256(json.dumps(passages, sort_keys=True).encode()).hexdigest()}, sort_keys=True)
    query = 'SELECT id, notes FROM renditions WHERE source = ' + literal(source['id']) + ' AND kind = ' + literal(kind) + ' AND version_label = ' + literal(version) + ' LIMIT 1'
    existing = rows(cfg, query)
    if not existing:
        try:
            rendition = wc.must(cfg, 'POST', wc.records('renditions'), {'source': source['id'], 'kind': kind, 'processor': processor, 'version_label': version, 'notes': manifest})
        except wc.Fail:
            existing = rows(cfg, query)
            if not existing:
                raise
            rendition = existing[0]
    else:
        rendition = existing[0]
    if rendition['notes'] != manifest:
        raise wc.Fail(4, 'Existing rendition has different extracted content. Preserve it and select a new --version.')
    for ordinal, passage in enumerate(passages, 1):
        query = 'SELECT id, locator, body FROM passages WHERE rendition = ' + literal(rendition['id']) + f' AND ordinal = {ordinal} LIMIT 1'
        previous = rows(cfg, query)
        if not previous:
            try:
                wc.must(cfg, 'POST', wc.records('passages'), {'rendition': rendition['id'], 'ordinal': ordinal, **passage})
                continue
            except wc.Fail:
                previous = rows(cfg, query)
                if not previous:
                    raise
        if any(previous[0][field] != passage[field] for field in ('locator', 'body')):
            raise wc.Fail(4, 'Existing passage differs from extraction; select a new rendition version.')
    return {'source': source['id'], 'rendition': rendition['id'], 'passages': len(passages), 'sha256': digest, 'status': 'extracted', 'next': 'Synthesize cited page revisions in a staging ingestion run, then publish.'}
