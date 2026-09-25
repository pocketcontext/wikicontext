#!/usr/bin/env python3
"""Synthetic ingestion recovery tests; never call Groq or production APIs."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
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
        return self.create(cfg, 'POST', '/api/collections/sources/records', {'sha256': digest})

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
                ingest.ingest(self.cfg, source)
        self.assertEqual(len(self.store.tables['sources']), 1)
        self.assertEqual(len(self.store.tables['renditions']), 0)
        transcript = [{'locator': 'seconds 0-1', 'body': 'Synthetic transcript.'}]
        with patch.object(ingest, 'transcribe', return_value=transcript) as provider:
            ingest.ingest(self.cfg, source)
            ingest.ingest(self.cfg, source)
            self.assertEqual(provider.call_count, 1)
        self.assertEqual(source.read_bytes(), b'synthetic audio fixture')

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
