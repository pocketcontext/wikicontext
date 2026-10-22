#!/usr/bin/env python3
"""Synthetic prompt listing, publication pinning and exact-text output checks."""
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from wikicontext_client import prompts as pr, repository_files as rf, cli


class Prompts(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(cli, 'space_id', return_value='space0000000001')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.page = 'a' * 15
        self.manifest = {self.page: 'b' * 15, 'c' * 15: 'd' * 15}
        self.props = {'catalog_type': 'repository_document', 'document_type': 'prompt', 'output_mode': 'exact_copy',
                      'source_id': 's' * 15, 'purpose': 'Install synthetic skills', 'target_agents': ['codex'],
                      'required_skills': ['example'], 'inputs': ['workspace path'],
                      'approval_boundaries': 'Ask before installing tools', 'last_validated_at': '2026-10-13'}
        self.body, self.original, self.archived = '# Synthetic\n', b'Run only after approval.\r\n\xe2\x9c\x93\n', False
        self.sql = []

    def row(self, page, slug, revision, title, summary, props):
        return {'page': page, 'slug': slug, 'id': revision, 'revision_page': page, 'title': title, 'summary': summary,
                'archived': 0, 'properties': json.dumps(props), 'property_evidence': None}

    def query(self, cfg, sql):
        self.sql.append(sql)
        if sql.startswith('SELECT id,sequence,manifest FROM publications'):
            return [{'id': 'p' * 15, 'sequence': 7 if 'sequence = ' not in sql else int(sql.split('sequence = ')[1].split()[0]), 'manifest': json.dumps(self.manifest)}]
        if sql.startswith('SELECT id,slug FROM pages'):
            return [{'id': self.page, 'slug': 'install-skills'}] if f"'{self.page}'" in sql or "'install-skills'" in sql else []
        other = dict(self.props, purpose='Clean a workspace')
        return [self.row('c' * 15, 'clean-workspace', 'd' * 15, 'Workspace cleanup', 'Remove stale checkouts', other),
                self.row(self.page, 'install-skills', 'b' * 15, 'Install skills', 'Synthetic setup', self.props)]

    def one(self, cfg, table, columns, record):
        if table == 'sources':
            return {'id': record, 'original': 'prompt.md', 'sha256': '0' * 64}
        return {'id': record, 'page': self.page, 'archived': self.archived, 'body': self.body, 'properties': self.props}

    def mocked(self):
        stack = unittest.mock.patch.multiple(pr.exp, query=self.query, one=self.one, download=lambda cfg, source: self.original)
        stack.start()
        self.addCleanup(stack.stop)

    def test_listing_filters_sorts_and_pins(self):
        self.mocked()
        listed = pr.list_prompts({})
        self.assertEqual((listed['sequence'], listed['space']), (7, 'space0000000001'))
        self.assertEqual([p['slug'] for p in listed['prompts']], ['clean-workspace', 'install-skills'])
        self.assertIn('ORDER BY sequence DESC LIMIT 1', self.sql[0])
        self.assertIn("'$.document_type') = 'prompt'", self.sql[1])
        self.assertIn("p.id = 'ppppppppppppppp'", self.sql[1])
        item = listed['prompts'][1]
        self.assertEqual((item['page'], item['revision'], item['output_mode'], item['target_agents']), (self.page, 'b' * 15, 'exact_copy', ['codex']))
        self.assertNotIn('body', item)
        self.assertEqual([p['slug'] for p in pr.list_prompts({}, query='SYNTHETIC install')['prompts']], ['install-skills'])
        self.assertEqual(pr.list_prompts({}, query='workspace stale')['prompts'][0]['slug'], 'clean-workspace')
        self.assertEqual(pr.list_prompts({}, query='install missing')['prompts'], [])
        self.assertEqual(pr.list_prompts({}, sequence=3)['sequence'], 3)
        self.assertIn('sequence = 3', self.sql[-2])
        for sequence in (0, -1, '3', True):
            with self.assertRaises(cli.Fail):
                pr.list_prompts({}, sequence=sequence)

    def test_listing_refuses_unpublished_or_invalid_rows(self):
        self.mocked()
        self.manifest[self.page] = 'x' * 15
        with self.assertRaises(cli.Fail):
            pr.list_prompts({})
        self.manifest[self.page] = 'b' * 15
        self.props['output_mode'] = 'html'
        with self.assertRaises(cli.Fail):
            pr.list_prompts({})

    def test_query_literals_never_interpolate_user_text(self):
        self.mocked()
        with self.assertRaises(cli.Fail):
            pr.render_prompt({}, "x' OR '1'='1", 7)
        self.assertEqual(self.sql, [])
        pr.list_prompts({}, query="x' OR 1=1 --")
        self.assertTrue(all('OR 1=1' not in sql for sql in self.sql))

    def test_slug_and_id_resolution_with_exact_bytes_and_receipt(self):
        self.mocked()
        for page in ('install-skills', self.page):
            content, receipt = pr.render_prompt({}, page, 12)
            self.assertEqual(content, self.original)
            self.assertEqual((receipt['page'], receipt['slug'], receipt['revision'], receipt['source'], receipt['sequence']),
                             (self.page, 'install-skills', 'b' * 15, 's' * 15, 12))
            self.assertEqual(receipt['rendered_sha256'], pr.exp.digest(content))
            self.assertEqual(receipt['approval_boundaries'], 'Ask before installing tools')
        self.assertNotIn(b'Ask before installing tools', content)
        self.assertNotIn(b'target_agents', content)
        for sequence in (None, 0, '12'):
            with self.assertRaises(cli.Fail):
                pr.render_prompt({}, 'install-skills', sequence)

    def test_invalid_utf8_original_refused(self):
        self.mocked()
        self.original = b'Prompt\xff\n'
        with self.assertRaises(cli.Fail):
            pr.render_prompt({}, 'install-skills', 12)

    def test_markdown_uses_shared_portable_refusal(self):
        self.mocked()
        self.props['output_mode'] = 'markdown'
        self.body = '# Synthetic prompt\r\nRun only after explicit approval.\n'
        content, receipt = pr.render_prompt({}, 'install-skills', 12)
        self.assertEqual(content, self.body.encode('utf-8'))
        self.assertNotIn('source', receipt)
        with patch.object(rf, 'portable', side_effect=rf.portable) as portable:
            for body in ('[[Private]]', 'Claim[^1]', '[needs verification]', '> [!NOTE]'):
                self.body = body
                with self.assertRaises(cli.Fail):
                    pr.render_prompt({}, 'install-skills', 12)
            self.assertEqual(portable.call_count, 4)

    def test_archived_non_prompt_and_absent_pages_refused(self):
        self.mocked()
        self.archived = True
        with self.assertRaises(cli.Fail):
            pr.render_prompt({}, 'install-skills', 12)
        self.archived = False
        saved = dict(self.props)
        for props in (dict(saved, document_type='license'), {'catalog_type': 'resource'}):
            self.props = props
            with self.assertRaises(cli.Fail):
                pr.render_prompt({}, 'install-skills', 12)
        self.props = saved
        del self.manifest[self.page]
        with self.assertRaises(cli.Fail):
            pr.render_prompt({}, 'install-skills', 12)
        with self.assertRaises(cli.Fail):
            pr.render_prompt({}, 'missing-prompt', 12)

    def test_export_creates_new_file_only(self):
        self.mocked()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'prompt.md'
            receipt = pr.export({}, 'install-skills', output, 12)
            self.assertEqual(output.read_bytes(), self.original)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(receipt['output'], str(output))
            with self.assertRaises(cli.Fail):
                pr.export({}, 'install-skills', output, 12)
            self.assertEqual(output.read_bytes(), self.original)

    def test_cli_registration(self):
        args = cli.parse(['prompts', '--sequence', '4', '--query', 'setup', '--pretty'])
        self.assertEqual((args.command, args.sequence, args.query, args.pretty), ('prompts', 4, 'setup', True))
        args = cli.parse(['prompt-text', 'install-skills', 'out.md', '--sequence', '4'])
        self.assertEqual((args.page, args.output, args.sequence), ('install-skills', 'out.md', 4))
        with self.assertRaises(SystemExit), patch('sys.stderr'):
            cli.parse(['prompt-text', 'install-skills', 'out.md'])


if __name__ == '__main__':
    unittest.main()
