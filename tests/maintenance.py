#!/usr/bin/env python3
"""Exercise migration freeze with synthetic WikiContext content over HTTP."""
import argparse
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
import urllib.error
import urllib.request

from integration import ROOT, credentials, server


def frozen_restart(binary, request, admin, token, frozen):
    """A fresh process preserves a frozen snapshot despite changed deploy settings."""
    with tempfile.TemporaryDirectory(prefix='wikicontext-frozen-restart-') as tmp:
        data = Path(tmp) / 'pb_data'
        data.mkdir()
        for source in request.data_dir.glob('*.db'):
            with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as read:
                with sqlite3.connect(data / source.name) as write:
                    read.backup(write)
        shutil.copy2(request.data_dir / 'maintenance.json', data / 'maintenance.json')
        if (request.data_dir / 'storage').exists():
            shutil.copytree(request.data_dir / 'storage', data / 'storage')
        def config_rows(path):
            with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
                return (db.execute('SELECT * FROM _params ORDER BY id').fetchall(),
                        db.execute('SELECT * FROM _collections ORDER BY id').fetchall())
        stored = config_rows(data / 'data.db')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, BASE_URL='https://must-not-apply.example.test',
                   WIKICONTEXT_GOOGLE_CLIENT_ID='synthetic-changed-client',
                   WIKICONTEXT_GOOGLE_CLIENT_SECRET='synthetic-changed-secret')
        common = [str(Path(binary).resolve()), '--dir', str(data),
                  '--migrationsDir', str(ROOT / 'pb_migrations'), '--hooksDir', str(ROOT / 'pb_hooks')]
        def call(method, path, body=None, identity=admin):
            req = urllib.request.Request(f'http://127.0.0.1:{port}' + path,
                data=None if body is None else json.dumps(body).encode(),
                headers={'Content-Type': 'application/json', 'Authorization': identity}, method=method)
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read())
        with (Path(tmp) / 'server.log').open('w+') as log:
            process = subprocess.Popen(common + ['serve', '--http', f'127.0.0.1:{port}'],
                                       cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                for _ in range(150):
                    if process.poll() is not None:
                        log.seek(0)
                        raise AssertionError(log.read())
                    try:
                        state = call('GET', '/api/context/maintenance')
                        break
                    except (OSError, ValueError):
                        time.sleep(.1)
                else:
                    raise AssertionError('frozen restart timed out')
                assert state['state'] == 'read_only' and state['generation'] == frozen['generation'], state
                assert config_rows(data / 'data.db') == stored, 'frozen bootstrap changed configuration'
                assert call('POST', '/api/context/query', {'sql': 'SELECT id FROM pages'}, token)['rows']
                # Existing operator tokens can thaw after a full process restart.
                state = call('PUT', '/api/context/maintenance', {
                    'readOnly': False, 'expectedGeneration': frozen['generation']})
                assert state['state'] == 'writable', state
            finally:
                process.terminate()
                process.wait(timeout=15)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True)
    args = parser.parse_args()
    with server(args.binary) as request:
        admin, user, token = credentials(request)
        records = '/api/collections/'
        page = request('POST', records + 'pages/records', {'slug': 'freeze-evidence', 'kind': 'concept'}, token)
        run = request('POST', records + 'ingestion_runs/records', {'key': 'freeze-synthetic', 'status': 'staging', 'description': 'Synthetic migration freeze'}, token)
        revision = request('POST', records + 'page_revisions/records', {
            'run': run['id'], 'page': page['id'], 'base_revision': '', 'title': 'Synthetic freeze evidence',
            'summary': 'Synthetic', 'body': 'Synthetic freeze fixture [needs verification].',
        }, token)
        boundary = 'synthetic-freeze-boundary'
        original = b'Synthetic immutable evidence'
        fields = {'title': 'Synthetic freeze original', 'original_name': 'synthetic.txt', 'media_type': 'text/plain'}
        body = ''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
                       for key, value in fields.items()).encode()
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="original"; filename="synthetic.txt"\r\n'
                 'Content-Type: text/plain\r\n\r\n').encode() + original + f'\r\n--{boundary}--\r\n'.encode()
        upload = urllib.request.Request(request.base_url + records + 'sources/records', data=body,
            headers={'Authorization': token, 'Content-Type': 'multipart/form-data; boundary=' + boundary}, method='POST')
        with urllib.request.urlopen(upload, timeout=10) as response:
            source = json.load(response)
        original_files = sorted(str(p.relative_to(request.data_dir)) for p in (request.data_dir / 'storage').rglob('*') if p.is_file())
        status = request('GET', '/api/context/maintenance', token=admin)
        request('PUT', '/api/context/maintenance', {'readOnly': True, 'expectedGeneration': status['generation']}, token, (401, 403))
        frozen = request('PUT', '/api/context/maintenance', {'readOnly': True, 'expectedGeneration': status['generation']}, admin)
        assert frozen['state'] == 'read_only', frozen
        marker = json.loads((request.data_dir / 'maintenance.json').read_text())
        assert marker['readOnly'] is True and marker['generation'] == frozen['generation']
        query = lambda sql: request('POST', '/api/context/query', {'sql': sql}, token)
        assert query('SELECT id FROM pages')['rows'] == [[page['id']]]
        request('GET', records + 'pages/records/' + page['id'], token=token)
        file_token = request('POST', '/api/files/token', {}, token)['token']
        file_path = '/api/files/' + source['collectionId'] + '/' + source['id'] + '/' + source['original']
        download = urllib.request.Request(request.base_url + file_path + '?token=' + file_token,
                                          headers={'Authorization': token})
        with urllib.request.urlopen(download, timeout=10) as response:
            assert response.read() == original
        try:
            urllib.request.urlopen(request.base_url + file_path, timeout=10)
            raise AssertionError('anonymous protected download accepted')
        except urllib.error.HTTPError as error:
            assert error.code in (401, 403, 404), error.code
        request('POST', records + 'users/auth-refresh', {}, token)
        for identity in (token, admin):
            request('POST', records + 'pages/records', {'slug': 'blocked', 'kind': 'concept'}, identity, 503)
            request('PATCH', records + 'ingestion_runs/records/' + run['id'], {
                'expected_revision': run['revision'], 'status': 'published',
            }, identity, 503)
            request('POST', '/api/batch', {'requests': [
                {'method': 'POST', 'url': records + 'pages/records', 'body': {'slug': 'blocked-batch', 'kind': 'concept'}},
            ]}, identity, 503)
        # An upload is rejected before the protected original can be persisted.
        try:
            urllib.request.urlopen(upload, timeout=10)
            raise AssertionError('frozen upload accepted')
        except urllib.error.HTTPError as error:
            assert error.code == 503, error.code
        assert query('SELECT id FROM sources')['rows'] == [[source['id']]]
        assert sorted(str(p.relative_to(request.data_dir)) for p in (request.data_dir / 'storage').rglob('*') if p.is_file()) == original_files
        assert not query('SELECT id FROM publications')['rows']
        frozen_restart(args.binary, request, admin, token, frozen)
        request('PUT', '/api/context/maintenance', {'readOnly': False, 'expectedGeneration': status['generation']}, admin, 409)
        thawed = request('PUT', '/api/context/maintenance', {'readOnly': False, 'expectedGeneration': frozen['generation']}, admin)
        assert thawed['state'] == 'writable', thawed
        request('PATCH', records + 'ingestion_runs/records/' + run['id'], {
            'expected_revision': run['revision'], 'status': 'published',
        }, token)
        assert len(query('SELECT id FROM publications')['rows']) == 1
    print('PASS: WikiContext freeze preserves reads, blocks uploads/publication/batch, persists state and explicitly thaws')


if __name__ == '__main__':
    main()
