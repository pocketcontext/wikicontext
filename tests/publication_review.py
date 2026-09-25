#!/usr/bin/env python3
"""Independent synthetic regression checks for publication boundaries and evidence integrity."""
import argparse
import concurrent.futures
import hashlib
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import os
from integration import server, credentials

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/wikicontext/scripts'))
import wc
import ingest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True)
    args = parser.parse_args()
    with server(args.binary) as request, tempfile.TemporaryDirectory(prefix='wikicontext-review-') as folder:
        admin, user, token = credentials(request)
        path = lambda table, record='': '/api/collections/' + table + '/records' + ('/' + record if record else '')
        create = lambda table, body: request('POST', path(table), body, token)
        def query(sql):
            result = request('POST', '/api/context/query', {'sql': sql}, token)
            assert not result['truncated']
            return [dict(zip(result['columns'], row)) for row in result['rows']]
        cfg = {'url': request.base_url, 'email': 'agent@example.com', 'password': 'SyntheticUserPassword123!'}
        with patch.dict(os.environ, {'XDG_CACHE_HOME': folder}):
            source = Path(folder) / 'synthetic-source.txt'
            source.write_text('Synthetic source supporting the test claim.')
            evidence = ingest.ingest(cfg, source)
            # Race direct uploads after warming auth; unique server hash allows only one source.
            racing_source = Path(folder) / 'concurrent-first-upload.txt'
            original = b'Synthetic concurrent first upload evidence.'
            racing_source.write_bytes(original)
            digest = hashlib.sha256(original).hexdigest()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                raced = list(pool.map(lambda _: ingest.upload_source(cfg, racing_source, original, digest, None), range(2)))
            assert len({record['id'] for record in raced}) == 1
            assert len(query('SELECT id FROM sources')) == 2
        passage = query('SELECT id FROM passages LIMIT 1')[0]
        def new_run(key):
            return create('ingestion_runs', {'key': key, 'status': 'staging', 'description': 'Synthetic review ' + key})
        def new_page(slug):
            return create('pages', {'slug': slug, 'kind': 'concept'})
        def revision(run, page, body='Synthetic claim.[^1]', base=''):
            return create('page_revisions', {'run': run['id'], 'page': page['id'], 'base_revision': base, 'title': 'Synthetic title', 'summary': 'Synthetic summary', 'body': body})
        def publish(run, expected=200):
            return request('PATCH', path('ingestion_runs', run['id']), {'expected_revision': run['revision'], 'status': 'published'}, token, expected)
        page = new_page('review-page')
        run = new_run('review-first')
        rev = revision(run, page)
        citation = create('citations', {'page_revision': rev['id'], 'passage': passage['id'], 'marker': '1'})
        # No public/published state survives a transaction attempting a post-publication append.
        before_audit = len(query('SELECT id FROM audit_log'))
        request('POST', '/api/batch', {'requests': [
            {'method': 'PATCH', 'url': path('ingestion_runs', run['id']), 'body': {'expected_revision': 1, 'status': 'published'}},
            {'method': 'POST', 'url': path('citations'), 'body': {'page_revision': rev['id'], 'passage': passage['id'], 'marker': '2'}}
        ]}, token, 400)
        assert not query('SELECT id FROM publications')
        assert query("SELECT status, revision FROM ingestion_runs WHERE id='%s'" % run['id']) == [{'status': 'staging', 'revision': 1}]
        assert len(query('SELECT id FROM audit_log')) == before_audit
        publish(run)
        # Publication content and evidence are immutable even through administrator records API.
        objects = [('sources', evidence['source']), ('renditions', evidence['rendition']), ('passages', passage['id']), ('pages', page['id']), ('page_revisions', rev['id']), ('citations', citation['id'])]
        for table, record in objects:
            for identity in (token, admin):
                request('PATCH', path(table, record), {'expected_revision': 1, 'body': 'mutated'}, identity, 400)
                request('DELETE', path(table, record), token=identity, expected=(403, 404))
        request('POST', path('page_revisions'), {'run': run['id'], 'page': page['id'], 'title': 'Closed draft', 'summary': 'no', 'body': '[needs verification]'}, token, 400)
        request('POST', path('page_links'), {'page_revision': rev['id'], 'target': page['id']}, token, 400)
        request('POST', path('citations'), {'page_revision': rev['id'], 'passage': passage['id'], 'marker': '2'}, token, 400)
        # Explicitly cancelled drafts cannot be amended or reopened, including within a batch.
        cancelled = new_run('cancelled-review')
        p2 = new_page('cancelled-page')
        r2 = revision(cancelled, p2, '[needs verification]')
        request('PATCH', path('ingestion_runs', cancelled['id']), {'expected_revision': 1, 'status': 'cancelled'}, token)
        request('PATCH', path('ingestion_runs', cancelled['id']), {'expected_revision': 2, 'status': 'staging'}, token, 400)
        request('POST', path('page_links'), {'page_revision': r2['id'], 'target': page['id']}, token, 400)
        # A base revision from another page cannot be smuggled into a staging revision.
        foreign = new_run('foreign-base')
        request('POST', path('page_revisions'), {'run': foreign['id'], 'page': p2['id'], 'base_revision': rev['id'], 'title': 'Foreign base', 'summary': 'no', 'body': '[needs verification]'}, token, 400)
        # Attribution and revision counters are server-owned, even when a caller requests a batch.
        for field, value in [('created_by', user['id']), ('updated_by', user['id']), ('revision', 1), ('created', '2020-01-01 00:00:00.000Z'), ('updated', '2020-01-01 00:00:00.000Z')]:
            request('POST', path('pages'), {'slug': 'forged-' + field.replace('_', '-'), 'kind': 'concept', field: value}, token, 400)
        # Definitions are exporter-owned; unused citations and unpublished link targets cannot publish.
        for key, body, add_citation, add_link in [
            ('definition', 'Claim.[^1]\n[^1]: forged source', True, False),
            ('unused', 'Claim [needs verification]', True, False),
            ('unpublished', 'See [[cancelled-page]]. [needs verification]', False, True),
        ]:
            staged = new_run(key)
            draft = revision(staged, page, body, rev['id'])
            if add_citation:
                create('citations', {'page_revision': draft['id'], 'passage': passage['id'], 'marker': '1'})
            if add_link:
                create('page_links', {'page_revision': draft['id'], 'target': p2['id']})
            publish(staged, 400)
        assert len(query('SELECT id FROM publications')) == 1
        assert len(query('SELECT id FROM sources')) == 2
        # Protected originals and SQL reads reject disabled identities, including file tokens.
        source_record = query("SELECT original FROM sources WHERE id='%s'" % evidence['source'])[0]
        file_token = request('POST', '/api/files/token', {}, token)['token']
        request('PATCH', path('users', user['id']), {'disabled': True}, admin)
        request('POST', '/api/context/query', {'sql': 'SELECT id FROM sources'}, token, (401, 403))
        request('GET', path('sources', evidence['source']), token=token, expected=(401, 403))
        request('GET', '/api/files/sources/' + evidence['source'] + '/' + source_record['original'] + '?token=' + file_token, expected=(403, 404))
    print('PASS: batch-close rollback, immutable evidence, closed runs, attribution, citations, source dedupe, access revocation')


if __name__ == '__main__':
    main()
