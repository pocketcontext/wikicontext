#!/usr/bin/env python3
"""Synthetic exporter tests; no network or production files."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/wikicontext/scripts'))
import exporter as exp
import wc


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'vault'
        self.metadata = {'version': 1, 'server': 'https://wiki.invalid', 'publication': 'p' * 15, 'sequence': 1}
        self.files = {'wiki/a.md': b'alpha', 'raw/source.txt': b'original'}

    def publish(self, files=None):
        return exp.publish(self.root, files or self.files, self.metadata)

    def test_repeatable_preserves_unrelated_and_cleans_owned(self):
        self.publish()
        first = (self.root / exp.MANIFEST).read_bytes()
        (self.root / '.obsidian').mkdir()
        (self.root / '.obsidian/app.json').write_text('{}')
        (self.root / 'wiki/personal.md').write_text('local')
        self.publish()
        self.assertEqual(first, (self.root / exp.MANIFEST).read_bytes())
        self.publish({'wiki/b.md': b'beta'})
        self.assertFalse((self.root / 'wiki/a.md').exists())
        self.assertFalse((self.root / 'raw/source.txt').exists())
        self.assertEqual((self.root / 'wiki/personal.md').read_text(), 'local')
        self.assertTrue((self.root / '.obsidian/app.json').exists())

    def test_edits_and_deletions_conflict_before_writes(self):
        self.publish()
        page = self.root / 'wiki/a.md'
        page.write_text('edited')
        with self.assertRaises(wc.Fail):
            self.publish({'wiki/b.md': b'new'})
        self.assertFalse((self.root / 'wiki/b.md').exists())
        self.assertEqual(page.read_text(), 'edited')
        page.unlink()
        with self.assertRaises(wc.Fail):
            self.publish()

    def test_unrelated_collision_and_symlink_refused(self):
        self.root.mkdir()
        (self.root / 'wiki').symlink_to(Path(self.temp.name))
        with self.assertRaises(wc.Fail):
            self.publish()
        (self.root / 'wiki').unlink()
        (self.root / 'wiki').mkdir()
        (self.root / 'wiki/a.md').write_text('my own')
        with self.assertRaises(wc.Fail):
            self.publish()
        with self.assertRaises(wc.Fail):
            exp.publish(self.root, {'../outside': b'oops'}, self.metadata)

    def test_failed_commit_rolls_back_existing_files(self):
        self.publish()
        original = exp.atomic_write
        calls = []
        def fail_once(path, content):
            calls.append(path.name)
            if path.name == 'b.md' and calls.count('b.md') == 1:
                raise OSError('simulated write failure')
            return original(path, content)
        with patch.object(exp, 'atomic_write', side_effect=fail_once):
            with self.assertRaises(OSError):
                self.publish({'wiki/a.md': b'changed', 'wiki/b.md': b'new'})
        self.assertEqual((self.root / 'wiki/a.md').read_bytes(), b'alpha')
        self.assertEqual((self.root / 'raw/source.txt').read_bytes(), b'original')
        self.assertFalse((self.root / exp.JOURNAL).exists())

    def test_pinned_render_and_originals(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        schemas = {
            'publications': 'id,run,sequence INTEGER,manifest,created',
            'pages': 'id,slug,kind',
            'page_revisions': 'id,page,run,title,summary,body,archived INTEGER,created',
            'citations': 'id,page_revision,passage,marker,note',
            'page_links': 'id,page_revision,target',
            'passages': 'id,rendition,locator',
            'renditions': 'id,source',
            'sources': 'id,title,original_name,original,sha256',
            'ingestion_runs': 'id,description,sources',
        }
        for name, schema in schemas.items():
            db.execute(f'CREATE TABLE {name} ({schema})')
        def put(table, values):
            db.execute(f'INSERT INTO {table} VALUES ({",".join("?" for _ in values)})', values)
        pid, rid, run, sid = 'a'*15, 'b'*15, 'c'*15, 'd'*15
        put('publications', ('p'*15, run, 1, json.dumps({pid: rid}), '2026-01-01'))
        put('publications', ('q'*15, 'z'*15, 2, '{}', '2026-01-02'))
        put('pages', (pid, 'example', 'concept'))
        put('page_revisions', (rid, pid, run, 'Example', 'Summary', 'Evidence [^1].', 0, '2026-01-01'))
        put('citations', ('e'*15, rid, 'f'*15, '1', 'supports example'))
        put('passages', ('f'*15, 'g'*15, 'page 1'))
        put('renditions', ('g'*15, sid))
        put('sources', (sid, 'Original', '[bad](url).txt', 'file.txt', exp.digest(b'source')))
        put('ingestion_runs', (run, 'First publication', json.dumps([sid])))
        calls = []
        def sql(cfg, method, path, body):
            self.assertEqual((method, path), ('POST', '/api/context/query'))
            calls.append(body['sql'])
            cursor = db.execute(body['sql'])
            return {'columns': [c[0] for c in cursor.description], 'rows': cursor.fetchall(), 'truncated': False}
        with patch.object(wc, 'must', side_effect=sql), patch.object(exp, 'download', return_value=b'source') as download:
            files, metadata = exp.render({'url': 'https://wiki.invalid'}, 1)
            again, again_meta = exp.render({'url': 'https://wiki.invalid'}, 1)
        self.assertEqual((files, metadata), (again, again_meta))
        self.assertEqual(metadata['sequence'], 1)
        self.assertIn('wiki/example.md', files)
        self.assertIn(f'raw/original-{sid}.txt', files)
        self.assertIn(b'\\[bad\\]\\(url\\).txt', files['wiki/example.md'])
        self.assertNotIn(b'2026-01-02', files['wiki/log.md'])
        self.assertEqual(download.call_count, 2)

    def test_interrupted_export_recovery_preserves_later_edits(self):
        import base64
        self.publish()
        page = self.root / 'wiki/a.md'
        journal = {'before': {'wiki/a.md': base64.b64encode(b'alpha').decode()},
                   'after': {'wiki/a.md': exp.digest(b'partial')}}
        (self.root / exp.JOURNAL).write_bytes(exp.packed(journal))
        page.write_bytes(b'partial')
        self.publish()
        self.assertEqual(page.read_bytes(), b'alpha')
        (self.root / exp.JOURNAL).write_bytes(exp.packed(journal))
        page.write_bytes(b'user edit after crash')
        with self.assertRaises(wc.Fail):
            self.publish()
        self.assertEqual(page.read_bytes(), b'user edit after crash')
        self.assertTrue((self.root / exp.JOURNAL).exists())

    def test_download_hash_verification(self):
        import io
        source = {'id': 'a'*15, 'original': 'original.txt', 'sha256': exp.digest(b'expected')}
        with patch.object(wc, 'must', return_value={'token': 'secret'}), patch.object(wc.opener, 'open', return_value=io.BytesIO(b'wrong')):
            with self.assertRaises(wc.Fail):
                exp.download({'url': 'https://wiki.invalid'}, source)

    def test_tampered_ownership_cannot_remove_obsidian_or_personal_files(self):
        import base64
        self.publish()
        for forbidden in ('.obsidian/settings.json', 'personal.txt', '../outside'):
            manifest = dict(self.metadata, files={forbidden: exp.digest(b'private')})
            (self.root / exp.MANIFEST).write_bytes(exp.packed(manifest))
            with self.assertRaises(wc.Fail):
                self.publish()
            journal = {'before': {forbidden: base64.b64encode(b'private').decode()},
                       'after': {forbidden: None}}
            (self.root / exp.JOURNAL).write_bytes(exp.packed(journal))
            with self.assertRaises(wc.Fail):
                self.publish()
            (self.root / exp.JOURNAL).unlink()

    def test_pagination_retries_smaller_batches_without_skipping(self):
        queries = []
        def response(cfg, method, path, body):
            sql = body['sql']
            queries.append(sql)
            if sql.endswith('LIMIT 100'):
                return {'truncated': True}
            if "id > ''" in sql:
                return {'truncated': False, 'columns': ['id'], 'rows': [['a'*15], ['b'*15]]}
            return {'truncated': False, 'columns': ['id'], 'rows': []}
        with patch.object(wc, 'must', side_effect=response):
            rows = exp.rows({}, 'citations', 'id')
        self.assertEqual([r['id'] for r in rows], ['a'*15, 'b'*15])
        self.assertTrue(queries[1].endswith('LIMIT 50'))
        self.assertIn("id > '" + 'b'*15 + "'", queries[-1])

    def test_truncated_results_fail_closed(self):
        with patch.object(wc, 'must', return_value={'truncated': True}):
            with self.assertRaises(wc.Fail):
                exp.render({'url': 'https://wiki.invalid'})
        self.assertFalse(self.root.exists())


if __name__ == '__main__':
    unittest.main()
