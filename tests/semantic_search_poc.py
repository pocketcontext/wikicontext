#!/usr/bin/env python3
"""Synthetic CLI semantic search checks: no provider calls or private wiki data."""
import copy
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wiki_search_poc', ROOT / 'tools/semantic_search_poc/cli.py')
poc = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = poc
spec.loader.exec_module(poc)


def ident(number):
    return f'{number:015d}'


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {'url': 'https://wiki.invalid', 'email': 'synthetic@example.invalid'}
        self.identity = ident(900)
        self.publication = {'id': ident(800), 'sequence': 1}
        self.pages = [{'id': ident(100), 'page': ident(1), 'slug': 'access',
                       'title': 'Access revocation', 'summary': 'Account access',
                       'body': '# Access\n\nDisable the account.\n\nRevoke existing sessions.'},
                      {'id': ident(101), 'page': ident(2), 'slug': 'vectors',
                       'title': 'Vector search', 'summary': 'Retrieval',
                       'body': 'Use vectors for semantic similarity.'}]
        self.snapshot = poc.build_snapshot(self.cfg, self.identity, self.publication, self.pages)

    def test_stable_serialization_and_lossless_paragraphs(self):
        self.assertEqual(self.snapshot, poc.build_snapshot(self.cfg, self.identity, self.publication, self.pages))
        self.assertTrue(poc.paragraphs('First.\n\nSecond.'))
        for page in self.snapshot['pages']:
            self.assertEqual(len({p['id'] for p in page['paragraphs']}), len(page['paragraphs']))
            for paragraph in page['paragraphs']:
                self.assertIn(paragraph['text'], page['body'])

    def test_compact_prompt_retains_every_page_and_paragraph(self):
        request = poc.request_body(self.snapshot, 'query', 'gpt-6-luna', 10)
        corpus = json.loads(request['input'][0]['content'].split('\n', 1)[1])
        decoded = [dict(zip(corpus['page_fields'], page)) for page in corpus['pages']]
        self.assertEqual(len(decoded), len(self.snapshot['pages']))
        for actual, expected in zip(decoded, self.snapshot['pages']):
            for field in ('revision_id', 'slug', 'title', 'summary'):
                self.assertEqual(actual[field], expected[field])
            self.assertEqual([dict(zip(corpus['paragraph_fields'], paragraph))
                              for paragraph in actual['paragraphs']], expected['paragraphs'])

    def test_schema_enumerates_exact_prepared_revisions(self):
        request = poc.request_body(self.snapshot, 'query', 'gpt-6-luna', 10)
        schema = request['text']['format']['schema']
        hits = schema['properties']['hits']
        self.assertEqual(hits['items']['properties']['revision_id']['enum'],
                         [p['revision_id'] for p in self.snapshot['pages']])
        self.assertEqual(hits['maxItems'], 10)
        self.assertTrue(request['text']['format']['strict'])
        # Provider schemas supplement, rather than replace, independent validation.
        with self.assertRaises(ValueError):
            poc.validate_results({'hits': [{'revision_id': ident(100) + 'x',
                                           'paragraph_ids': ['p00001']}]}, self.snapshot, 10)

    def test_empty_corpus_schema_disallows_hits_without_invalid_empty_enum(self):
        empty = poc.build_snapshot(self.cfg, self.identity, self.publication, [])
        request = poc.request_body(empty, 'query', 'gpt-6-luna', 10)
        hits = request['text']['format']['schema']['properties']['hits']
        self.assertEqual(hits['maxItems'], 0)
        self.assertEqual(hits['items']['properties']['revision_id'], {'type': 'string'})
        self.assertEqual(poc.validate_results({'hits': []}, empty, 10), [])
        with self.assertRaises(ValueError):
            poc.validate_results({'hits': [{'revision_id': ident(100),
                                           'paragraph_ids': ['p00001']}]}, empty, 10)

    def test_snapshot_rejects_other_identity_origin_and_changed_content(self):
        poc.validate_snapshot(self.snapshot, self.cfg, self.identity)
        with self.assertRaises(ValueError):
            poc.validate_snapshot(self.snapshot, self.cfg, ident(901))
        with self.assertRaises(ValueError):
            poc.validate_snapshot(self.snapshot, dict(self.cfg, url='https://other.invalid'), self.identity)
        changed = copy.deepcopy(self.snapshot)
        changed['pages'][0]['body'] = 'Silently changed cached prose.'
        with self.assertRaises(ValueError):
            poc.validate_snapshot(changed, self.cfg, self.identity)

    def test_results_use_canonical_text_and_pinned_links(self):
        page = self.snapshot['pages'][0]
        paragraph = page['paragraphs'][-1]
        hits = poc.validate_results({'hits': [{'revision_id': page['revision_id'],
                                             'paragraph_ids': [paragraph['id']]}]}, self.snapshot, 10)
        encoded = json.dumps(hits)
        self.assertIn(paragraph['text'], encoded)
        self.assertIn(page['title'], encoded)
        self.assertIn('access', encoded)

    def test_results_reject_fabricated_revision_and_paragraph(self):
        page = self.snapshot['pages'][0]
        for hit in [
            {'revision_id': ident(999), 'paragraph_ids': [page['paragraphs'][0]['id']]},
            {'revision_id': page['revision_id'], 'paragraph_ids': ['fabricated']},
        ]:
            with self.subTest(hit=hit), self.assertRaises(ValueError):
                poc.validate_results({'hits': [hit]}, self.snapshot, 10)

    def test_no_answer_and_duplicate_results(self):
        self.assertEqual(poc.validate_results({'hits': []}, self.snapshot, 10), [])
        page = self.snapshot['pages'][0]
        hit = {'revision_id': page['revision_id'], 'paragraph_ids': [page['paragraphs'][0]['id']]}
        with self.assertRaises(ValueError):
                poc.validate_results({'hits': [hit, hit]}, self.snapshot, 10)


class PreparedCorpusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name) / 'private-cache'
        self.cfg = {'url': 'https://wiki.invalid', 'email': 'synthetic@example.invalid'}
        self.identity = ident(900)
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE publications(id TEXT PRIMARY KEY, sequence INTEGER, manifest TEXT);
            CREATE TABLE pages(id TEXT PRIMARY KEY, slug TEXT, kind TEXT);
            CREATE TABLE page_revisions(id TEXT PRIMARY KEY, page TEXT, title TEXT,
                summary TEXT, body TEXT, archived INTEGER);
        ''')
        for page, slug in [(1, 'access'), (2, 'archived')]:
            self.db.execute('INSERT INTO pages VALUES (?,?,?)', (ident(page), slug, 'concept'))
        for revision, page, body, archived in [(100, 1, 'Old published prose.', 0),
                                              (101, 1, 'New published prose.', 0),
                                              (102, 1, 'Unpublished secret draft.', 0),
                                              (103, 2, 'Archived prose.', 1)]:
            self.db.execute('INSERT INTO page_revisions VALUES (?,?,?,?,?,?)',
                            (ident(revision), ident(page), 'Synthetic title', 'Summary', body, archived))
        for publication, sequence, selected in [(800, 1, 100), (801, 2, 101)]:
            self.db.execute('INSERT INTO publications VALUES (?,?,?)',
                            (ident(publication), sequence, json.dumps({ident(1): ident(selected), ident(2): ident(103)})))
        self.byte_limit = 1000000
        self.search_requests = []
        patcher = patch.object(poc.wc, 'must', side_effect=self.query)
        patcher.start()
        self.addCleanup(patcher.stop)

    def query(self, cfg, method, path, body=None):
        if path == '/api/collections/users/auth-refresh':
            return {'token': 'synthetic-token', 'record': {'id': self.identity,
                    'email': self.cfg['email'], 'collectionName': 'users'}}
        if path == '/api/context/schema':
            return {'tables': []}
        if path == '/api/context/search':
            self.search_requests.append(body)
            return {'index': 'pages', 'scope': body['scope'], 'generation': 'synthetic-generation',
                    'hits': [{'id': ident(100), 'score': -1.0, 'excerpt': 'Old published prose.'}],
                    'hasMore': False, 'truncated': False}
        self.assertEqual((method, path), ('POST', '/api/context/query'))
        cursor = self.db.execute(body['sql'])
        result, size = [], 0
        for row in cursor:
            size += len(json.dumps(row).encode())
            if size > self.byte_limit:
                return {'columns': [c[0] for c in cursor.description], 'rows': result, 'truncated': True}
            result.append(row)
        return {'columns': [c[0] for c in cursor.description], 'rows': result, 'truncated': False}

    def prepared(self):
        poc.prepare(self.cfg, self.cache, sequence=1)
        return poc.load_snapshot(self.cache, self.cfg, self.identity)

    def client(self, hits=None, status='completed'):
        client = MagicMock()
        client.responses.create.return_value = SimpleNamespace(status=status,
            output_text=json.dumps({'hits': hits or []}),
            usage=SimpleNamespace(model_dump=lambda: {'input_tokens': 1000,
                'output_tokens': 10, 'input_tokens_details': {'cached_tokens': 500}}))
        return client

    def test_prepare_selects_exact_history_and_excludes_drafts_archives(self):
        snapshot = self.prepared()
        self.assertEqual(snapshot['publication'], {'id': ident(800), 'sequence': 1})
        self.assertEqual([p['revision_id'] for p in snapshot['pages']], [ident(100)])
        self.assertEqual(snapshot['pages'][0]['body'], 'Old published prose.')
        summary = poc.prepare(self.cfg, self.cache)
        self.assertEqual(summary['publication']['id'], ident(801))
        self.assertEqual(summary['openai_requests'], 0)
        self.assertEqual(os.stat(summary['cache_file']).st_mode & 0o777, 0o600)
        self.assertEqual(self.cache.stat().st_mode & 0o777, 0o700)

    def test_truncated_body_never_replaces_existing_snapshot(self):
        snapshot = self.prepared()
        original = poc.cache_path(self.cache, self.cfg, self.identity).read_bytes()
        self.db.execute('UPDATE page_revisions SET body=? WHERE id=?', ('x' * 5000, ident(101)))
        self.byte_limit = 500
        with self.assertRaises(poc.wc.Fail):
            poc.prepare(self.cfg, self.cache)
        self.assertEqual(poc.cache_path(self.cache, self.cfg, self.identity).read_bytes(), original)
        self.assertEqual(poc.load_snapshot(self.cache, self.cfg, self.identity), snapshot)

    def test_cache_rejects_insecure_permissions_symlinks_and_git_directory(self):
        self.prepared()
        path = poc.cache_path(self.cache, self.cfg, self.identity)
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            poc.load_snapshot(self.cache, self.cfg, self.identity)
        path.unlink()
        path.symlink_to(Path(self.temp.name) / 'not-a-cache')
        with self.assertRaises((ValueError, OSError)):
            poc.load_snapshot(self.cache, self.cfg, self.identity)
        repository = Path(self.temp.name) / 'repo'
        repository.mkdir()
        (repository / '.git').mkdir()
        with self.assertRaises(ValueError):
            poc.private_directory(repository / 'cache')

    def test_search_canonical_output_prefix_and_historical_fts(self):
        snapshot = self.prepared()
        paragraph = snapshot['pages'][0]['paragraphs'][0]
        client = self.client([{'revision_id': ident(100), 'paragraph_ids': [paragraph['id']]}])
        result = poc.search(self.cfg, self.cache, 'old prose', client=client, baseline=True)
        self.assertEqual(result['hits'][0]['excerpt'], 'Old published prose.')
        self.assertIn('?publication=' + ident(800), result['hits'][0]['url'])
        self.assertEqual(self.search_requests[0]['scope'], ident(800))
        request = client.responses.create.call_args.kwargs
        self.assertFalse(request['store'])
        self.assertNotIn('tools', request)
        self.assertNotIn('old prose', request['input'][0]['content'])
        self.assertIn('old prose', request['input'][-1]['content'])
        self.assertNotIn('Unpublished secret draft.', json.dumps(request))

    def test_revoked_user_never_calls_provider(self):
        self.prepared()
        client = self.client()
        with patch.object(poc, 'authenticate', side_effect=poc.wc.Fail(1, 'revoked')):
            with self.assertRaises(poc.wc.Fail):
                poc.search(self.cfg, self.cache, 'test', client=client)
        client.responses.create.assert_not_called()

    def test_changed_prepared_snapshot_stops_before_provider(self):
        old = self.prepared()
        poc.prepare(self.cfg, self.cache)
        client = self.client()
        with self.assertRaisesRegex(ValueError, 'changed during benchmark'):
            poc.search(self.cfg, self.cache, 'test', client=client, expected_digest=old['digest'])
        client.responses.create.assert_not_called()

    def test_invalid_provider_results_retain_billed_usage(self):
        self.prepared()
        client = self.client([{'revision_id': ident(999), 'paragraph_ids': ['invented']}])
        with self.assertRaises(poc.SearchFailure) as failure:
            poc.search(self.cfg, self.cache, 'test', client=client)
        self.assertEqual(failure.exception.metrics['usage']['input_tokens'], 1000)
        self.assertIn('cost', failure.exception.metrics)
        self.assertEqual(failure.exception.validation_reason, 'unknown_or_duplicate_revision')
        client.responses.create.assert_called_once()

    def test_validation_reasons_do_not_echo_provider_text(self):
        self.prepared()
        for output, expected in [('synthetic-secret NOT JSON', 'invalid_json'),
            ('{"hits":[{"revision_id":"000000000000100","paragraph_ids":["synthetic-secret"]}]}',
             'invalid_or_duplicate_paragraph_ids'),
            ('{"private":"synthetic-secret"}', 'invalid_result_shape')]:
            with self.subTest(expected=expected):
                client = self.client()
                client.responses.create.return_value.output_text = output
                with self.assertRaises(poc.SearchFailure) as failure:
                    poc.search(self.cfg, self.cache, 'test', client=client)
                self.assertEqual(failure.exception.validation_reason, expected)
                self.assertNotIn('synthetic-secret', str(failure.exception))
                self.assertNotIn('synthetic-secret', json.dumps(failure.exception.metrics))

    def test_incomplete_output_and_provider_failure_are_not_retried(self):
        self.prepared()
        client = self.client(status='incomplete')
        with self.assertRaisesRegex(ValueError, 'billed'):
            poc.search(self.cfg, self.cache, 'test', client=client)
        client.responses.create.assert_called_once()
        client = self.client()
        client.responses.create.side_effect = RuntimeError('private-provider-body')
        with self.assertRaises(RuntimeError):
            poc.search(self.cfg, self.cache, 'test', client=client)
        client.responses.create.assert_called_once()

    def test_sdk_uses_official_url_and_no_retries(self):
        self.prepared()
        factory = MagicMock(return_value=self.client())
        with patch.dict(sys.modules, {'openai': SimpleNamespace(OpenAI=factory)}), \
             patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-secret', 'OPENAI_BASE_URL': 'https://wrong.invalid'}):
            poc.search(self.cfg, self.cache, 'test', timeout=12)
        self.assertEqual(factory.call_args.kwargs['max_retries'], 0)
        self.assertEqual(factory.call_args.kwargs['base_url'], 'https://api.openai.com/v1')
        self.assertEqual(factory.call_args.kwargs['timeout'], 12)

    def test_count_reauthenticates_and_only_calls_token_count_once(self):
        snapshot = self.prepared()
        client = self.client()
        client.responses.input_tokens.count.return_value = SimpleNamespace(input_tokens=1234)
        with patch.object(poc, 'authenticate', wraps=poc.authenticate) as auth:
            result = poc.count_tokens(self.cfg, self.cache, 'test', client=client)
        auth.assert_called_once_with(self.cfg)
        client.responses.create.assert_not_called()
        client.responses.input_tokens.count.assert_called_once()
        request = poc.request_body(snapshot, 'test', 'gpt-6-luna', 10)
        self.assertEqual(client.responses.input_tokens.count.call_args.kwargs,
                         {key: request[key] for key in ('model', 'input', 'instructions', 'reasoning', 'text')})
        self.assertEqual(result['input_tokens'], 1234)
        self.assertEqual(result['generation_requests'], 0)
        self.assertEqual(result['corpus_digest'], snapshot['digest'])

    def test_count_rejects_revocation_and_invalid_provider_count(self):
        self.prepared()
        client = self.client()
        with patch.object(poc, 'authenticate', side_effect=poc.wc.Fail(1, 'revoked')):
            with self.assertRaises(poc.wc.Fail):
                poc.count_tokens(self.cfg, self.cache, client=client)
        client.responses.input_tokens.count.assert_not_called()
        client.responses.input_tokens.count.return_value = SimpleNamespace(input_tokens=-1)
        with self.assertRaisesRegex(ValueError, 'invalid input token count'):
            poc.count_tokens(self.cfg, self.cache, client=client)
        client.responses.input_tokens.count.assert_called_once()
        client.responses.create.assert_not_called()

    def test_real_sdk_offline_serialization_and_usage(self):
        try:
            import httpx
            from openai import OpenAI
        except ImportError:
            self.skipTest('Install POC requirements to check real SDK with offline transport')
        self.prepared()
        requests = []
        def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={'id': 'resp_synthetic', 'object': 'response',
                'created_at': 1, 'status': 'completed', 'model': 'gpt-6-luna',
                'output': [{'type': 'message', 'id': 'msg_synthetic', 'status': 'completed',
                    'role': 'assistant', 'content': [{'type': 'output_text', 'text': '{"hits":[]}',
                                                    'annotations': []}]}],
                'usage': {'input_tokens': 1000, 'output_tokens': 10, 'total_tokens': 1010,
                    'input_tokens_details': {'cached_tokens': 500, 'cache_write_tokens': 100},
                    'output_tokens_details': {'reasoning_tokens': 0}}})
        with httpx.Client(transport=httpx.MockTransport(respond)) as http_client, \
             OpenAI(api_key='synthetic-only', max_retries=0, http_client=http_client) as client:
            result = poc.search(self.cfg, self.cache, 'test', client=client)
        self.assertEqual(len(requests), 1)
        self.assertEqual(result['hits'], [])
        self.assertFalse(requests[0]['store'])
        self.assertTrue(requests[0]['text']['format']['strict'])
        self.assertEqual(result['metrics']['usage']['input_tokens_details']['cache_write_tokens'], 100)
        self.assertFalse(result['metrics']['cost']['uncertain'])


class AccountingAndCLITests(unittest.TestCase):
    def provider_failure(self, code='rate_limit_exceeded'):
        try:
            import httpx
            from openai import RateLimitError
        except ImportError:
            self.skipTest('Install POC requirements for SDK provider-error checks')
        response = httpx.Response(429, request=httpx.Request('POST', 'https://api.openai.com/v1/responses'), headers={
            'retry-after': '3.5', 'x-ratelimit-limit-tokens': '100000',
            'x-ratelimit-reset-tokens': '1m2.5s', 'x-ratelimit-remaining-tokens': 'synthetic-secret',
            'authorization': 'Bearer synthetic-secret', 'set-cookie': 'private-session',
            'x-request-id': 'private-provider-string'})
        return RateLimitError('synthetic-secret PRIVATE CORPUS echoed in provider message',
                              response=response, body={'code': code, 'type': 'tokens'})

    def test_provider_diagnostics_allowlist_excludes_echoed_private_values(self):
        metadata = poc.provider_error_metadata(self.provider_failure())
        self.assertEqual(metadata['status_code'], 429)
        self.assertEqual(metadata['code'], 'rate_limit_exceeded')
        self.assertEqual(metadata['error_type'], 'tokens')
        self.assertEqual(metadata['headers'], {'retry-after': '3.5',
            'x-ratelimit-limit-tokens': '100000', 'x-ratelimit-reset-tokens': '1m2.5s'})
        self.assertNotIn('synthetic-secret', json.dumps(metadata))
        self.assertNotIn('PRIVATE CORPUS', json.dumps(metadata))
        for code in ['sk-proj-syntheticSecret', 'Bearer secret', 'a' * 100, 'bad\ncode']:
            with self.subTest(code=code):
                self.assertNotIn('code', poc.provider_error_metadata(self.provider_failure(code)))
        unknown = RuntimeError('synthetic-secret')
        unknown.status_code = 429
        unknown.code = 'rate_limit_exceeded'
        self.assertEqual(poc.provider_error_metadata(unknown), {'class': 'RuntimeError'})

    def test_rate_limit_cli_and_benchmark_keep_safe_diagnostics_without_retry(self):
        stderr = io.StringIO()
        with patch.object(poc.wc, 'config', return_value={}), \
             patch.object(poc, 'search', side_effect=self.provider_failure()) as search, \
             contextlib.redirect_stderr(stderr):
            self.assertEqual(poc.main(['search', 'test']), 1)
        search.assert_called_once()
        self.assertIn('rate_limit_exceeded', stderr.getvalue())
        self.assertNotIn('synthetic-secret', stderr.getvalue())
        with patch.object(poc, 'authenticate', return_value=ident(900)), \
             patch.object(poc, 'load_snapshot', return_value={'digest': 'synthetic'}), \
             patch.object(poc, 'search', side_effect=self.provider_failure()) as search:
            report = poc.benchmark({}, '/unused', ['test'], ['gpt-6-luna'], repeat=3)
        search.assert_called_once()
        self.assertEqual(report['failure']['diagnostics']['status_code'], 429)
        self.assertEqual(report['failure']['diagnostics']['code'], 'rate_limit_exceeded')
        self.assertNotIn('synthetic-secret', json.dumps(report))
        self.assertNotIn('PRIVATE CORPUS', json.dumps(report))

    def test_cache_write_cost_not_double_counted_and_unknown_not_free(self):
        cost = poc.estimate_cost('gpt-6-luna', {'input_tokens': 1000000, 'output_tokens': 0,
            'input_tokens_details': {'cached_tokens': 200000, 'cache_write_tokens': 300000}})
        self.assertAlmostEqual(cost['usd'], 2 * (.002 + .0375 + .05))
        unknown = poc.estimate_cost('gpt-6-luna', {})
        self.assertIsNone(unknown['usd'])
        self.assertTrue(unknown['uncertain'])
        uncertain = poc.estimate_cost('gpt-6-luna', {'input_tokens': 1000, 'output_tokens': 0,
                                                 'input_tokens_details': {'cached_tokens': 0}})
        self.assertIsNone(uncertain['usd'])
        self.assertLess(uncertain['lower_usd'], uncertain['upper_usd'])

    def test_benchmark_relevance_and_unlabelled(self):
        def result(*args, **kwargs):
            return {'hits': [{'slug': 'access'}, {'slug': 'vectors'}]}
        with patch.object(poc, 'search', side_effect=result) as search, \
             patch.object(poc, 'authenticate', return_value=ident(900)), \
             patch.object(poc, 'load_snapshot', return_value={'digest': 'synthetic'}):
            report = poc.benchmark({}, '/unused', [{'query': 'revoke', 'expected_slugs': ['access', 'missing']},
                                                  'unlabelled'], ['gpt-6-luna'], repeat=2)
        self.assertEqual(report['requests'], 4)
        self.assertEqual(search.call_count, 4)
        self.assertEqual(report['runs'][0]['relevance']['recall_at_5'], .5)
        self.assertNotIn('relevance', report['runs'][1])

    def test_benchmark_explicit_no_answer_and_partial_failure(self):
        with patch.object(poc, 'authenticate', return_value=ident(900)), \
             patch.object(poc, 'load_snapshot', return_value={'digest': 'synthetic'}), \
             patch.object(poc, 'search', side_effect=[{'hits': []}, RuntimeError('private-provider-data')]) as search:
            report = poc.benchmark({}, '/unused', [{'query': 'absent', 'expected_slugs': []}],
                                   ['gpt-6-luna'], repeat=3)
        self.assertEqual(search.call_count, 2)
        self.assertTrue(report['runs'][0]['relevance']['no_answer_correct'])
        self.assertFalse(report['completed'])
        self.assertNotIn('private-provider-data', json.dumps(report))

    def test_benchmark_partial_failure_keeps_usage_and_fts_relevance(self):
        metrics = {'usage': {'input_tokens': 900}, 'cost': {'usd': None, 'uncertain': True}}
        with patch.object(poc, 'authenticate', return_value=ident(900)), \
             patch.object(poc, 'load_snapshot', return_value={'digest': 'synthetic'}), \
             patch.object(poc, 'search', side_effect=[{'hits': [{'slug': 'access'}],
                'fts': {'pages': [{'slug': 'access'}]}},
                poc.SearchFailure('invalid result', metrics, 'unknown_or_duplicate_revision')]):
            report = poc.benchmark({}, '/unused', [{'query': 'access', 'expected_slugs': ['access']}],
                                   ['gpt-6-luna'], repeat=2, baseline=True)
        self.assertEqual(report['failure']['metrics'], metrics)
        self.assertEqual(report['failure']['validation_reason'], 'unknown_or_duplicate_revision')
        self.assertEqual(report['runs'][0]['relevance']['fts_recall_at_5'], 1)
        self.assertEqual(report['completed_requests'], 1)
        self.assertEqual(report['search_attempts'], 2)

    def test_benchmark_validates_all_queries_before_metered_calls(self):
        with patch.object(poc, 'search') as search, self.assertRaises(ValueError):
            poc.benchmark({}, '/unused', ['fine', {'query': ''}], ['gpt-6-luna'])
        search.assert_not_called()

    def test_benchmark_interval_spaces_trials_without_retries(self):
        with patch.object(poc, 'authenticate', return_value=ident(900)), \
             patch.object(poc, 'load_snapshot', return_value={'digest': 'synthetic'}), \
             patch.object(poc, 'search', side_effect=lambda *args, **kwargs: {'hits': []}) as search, \
             patch.object(poc.time, 'sleep') as sleep:
            report = poc.benchmark({}, '/unused', ['test'], ['gpt-6-luna'], repeat=3, interval=65)
        self.assertEqual(search.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual([call.args for call in sleep.call_args_list], [(65,), (65,)])
        self.assertTrue(report['completed'])

    def test_cli_suppresses_provider_error_details(self):
        stderr = io.StringIO()
        with patch.object(poc.wc, 'config', return_value={}), \
             patch.object(poc, 'search', side_effect=RuntimeError('synthetic-secret private corpus')), \
             contextlib.redirect_stderr(stderr):
            code = poc.main(['search', 'test'])
        self.assertEqual(code, 1)
        self.assertNotIn('synthetic-secret', stderr.getvalue())
        self.assertNotIn('private corpus', stderr.getvalue())

    def test_cli_rejects_invalid_arguments_before_search(self):
        for arguments in [['prepare', '--sequence', '1', '--publication', ident(800)],
                          ['search', 'query', '--model', 'unknown']]:
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                poc.parser().parse_args(arguments)
        with patch.object(poc.wc, 'config', return_value={}), patch.object(poc, 'search') as search, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(poc.main(['search', 'query', '--timeout', '-1']), 1)
        search.assert_not_called()


if __name__ == '__main__':
    unittest.main()
