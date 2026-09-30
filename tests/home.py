#!/usr/bin/env python3
"""Synthetic publication home, conflict, rollback and populated migration checks."""
import argparse
import concurrent.futures
import json
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch

from integration import ROOT, credentials, server
import search_integration
from search_integration import Fixture, running


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True)
    args = parser.parse_args()
    # Exercise an actual populated pre-home schema, then apply the forward migration.
    with tempfile.TemporaryDirectory(prefix='wikicontext-home-upgrade-') as tmp:
        legacy = Path(tmp) / 'legacy'
        legacy.mkdir()
        for name in ('pb_hooks', 'pb_migrations'):
            shutil.copytree(ROOT / name, legacy / name)
        (legacy / 'pb_migrations/1790700000_home.js').unlink()
        config = json.loads((ROOT / 'pocketcontext.json').read_text())
        for table, fields in [('ingestion_runs', ('home', 'home_base', 'clear_home')), ('publications', ('home',))]:
            config['tables'][table] = [field for field in config['tables'][table] if field not in fields]
        (legacy / 'pocketcontext.json').write_text(json.dumps(config))
        work = Path(tmp) / 'app'
        with patch.object(search_integration, 'ROOT', legacy), running(args.binary, work) as request:
            _, _, token = credentials(request)
            f = Fixture(request, token)
            page = f.page('alphabetical-first')
            run = f.run('legacy-publication')
            revision = f.revision(run, page)
            pub = f.publish(run)
            manifest = f.query('SELECT manifest FROM publications')[0]['manifest']
        with running(args.binary, work) as request:
            f = Fixture(request, token)
            assert f.query('SELECT id, home, manifest FROM publications') == [dict(id=pub['id'], home='', manifest=manifest)]
            assert f.query('SELECT home, home_base, clear_home FROM ingestion_runs') == [dict(home='', home_base='', clear_home=False)]
            assert f.search(pub)['hits'][0]['id'] == revision['id']
            home = f.run('post-migration-home', home=page['id'], home_base='')
            f.publish(home)
            assert f.query('SELECT home FROM publications ORDER BY sequence') == [{'home': ''}, {'home': page['id']}]

    with server(args.binary) as request:
        admin, _, token = credentials(request)
        f = Fixture(request, token)
        def update(run, **body):
            return request('PATCH', '/api/collections/ingestion_runs/records/' + run['id'],
                           dict(expected_revision=run['revision'], **body), token)
        def head():
            return f.query('SELECT id, home, manifest FROM publications ORDER BY sequence DESC LIMIT 1')[0]
        def state(run):
            return (f.query('SELECT * FROM publications ORDER BY sequence'),
                    f.query("SELECT * FROM ingestion_runs WHERE id='%s'" % run['id']),
                    f.query('SELECT * FROM audit_log ORDER BY id'), f.generation())
        def reject(run, expected=400):
            before = state(run)
            f.publish(run, expected)
            assert state(run) == before, 'Failed home publication changed committed state'

        a, b, unpublished = f.page('alpha'), f.page('beta'), f.page('unpublished')
        initial = f.run('initial', home=b['id'])
        ar, br = f.revision(initial, a), f.revision(initial, b)
        f.publish(initial)
        first = head()
        assert first['home'] == b['id']
        carried = f.run('carried')
        ar = f.revision(carried, a, ar['id'])
        f.publish(carried)
        assert head()['home'] == b['id']
        home = f.run('home-only', home=a['id'], home_base=b['id'])
        previous_manifest = head()['manifest']
        f.publish(home)
        assert head()['home'] == a['id'] and head()['manifest'] == previous_manifest
        assert f.query("SELECT home FROM publications WHERE id='%s'" % first['id']) == [{'home': b['id']}]
        # Staged choices survive ordinary edits and expose their original expectation.
        stale = f.run('stale-home', home=b['id'], home_base=b['id'])
        stale = update(stale, description='Synthetic edited description')
        reject(stale, 409)
        audit = f.query("SELECT changes FROM audit_log WHERE record='%s'" % stale['id'])
        for entry in audit:
            changes = json.loads(entry['changes']) if isinstance(entry['changes'], str) else entry['changes']
            assert changes['home'] == b['id'] and changes['home_base'] == b['id'] and not changes['clear_home']
        reject(f.run('missing-home', home=unpublished['id'], home_base=a['id']))
        reject(f.run('empty-run'))
        for extra in [dict(home=a['id'], clear_home=True), dict(home_base='invalid'), dict(home='abcdefghijklmno')]:
            request('POST', '/api/collections/ingestion_runs/records',
                    dict(key='invalid-' + str(len(f.query('SELECT id FROM ingestion_runs'))), status='staging', description='Synthetic invalid', **extra), token, (400, 404))
        # Archiving a carried home fails; the same staged archive can explicitly replace it.
        archive = f.run('archive-home')
        ar = f.revision(archive, a, ar['id'], archived=True)
        reject(archive)
        archive = update(archive, home=b['id'], home_base=a['id'])
        f.publish(archive)
        assert head()['home'] == b['id']
        reject(f.run('archived-home', home=a['id'], home_base=b['id']))
        archive_b = f.run('archive-clear', clear_home=True, home_base=b['id'])
        f.revision(archive_b, b, br['id'], archived=True)
        f.publish(archive_b)
        assert head()['home'] == ''
        # Restore both pages, then race independent staged home choices from the same base.
        restore = f.run('restore')
        latest = head()['manifest']
        latest = json.loads(latest) if isinstance(latest, str) else latest
        f.revision(restore, a, latest[a['id']]); f.revision(restore, b, latest[b['id']])
        f.publish(restore)
        left, right = f.run('race-left', home=a['id']), f.run('race-right', home=b['id'])
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda run: f.publish(run, (200, 409)), (left, right)))
        assert sum('sequence' in result for result in results) == 1, results
        assert head()['home'] in (a['id'], b['id'])
        # Audit failure after publishing a home-only run rolls back search generation too.
        failed = f.run('audit-failure', id='pubfailure00001', clear_home=True, home_base=head()['home'])
        reject(failed, (400, 500))
        clear = f.run('clear-only', clear_home=True, home_base=head()['home'])
        old_manifest = head()['manifest']
        f.publish(clear)
        assert head()['home'] == '' and head()['manifest'] == old_manifest
        request('PATCH', '/api/collections/publications/records/' + first['id'], {'home': a['id']}, admin, 403)
    print('PASS: publication home, historical migration, home-only runs, staged conflicts, concurrency, archive/clear, audit and search rollback')


if __name__ == '__main__':
    main()
