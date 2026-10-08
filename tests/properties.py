#!/usr/bin/env python3
"""Revisioned catalog metadata, provenance and relationship publication boundaries."""
import argparse
import json
import os
import shutil
from pathlib import Path
import tempfile
from unittest.mock import patch
from integration import ROOT, server, credentials
import search_integration
from search_integration import Fixture, running
from wikicontext_client import ingest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True)
    args = parser.parse_args()
    # Upgrade a populated database without rewriting historical content or manifests.
    with tempfile.TemporaryDirectory(prefix='wiki-properties-upgrade-') as tmp:
        legacy = Path(tmp)/'legacy'
        legacy.mkdir()
        for name in ('pb_hooks', 'pb_migrations'):
            shutil.copytree(ROOT/name, legacy/name)
        (legacy/'pb_migrations/1791400000_properties.js').unlink()
        config = json.loads((ROOT/'pocketcontext.json').read_text())
        config['tables']['page_revisions'] = [key for key in config['tables']['page_revisions'] if key not in ('properties', 'property_evidence')]
        (legacy/'pocketcontext.json').write_text(json.dumps(config))
        work = Path(tmp)/'app'
        with patch.object(search_integration, 'ROOT', legacy), running(args.binary, work) as request:
            _, _, token = credentials(request)
            fixture = Fixture(request, token)
            page = fixture.page('legacy-resource')
            staged = fixture.run('legacy-resource-publication')
            revision = fixture.revision(staged, page)
            publication = fixture.publish(staged)
            before = fixture.query('SELECT id,manifest FROM publications')
            audit = fixture.query('SELECT id FROM audit_log ORDER BY id')
        with running(args.binary, work) as request:
            fixture = Fixture(request, token)
            assert fixture.query('SELECT id,manifest FROM publications') == before
            assert fixture.query('SELECT id FROM audit_log ORDER BY id') == audit
            row = fixture.query('SELECT id,properties,property_evidence FROM page_revisions')[0]
            assert row['id'] == revision['id'] and row['properties'] is None and row['property_evidence'] is None
            assert fixture.search(publication)['hits'][0]['id'] == revision['id']
            staged = fixture.run('upgraded-resource-publication')
            updated = request('POST', '/api/collections/page_revisions/records', dict(run=staged['id'], page=page['id'], base_revision=revision['id'], title='Updated resource', summary='Synthetic upgrade', body='[needs verification]', properties={'catalog_type': 'resource'}), token)
            fixture.publish(staged)
            assert json.loads(fixture.query('SELECT manifest FROM publications ORDER BY sequence DESC LIMIT 1')[0]['manifest'])[page['id']] == updated['id']
            assert fixture.query("SELECT properties FROM page_revisions WHERE id='%s'" % revision['id'])[0]['properties'] is None

    with server(args.binary) as request, tempfile.TemporaryDirectory(prefix='wiki-properties-') as folder:
        _, _, token = credentials(request)
        def create(table, body, expected=200):
            return request('POST', f'/api/collections/{table}/records', body, token, expected)
        def query(sql):
            result = request('POST', '/api/context/query', {'sql': sql}, token)
            assert not result['truncated']
            return [dict(zip(result['columns'], row)) for row in result['rows']]
        def publish(run, expected=200):
            return request('PATCH', '/api/collections/ingestion_runs/records/'+run['id'], {'expected_revision': 1, 'status': 'published'}, token, expected)
        def run(key):
            return create('ingestion_runs', {'key': key, 'status': 'staging', 'description': 'Synthetic catalog test'})
        def revision(staged, page, base='', properties=None, evidence=None, expected=200, body='Synthetic assessment. [needs verification]'):
            return create('page_revisions', {'run': staged['id'], 'page': page['id'], 'base_revision': base, 'title': 'Synthetic resource', 'summary': 'Synthetic catalog', 'body': body, 'properties': properties, 'property_evidence': evidence}, expected)
        def link(rev, page):
            return create('page_links', {'page_revision': rev['id'], 'target': page['id']})
        def cite(rev):
            return create('citations', {'page_revision': rev['id'], 'passage': passage, 'marker': '1'})
        source = Path(folder)/'evidence.txt'
        source.write_text('Synthetic provider observation.')
        with patch.dict(os.environ, {'XDG_CACHE_HOME': folder}):
            ingest.ingest({'url': request.base_url, 'email': 'agent@example.com', 'password': 'SyntheticUserPassword123!'}, source)
        passage = query('SELECT id FROM passages LIMIT 1')[0]['id']
        target = create('pages', {'slug': 'deployment', 'kind': 'entity'})
        page = create('pages', {'slug': 'bucket', 'kind': 'entity'})
        first = run('catalog-first')
        target_rev = revision(first, target)  # Legacy omitted/null properties remain readable.
        props = {'catalog_type': 'resource', 'provider': 'Synthetic', 'deployment_profiles': [target['id']], 'owner': None, 'active': True, 'capacity': 3}
        rev = revision(first, page, properties=props, evidence={'provider': ['1']})
        cite(rev)
        publish(first, 400)  # Relationships require explicit link records.
        assert not query('SELECT id FROM publications')
        assert query("SELECT status FROM ingestion_runs WHERE id='%s'" % first['id'])[0]['status'] == 'staging'
        link(rev, target)
        publish(first)
        # SQL exposes exactly the immutable published metadata.
        row = query("SELECT properties,property_evidence FROM page_revisions WHERE id='%s'" % rev['id'])[0]
        assert json.loads(row['properties']) == props
        assert json.loads(row['property_evidence']) == {'provider': ['1']}
        request('PATCH', '/api/collections/page_revisions/records/'+rev['id'], {'expected_revision': 1, 'properties': {'owner': 'Changed'}}, token, 400)
        # Concurrent property changes use the same base conflict boundary as prose.
        update, stale = run('catalog-update'), run('catalog-stale')
        revised = revision(update, page, rev['id'], {'catalog_type': 'resource', 'owner': 'Reviewed'})
        revision(stale, page, rev['id'], {'catalog_type': 'resource', 'owner': 'Stale'})
        publish(update)
        publish(stale, 409)
        manifests = query('SELECT manifest FROM publications ORDER BY sequence')
        assert json.loads(manifests[0]['manifest'])[page['id']] == rev['id']
        assert json.loads(manifests[1]['manifest'])[page['id']] == revised['id']
        assert json.loads(query("SELECT properties FROM page_revisions WHERE id='%s'" % rev['id'])[0]['properties']) == props
        bad = run('catalog-malformed')
        for malformed in [[], 'text', 2, {'title': 'spoof'}, {'wikicontext_page': 'spoof'}, {'bad-key': 'x'}, {'nested': {}}, {'list': [1]}, {'list': ['x','x']}, {'catalog_type': 'unknown'}, {'resources': ['bad']}, {'resources': target['id']}, {'long': 'x'*2049}, {'number': 9007199254740992}, {f'key_{n}': n for n in range(65)}]:
            revision(bad, page, revised['id'], malformed, expected=400)
        for evidence in [[], {'missing': ['1']}, {'provider': '1'}, {'provider': ['0']}, {'provider': ['1','1']}]:
            revision(bad, page, revised['id'], {'provider': 'Synthetic'}, evidence, expected=400)
        # Missing and unused evidence fail atomically; property-only citation is valid.
        for name, evidence, add_citation, body in [
            ('missing', {'provider': ['1']}, False, '[needs verification]'),
            ('unused', {}, True, '[needs verification]'),
            ('uncited-body', {'provider': ['1']}, True, 'Uncited prose.'),
        ]:
            staged = run(name)
            draft = revision(staged, page, revised['id'], {'provider': 'Synthetic'}, evidence, body=body)
            if add_citation:
                cite(draft)
            publish(staged, 400)
        # A relationship to an unpublished page fails even with its link record.
        missing = create('pages', {'slug': 'unpublished', 'kind': 'entity'})
        staged = run('unpublished-target')
        draft = revision(staged, page, revised['id'], {'resources': [missing['id']]})
        link(draft, missing)
        publish(staged, 400)
        # A current relation prevents archiving its target; historical-only relations do not.
        staged = run('restore-relation')
        related = revision(staged, page, revised['id'], {'deployment_profiles': [target['id']]})
        link(related, target)
        publish(staged)
        archive = run('archive-target')
        create('page_revisions', {'run': archive['id'], 'page': target['id'], 'base_revision': target_rev['id'], 'title': 'Archived deployment', 'summary': 'Synthetic archive', 'body': '[needs verification]', 'archived': True})
        publish(archive, 400)
        assert len(query('SELECT id FROM publications')) == 3
    print('PASS: revisioned properties, immutable history, conflict rollback, bounded metadata, property provenance and relationship graph')


if __name__ == '__main__':
    main()
