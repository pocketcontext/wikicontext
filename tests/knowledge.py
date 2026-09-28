#!/usr/bin/env python3
"""Synthetic SQL fixtures exercise pinned publication traversal and response limits."""
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/wikicontext/scripts'))
import knowledge
import wc


def ident(number):
    return f'{number:015d}'


class Knowledge(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE publications(id TEXT PRIMARY KEY, sequence INTEGER, manifest TEXT);
            CREATE TABLE pages(id TEXT PRIMARY KEY, slug TEXT, kind TEXT);
            CREATE TABLE page_revisions(id TEXT PRIMARY KEY, page TEXT, title TEXT,
                summary TEXT, body TEXT, archived INTEGER);
            CREATE TABLE page_links(id TEXT PRIMARY KEY, page_revision TEXT, target TEXT);
            CREATE TABLE citations(id TEXT PRIMARY KEY, page_revision TEXT, marker INTEGER);
        ''')
        self.calls, self.byte_limit, self.row_limit = [], 1024 * 1024, 500
        self.http413 = False
        patcher = patch.object(wc, 'must', side_effect=self.query)
        patcher.start()
        self.addCleanup(patcher.stop)

    def query(self, cfg, method, path, body):
        self.assertEqual((method, path), ('POST', '/api/context/query'))
        sql = body['sql']
        self.calls.append(sql)
        cursor = self.db.execute(sql)
        columns = [column[0] for column in cursor.description]
        result, size = [], 0
        for row in cursor:
            size += len(json.dumps(row).encode())
            if len(result) >= self.row_limit or size > self.byte_limit:
                if self.http413:
                    raise wc.Fail(1, 'HTTP 413 from POST /api/context/query')
                return dict(columns=columns, rows=result, truncated=True)
            result.append(row)
        return dict(columns=columns, rows=result, truncated=False)

    def fixture(self, count=3, body='Evidence [needs verification].'):
        manifest = {}
        for index in range(count):
            page, revision = ident(index + 1), ident(index + 10001)
            self.db.execute('INSERT INTO pages VALUES (?,?,?)', (page, f'page-{index:04}', 'concept'))
            self.db.execute('INSERT INTO page_revisions VALUES (?,?,?,?,?,?)',
                            (revision, page, f'Title {index}', 'Summary', body, 0))
            manifest[page] = revision
        self.db.execute('INSERT INTO publications VALUES (?,1,?)', (ident(90000), json.dumps(manifest)))
        return manifest

    def test_empty(self):
        self.assertEqual(knowledge.search({}, 'anything'), {'publication': None, 'pages': []})
        self.assertEqual(knowledge.lint({})['findings'], [])

    def test_bounded_pages_and_large_manifest(self):
        manifest = self.fixture(601, body='Tuesday ' + 'x' * 2500)
        # The manifest itself cannot fit in one response, but no query returns it.
        self.byte_limit = 16000
        self.assertGreater(len(json.dumps(manifest)), self.byte_limit)
        result = knowledge.search({}, 'Tuesday')
        self.assertEqual(len(result['pages']), 601)
        self.assertEqual(len({page['id'] for page in result['pages']}), 601)
        self.assertLess(len(self.calls), 150)
        self.assertFalse(any('SELECT id, sequence, manifest' in sql for sql in self.calls))

    def test_http413_retries_and_single_row_failure(self):
        self.fixture(4, body='x' * 1000)
        self.byte_limit, self.http413 = 1500, True
        self.assertEqual(len(knowledge.published({})[1]), 4)
        self.byte_limit = 500
        with self.assertRaisesRegex(wc.Fail, 'HTTP 413'):
            knowledge.published({})

    def test_truncated_single_row_fails_closed(self):
        self.fixture(1, body='x' * 3000)
        self.byte_limit = 1000
        with self.assertRaisesRegex(wc.Fail, 'truncated'):
            knowledge.search({}, 'x')

    def test_manifest_corruption(self):
        manifest = self.fixture()
        key, value = next(iter(manifest.items()))
        corrupt = ['invalid-json', '[]', 'null', '42', '"text"',
                   json.dumps({key: None}), json.dumps({key: 10001}),
                   json.dumps({key: {}}), json.dumps({'bad': value}),
                   json.dumps({'abcdefghijklmno': value}),
                   json.dumps({key: 'missingrevision'}),
                   json.dumps({key: ident(10002)}),
                   '{' + f'"{key}":"{value}","{key}":"{value}"' + '}']
        for data in corrupt:
            with self.subTest(manifest=data):
                self.db.execute('UPDATE publications SET manifest=?', (data,))
                with self.assertRaisesRegex(wc.Fail, 'publication manifest'):
                    knowledge.published({})

    def test_empty_manifest_and_archive_validation(self):
        self.fixture(0)
        self.assertEqual(knowledge.published({})[1], [])
        self.db.execute('DELETE FROM publications')
        manifest = self.fixture(1)
        self.db.execute('UPDATE page_revisions SET archived=1')
        self.assertEqual(knowledge.published({})[1], [])
        self.db.execute('DELETE FROM pages')
        with self.assertRaisesRegex(wc.Fail, 'incomplete publication'):
            knowledge.published({})

    def test_lint_batches_relationships_excludes_drafts_and_archives(self):
        manifest = self.fixture(120)
        pairs = list(manifest.items())
        for index, (page, revision) in enumerate(pairs):
            self.db.execute('INSERT INTO page_links VALUES (?,?,?)',
                            (ident(20000 + index), revision, pairs[(index + 1) % len(pairs)][0]))
            self.db.execute('INSERT INTO citations VALUES (?,?,1)', (ident(30000 + index), revision))
        # Many relationships for one revision require their own keyset pages.
        for index in range(550):
            self.db.execute('INSERT INTO page_links VALUES (?,?,?)',
                            (ident(40000 + index), pairs[0][1], pairs[1][0]))
        self.db.execute('INSERT INTO page_revisions VALUES (?,?,?,?,?,0)',
                        (ident(80000), pairs[0][0], 'Draft', '', 'draft'))
        self.db.execute('INSERT INTO page_links VALUES (?,?,?)', (ident(81000), ident(80000), 'missing'))
        self.db.execute('UPDATE page_revisions SET archived=1 WHERE id=?', (pairs[-1][1],))
        self.db.execute('INSERT INTO page_links VALUES (?,?,?)', (ident(81001), pairs[-1][1], 'missing'))
        result = knowledge.lint({})
        self.assertEqual(len([r for r in result['findings'] if r['kind'] == 'broken-link']), 1)
        self.assertFalse(any(r['kind'] == 'no-citations' for r in result['findings']))
        self.assertEqual(len([r for r in result['findings'] if r['kind'] == 'needs-verification']), 119)
        self.assertLess(len(self.calls), 20)

    def test_new_publication_during_reads_does_not_change_pin(self):
        self.fixture(2)
        query = self.query
        def advancing(*args):
            result = query(*args)
            if len(self.calls) == 1:
                self.db.execute('INSERT INTO publications VALUES (?,2,?)', (ident(90001), '{}'))
            return result
        with patch.object(wc, 'must', side_effect=advancing):
            result = knowledge.search({}, 'Title')
        self.assertEqual(result['publication'], ident(90000))
        self.assertEqual(len(result['pages']), 2)


if __name__ == '__main__':
    unittest.main()
