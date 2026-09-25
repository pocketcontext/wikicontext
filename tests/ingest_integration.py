#!/usr/bin/env python3
"""Real HTTP evidence ingestion with synthetic data and isolated storage."""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import urllib.error
import urllib.request
from unittest.mock import patch
from integration import server, credentials

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/wikicontext/scripts'
sys.path.insert(0, str(SCRIPTS))
import wc
spec = importlib.util.spec_from_file_location('ingestion_client', SCRIPTS / 'ingest.py')
ingest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ingest)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True)
    args = parser.parse_args()
    with server(args.binary) as request, tempfile.TemporaryDirectory(prefix='wikicontext-ingest-test-') as folder:
        admin, user, token = credentials(request)
        cfg = {'url': request.base_url, 'email': 'agent@example.com', 'password': 'SyntheticUserPassword123!'}
        with patch.dict(os.environ, {'XDG_CACHE_HOME': str(Path(folder) / 'cache')}):
            source = Path(folder) / 'synthetic-notes.md'
            content = ('Synthetic cited evidence.\n' * 3000).encode()
            source.write_bytes(content)
            real_must = wc.must
            def interrupted(cfg, method, url, body=None):
                if url == wc.records('passages') and body['ordinal'] == 2:
                    raise wc.Fail(1, 'simulated lost client connection before second passage')
                return real_must(cfg, method, url, body)
            with patch.object(wc, 'must', side_effect=interrupted):
                try:
                    ingest.ingest(cfg, source)
                except wc.Fail as error:
                    assert str(error).startswith('simulated lost client'), str(error)
                else:
                    raise AssertionError('Expected interrupted ingestion')
            result = ingest.ingest(cfg, source)
            assert result == ingest.ingest(cfg, source)
            assert result['sha256'] == hashlib.sha256(content).hexdigest()
            stored = ingest.rows(cfg, 'SELECT id, original, sha256 FROM sources')
            assert len(stored) == 1
            passages = ingest.rows(cfg, "SELECT id, ordinal, body FROM passages WHERE rendition = '%s' ORDER BY ordinal" % result['rendition'])
            assert len(passages) == 4
            assert ''.join(p['body'] for p in passages).encode() == content
            file_path = '/api/files/sources/' + stored[0]['id'] + '/' + stored[0]['original']
            try:
                urllib.request.urlopen(request.base_url + file_path)
            except urllib.error.HTTPError as error:
                assert error.code in (403, 404)
            else:
                raise AssertionError('Anonymous original download succeeded')
            file_token = request('POST', '/api/files/token', {}, token)['token']
            with urllib.request.urlopen(request.base_url + file_path + '?token=' + file_token) as response:
                assert response.read() == content
            run = real_must(cfg, 'POST', wc.records('ingestion_runs'), {'key': 'ingestion-fixture', 'description': 'Synthetic ingestion', 'status': 'staging', 'sources': [result['source']]})
            page = real_must(cfg, 'POST', wc.records('pages'), {'slug': 'synthetic-evidence', 'kind': 'summary'})
            revision = real_must(cfg, 'POST', wc.records('page_revisions'), {'run': run['id'], 'page': page['id'], 'base_revision': '', 'title': 'Synthetic evidence', 'summary': 'Synthetic test.', 'body': 'The fixture contains evidence.[^1]'})
            real_must(cfg, 'POST', wc.records('citations'), {'page_revision': revision['id'], 'passage': passages[0]['id'], 'marker': '1'})
            real_must(cfg, 'PATCH', wc.records('ingestion_runs', run['id']), {'expected_revision': 1, 'status': 'published'})
            assert len(ingest.rows(cfg, 'SELECT id FROM publications')) == 1
            assert source.read_bytes() == content
    print('PASS: real upload/hash, duplicate and interrupted resume, protected original, cited publication')


if __name__ == '__main__':
    main()
