#!/usr/bin/env python3
"""Synthetic ingestion recovery tests; never call Groq or production APIs."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import shutil
import wave
import unittest
import unittest.mock
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/wikicontext/scripts'))
# This test filename shadows the implementation when run as a script.
spec = importlib.util.spec_from_file_location('ingestion', Path(sys.path[0]) / 'ingest.py')
ingest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ingest)
UPLOAD_SOURCE = ingest.upload_source


class EvidenceStore:
    def __init__(self):
        self.tables = {name: [] for name in ('sources', 'renditions', 'passages')}
        self.fail_ordinal = None

    def query(self, cfg, sql):
        import sqlite3
        db = sqlite3.connect(':memory:')
        db.row_factory = sqlite3.Row
        for name, fields in [('sources', 'id, sha256'), ('renditions', 'id, source, kind, version_label, notes'), ('passages', 'id, rendition, ordinal INTEGER, locator, body')]:
            db.execute(f'CREATE TABLE {name} ({fields})')
            for record in self.tables[name]:
                columns = [field.split()[0] for field in fields.split(', ')]
                db.execute(f'INSERT INTO {name} VALUES ({",".join("?" for _ in columns)})', [record.get(column) for column in columns])
        result = [dict(row) for row in db.execute(sql)]
        db.close()
        return result

    def upload(self, cfg, path, content, digest, title):
        return self.create(cfg, 'POST', '/api/collections/sources/records', {'sha256': digest, 'original_name': path.name, 'content': content})

    def create(self, cfg, method, path, body):
        table = path.split('/')[3]
        if table == 'passages' and body['ordinal'] == self.fail_ordinal:
            raise ingest.wc.Fail(1, 'injected interrupted write')
        row = {'id': str(len(self.tables[table]) + 1).zfill(15), **body}
        self.tables[table].append(row)
        return row


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = {'url': 'http://127.0.0.1:12345', 'email': 'synthetic@example.test'}
        self.store = EvidenceStore()
        for patcher in [patch.dict(os.environ, {'XDG_CACHE_HOME': str(self.root / 'cache')}),
                        patch.object(ingest, 'rows', self.store.query), patch.object(ingest, 'upload_source', self.store.upload),
                        patch.object(ingest.wc, 'must', self.store.create)]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def source(self, name, content):
        path = self.root / name
        path.write_bytes(content)
        return path

    def test_interrupted_passages_resume_and_duplicate(self):
        source = self.source('evidence.md', ('first\n' * 12000).encode())
        self.store.fail_ordinal = 2
        with self.assertRaises(ingest.wc.Fail):
            ingest.ingest(self.cfg, source)
        self.assertEqual(len(self.store.tables['sources']), 1)
        self.assertEqual(len(self.store.tables['passages']), 1)
        self.store.fail_ordinal = None
        completed = ingest.ingest(self.cfg, source)
        duplicate = ingest.ingest(self.cfg, source)
        self.assertEqual(completed, duplicate)
        self.assertEqual(completed['passages'], 3)
        self.assertEqual(len(self.store.tables['renditions']), 1)
        self.assertEqual(''.join(p['body'] for p in self.store.tables['passages']), source.read_text())
        self.assertEqual(completed['status'], 'extracted')

    def test_provider_failure_preserves_original_then_cached_resume(self):
        source = self.source('meeting.wav', b'synthetic audio fixture')
        with patch.object(ingest, 'transcribe', side_effect=ingest.wc.Fail(1, 'provider unavailable')):
            with self.assertRaises(ingest.wc.Fail):
                ingest.ingest(self.cfg, source, audio_storage='original')
        self.assertEqual(len(self.store.tables['sources']), 1)
        self.assertEqual(len(self.store.tables['renditions']), 0)
        transcript = [{'locator': 'seconds 0-1', 'body': 'Synthetic transcript.'}]
        with patch.object(ingest, 'transcribe', return_value=transcript) as provider:
            ingest.ingest(self.cfg, source, audio_storage='original')
            ingest.ingest(self.cfg, source, audio_storage='original')
            self.assertEqual(provider.call_count, 1)
        self.assertEqual(source.read_bytes(), b'synthetic audio fixture')

    def audio_source(self):
        path = self.root / 'synthetic-meeting.wav'
        with wave.open(str(path), 'wb') as audio:
            audio.setnchannels(2)
            audio.setsampwidth(2)
            audio.setframerate(48000)
            audio.writeframes(b'\0' * 48000 * 2 * 2)
        return path

    def test_normalization_failure_never_uploads(self):
        path = self.source('broken.wav', b'synthetic invalid audio')
        with patch.object(ingest, 'prepare_audio', side_effect=ingest.wc.Fail(1, 'normalization failed')):
            with self.assertRaises(ingest.wc.Fail):
                ingest.ingest(self.cfg, path)
        self.assertFalse(self.store.tables['sources'])
        self.assertEqual(path.read_bytes(), b'synthetic invalid audio')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_selected_audio_duration_ignores_longer_video_and_other_audio(self):
        for suffix, video_codec, audio_codec, offset in [
                ('mp4', 'mpeg4', 'aac', '0'), ('webm', 'libvpx', 'libopus', '2')]:
            with self.subTest(format=suffix):
                path = self.root / ('mixed.' + suffix)
                ingest.command(['ffmpeg', '-nostdin', '-v', 'error',
                                '-f', 'lavfi', '-i', 'color=size=16x16:rate=10:duration=4',
                                '-itsoffset', offset, '-f', 'lavfi', '-i',
                                'sine=frequency=440:duration=1',
                                '-f', 'lavfi', '-i', 'sine=frequency=880:duration=3',
                                '-map', '0:v:0', '-map', '1:a:0', '-map', '2:a:0',
                                '-c:v', video_codec, '-c:a', audio_codec, str(path)])
                probe = json.loads(ingest.command(['ffprobe', '-v', 'error',
                                   '-show_streams', '-show_format', '-of', 'json', str(path)]))
                self.assertGreater(float(probe['format']['duration']), 3.5)
                audio = [stream for stream in probe['streams'] if stream['codec_type'] == 'audio']
                self.assertEqual(len(audio), 2)
                if suffix == 'webm':
                    self.assertNotIn('duration', audio[0])
                    self.assertGreater(float(audio[0]['start_time']), 1.5)
                self.assertAlmostEqual(ingest.duration(path), 1, delta=0.1)
                content, provenance = ingest.prepare_audio(self.cfg, path)
                self.assertAlmostEqual(provenance['duration'], 1, delta=0.1)
                derivative = self.root / (suffix + '.ogg')
                derivative.write_bytes(content)
                self.assertAlmostEqual(ingest.duration(derivative), 1, delta=0.1)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_duration_fallback_counts_decoded_wav_samples(self):
        path = self.audio_source()
        real_command = ingest.command
        def missing_duration(args):
            return b'N/A\n' if args[0] == 'ffprobe' else real_command(args)
        with patch.object(ingest, 'command', side_effect=missing_duration):
            # FFmpeg versions may round progress timestamps by a millisecond.
            self.assertAlmostEqual(ingest.duration(path), 1, delta=0.002)

    def test_invalid_audio_duration_is_rejected(self):
        for value in [b'0', b'-1', b'nan', b'inf']:
            with self.subTest(value=value), patch.object(ingest, 'command', return_value=value):
                with self.assertRaises(ingest.wc.Fail):
                    ingest.duration(self.root / 'unused.wav')
        for progress in [b'', b'out_time_us=N/A', b'out_time_us=0', b'out_time_us=nan']:
            with self.subTest(progress=progress), patch.object(ingest, 'command', side_effect=[b'N/A', progress]):
                with self.assertRaises(ingest.wc.Fail):
                    ingest.duration(self.root / 'unused.webm')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_normalized_upload_provider_bytes_and_retry(self):
        path = self.audio_source()
        original = path.read_bytes()
        sent = []
        def provider(audio_path, original_duration):
            sent.append(audio_path.read_bytes())
            self.assertAlmostEqual(original_duration, 1, delta=0.1)
            if len(sent) == 1:
                raise ingest.wc.Fail(1, 'synthetic provider failure')
            return [{'locator': 'seconds 0-1', 'body': 'Synthetic transcript.'}]
        with patch.object(ingest, 'send_transcription', side_effect=provider), \
                patch.dict(os.environ, {'WIKICONTEXT_GROQ_API_KEY': 'synthetic-key'}):
            with self.assertRaises(ingest.wc.Fail):
                ingest.ingest(self.cfg, path)
            self.assertEqual(len(self.store.tables['sources']), 1)
            result = ingest.ingest(self.cfg, path)
            self.assertEqual(result, ingest.ingest(self.cfg, path))
        self.assertEqual(len(sent), 2)
        stored = self.store.tables['sources'][0]
        self.assertEqual(stored['original_name'], 'synthetic-meeting.normalized.ogg')
        self.assertEqual(sent, [stored['content'], stored['content']])
        self.assertEqual(result['sha256'], hashlib.sha256(sent[0]).hexdigest())
        self.assertEqual(path.read_bytes(), original)
        provenance = json.loads(self.store.tables['renditions'][0]['notes'])['audio']
        self.assertEqual(provenance['input_sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(provenance['input_name'], path.name)
        self.assertEqual(provenance['stored_sha256'], result['sha256'])
        self.assertEqual(provenance['storage'], 'normalized')
        self.assertEqual(provenance['channels'], 1)
        self.assertEqual(provenance['sample_rate'], 16000)
        self.assertEqual(provenance['bitrate'], 16000)
        self.assertEqual(provenance['codec'], 'opus')
        stored_path = self.root / 'stored.ogg'
        stored_path.write_bytes(sent[0])
        inspected = json.loads(ingest.command(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(stored_path)]))
        stream = inspected['streams'][0]
        self.assertEqual(stream['codec_name'], 'opus')
        self.assertEqual(stream['channels'], 1)
        tags = {key.lower(): value for key, value in stream['tags'].items()}
        self.assertEqual(tags['wikicontext_input_sha256'], provenance['input_sha256'])
        self.assertEqual(tags['wikicontext_audio_profile'], provenance['profile'])
        self.assertEqual(tags['wikicontext_converter'], provenance['converter'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_normalization_precedes_source_size_gate(self):
        path = self.audio_source()
        normalized, provenance = ingest.prepare_audio(self.cfg, path)
        self.assertLess(len(normalized), path.stat().st_size)
        transcript = [{'locator': 'seconds 0-1', 'body': 'Synthetic transcript.'}]
        with patch.object(ingest, 'MAX_SOURCE', len(normalized) + 1), \
                patch.object(ingest, 'send_transcription', return_value=transcript), \
                patch.dict(os.environ, {'WIKICONTEXT_GROQ_API_KEY': 'synthetic-key'}):
            ingest.ingest(self.cfg, path)
            with self.assertRaises(ingest.wc.Fail):
                ingest.ingest(self.cfg, path, audio_storage='original')
        self.assertEqual(len(self.store.tables['sources']), 1)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_audio_cache_and_fresh_cache_determinism(self):
        path = self.audio_source()
        first, provenance = ingest.prepare_audio(self.cfg, path)
        with patch.object(ingest, 'convert_audio', side_effect=AssertionError('cached output must be reused')):
            second, saved_provenance = ingest.prepare_audio(self.cfg, path)
        self.assertEqual(first, second)
        self.assertEqual(provenance, saved_provenance)
        other_cfg = {**self.cfg, 'email': 'other@example.test'}
        fresh, _ = ingest.prepare_audio(other_cfg, path)
        self.assertEqual(first, fresh)
        renamed = self.root / 'renamed.wav'
        renamed.write_bytes(path.read_bytes())
        renamed_bytes, _ = ingest.prepare_audio({**self.cfg, 'email': 'third@example.test'}, renamed)
        self.assertEqual(first, renamed_bytes)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_invalid_cached_audio_never_uploads(self):
        path = self.audio_source()
        ingest.prepare_audio(self.cfg, path)
        cached = next((self.root / 'cache/wikicontext/audio').glob('*/audio.ogg'))
        cached.write_bytes(b'tampered audio')
        with self.assertRaises(ingest.wc.Fail):
            ingest.ingest(self.cfg, path)
        self.assertFalse(self.store.tables['sources'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_default_duration_mismatch_and_size_limit_prevent_upload(self):
        path = self.audio_source()
        with patch.object(ingest, 'duration', side_effect=[10.0, 7.0]):
            with self.assertRaises(ingest.wc.Fail):
                ingest.ingest(self.cfg, path)
        self.assertFalse(self.store.tables['sources'])
        with patch.object(ingest, 'MAX_AUDIO', 1):
            with self.assertRaises(ingest.wc.Fail):
                ingest.ingest(self.cfg, path)
        self.assertFalse(self.store.tables['sources'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_audio_partial_passages_resume_after_rename_and_fresh_cache(self):
        path = self.audio_source()
        transcript = [{'locator': 'seconds 0-0.5', 'body': 'Synthetic first passage.'},
                      {'locator': 'seconds 0.5-1', 'body': 'Synthetic second passage.'}]
        with patch.object(ingest, 'send_transcription', return_value=transcript), \
                patch.dict(os.environ, {'WIKICONTEXT_GROQ_API_KEY': 'synthetic-key'}):
            self.store.fail_ordinal = 2
            with self.assertRaises(ingest.wc.Fail):
                ingest.ingest(self.cfg, path)
            self.assertEqual(len(self.store.tables['passages']), 1)
            original_notes = self.store.tables['renditions'][0]['notes']
            renamed = self.root / 'renamed.wav'
            renamed.write_bytes(path.read_bytes())
            self.store.fail_ordinal = None
            result = ingest.ingest({**self.cfg, 'email': 'new-machine@example.test'}, renamed)
        self.assertEqual(result['passages'], 2)
        self.assertEqual(len(self.store.tables['sources']), 1)
        self.assertEqual(len(self.store.tables['renditions']), 1)
        self.assertEqual(self.store.tables['renditions'][0]['notes'], original_notes)

    def test_unsupported_and_scanned_pdf_never_claim_completion(self):
        with self.assertRaises(ingest.wc.Fail):
            ingest.ingest(self.cfg, self.source('unknown.zip', b'fixture'))
        with patch.object(ingest, 'command', return_value=b'\f'):
            with self.assertRaises(ingest.wc.Fail):
                ingest.ingest(self.cfg, self.source('scan.pdf', b'pdf fixture'))
        self.assertEqual(len(self.store.tables['sources']), 2)
        self.assertFalse(self.store.tables['renditions'])

    def test_changed_extraction_cannot_overwrite_immutable_rendition(self):
        source = self.source('evidence.txt', b'Original evidence.' * 2000)
        self.store.fail_ordinal = 2
        with self.assertRaises(ingest.wc.Fail):
            ingest.ingest(self.cfg, source)
        self.store.fail_ordinal = None
        cache = next((self.root / 'cache/wikicontext/extractions').glob('*.json'))
        record = json.loads(cache.read_text())
        record[2][0]['body'] = 'Different evidence.'
        cache.write_text(json.dumps(record))
        with self.assertRaises(ingest.wc.Fail) as raised:
            ingest.ingest(self.cfg, source)
        self.assertEqual(raised.exception.code, 4)
        self.assertEqual(self.store.tables['passages'][0]['body'], source.read_text()[:24000])

    def test_lfs_pointer_rejected_before_upload(self):
        path = self.source('meeting.wav', b'version https://git-lfs.github.com/spec/v1\noid sha256:abc\n')
        with self.assertRaises(ingest.wc.Fail):
            ingest.ingest(self.cfg, path)
        self.assertFalse(self.store.tables['sources'])

    def test_original_upload_identifies_client(self):
        # Edge proxies reject Python's default urllib signature.
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"id":"source00000000001"}'
        with patch.object(ingest.wc, 'must'), patch.object(ingest.wc, 'load_session', return_value={'token': 'synthetic-token'}), \
                patch.object(ingest.wc.opener, 'open', return_value=response) as request:
            UPLOAD_SOURCE(self.cfg, self.source('note.md', b'fixture'), b'fixture', 'a' * 64, 'Note')
        self.assertEqual(request.call_args.args[0].get_header('User-agent'), ingest.wc.USER_AGENT)

    def test_missing_groq_key_no_provider_request(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(ingest.wc.opener, 'open') as request:
            with self.assertRaises(ingest.wc.Fail):
                ingest.transcribe(self.source('meeting.wav', b'fixture'))
            request.assert_not_called()

    def test_audio_duration_mismatch_prevents_upload(self):
        with patch.dict(os.environ, {'WIKICONTEXT_GROQ_API_KEY': 'synthetic-key'}), patch.object(ingest, 'duration', side_effect=[10.0, 7.0]), patch.object(ingest, 'command'), patch.object(ingest.wc.opener, 'open') as request:
            with self.assertRaises(ingest.wc.Fail):
                ingest.transcribe(self.source('meeting.wav', b'fixture'))
            request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
