#!/usr/bin/env python3
"""Run the browser reader against synthetic data and an isolated real server."""
import argparse
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import urllib.request
import urllib.error

from integration import ROOT, credentials, server
sys.path.insert(0, str(ROOT / 'skills/wikicontext/scripts'))
from ingest import multipart


def seed(request):
    admin, user, token = credentials(request)
    def create(table, body):
        return request('POST', '/api/collections/' + table + '/records', body, token)
    original = b'The synthetic observatory opened in 2026. Its telescope studies stars.\n'
    body, media = multipart({'title': 'Observatory source', 'original_name': 'observatory.txt', 'media_type': 'text/plain'},
                            'original', 'observatory.txt', original, 'text/plain')
    upload = urllib.request.Request(request.base_url + '/api/collections/sources/records', body,
                                    {'Authorization': token, 'Content-Type': media})
    with urllib.request.urlopen(upload) as response:
        source = json.load(response)
    rendition = create('renditions', {'source': source['id'], 'kind': 'text', 'processor': 'synthetic browser fixture', 'version_label': 'v1'})
    passage = create('passages', {'rendition': rendition['id'], 'ordinal': 1, 'locator': 'document; line 1', 'body': original.decode()})
    observatory = create('pages', {'slug': 'observatory', 'kind': 'entity'})
    telescope = create('pages', {'slug': 'telescope', 'kind': 'concept'})
    state = {'sequence': 0, 'revision': '', 'pending': None}

    def stage():
        number = state['sequence'] + 1
        run = create('ingestion_runs', {'key': f'browser-{number}', 'status': 'staging', 'description': f'Browser publication {number}', 'sources': [source['id']]})
        revision = create('page_revisions', {'run': run['id'], 'page': observatory['id'], 'base_revision': state['revision'],
            'title': 'Observatory', 'summary': 'A synthetic place to study stars.',
            'body': f'## Opening\n\nPublished edition {number}. The observatory opened in 2026.[^1]\n\nSee [[telescope|the telescope]].\n\n'
                    '> [!NOTE] Reading note\n> These records are synthetic.\n\n'
                    '<script>window.wikiInjected = true</script>\n\n'
                    '<img src="https://invalid.example/tracker" onerror="window.wikiInjected = true">\n\n'
                    '[Unsafe link](javascript:alert(1))\n\n![Remote image](https://invalid.example/pixel.png)\n\n'
                    '| Instrument | Status |\n| --- | --- |\n| Telescope | Ready |\n'})
        create('citations', {'page_revision': revision['id'], 'passage': passage['id'], 'marker': '1', 'note': 'Opening date.'})
        create('page_links', {'page_revision': revision['id'], 'target': telescope['id']})
        if number == 1:
            create('page_revisions', {'run': run['id'], 'page': telescope['id'], 'title': 'Telescope', 'summary': 'Synthetic instrument.', 'body': '## Lens\n\nAn instrument for observing stars. [needs verification]'})
        state['pending'] = (run, revision)
        return {'edition': number}

    def publish():
        if state['pending'] is None:
            stage()
        run, revision = state['pending']
        request('PATCH', '/api/collections/ingestion_runs/records/' + run['id'], {'expected_revision': run['revision'], 'status': 'published'}, token)
        state.update(sequence=state['sequence'] + 1, revision=revision['id'], pending=None)
        return {'edition': state['sequence']}

    publish()
    def control(action):
        if action == '/stage':
            return stage()
        if action == '/publish':
            return publish()
        if action in ('/disable', '/enable'):
            request('PATCH', '/api/collections/users/records/' + user['id'], {'disabled': action == '/disable'}, admin)
            return {'ok': True}
        raise ValueError('Unknown fixture action')
    return control


@contextlib.contextmanager
def controller(control):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                result = control(self.path)
                status = 200
            except Exception as error:
                result, status = {'error': str(error)}, 500
            encoded = json.dumps(result).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        def log_message(self, *_args):
            pass
    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(http.server_port)
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


def check_static(base_url):
    with urllib.request.urlopen(base_url + '/') as response:
        html = response.read().decode()
        assert response.headers['Cache-Control'] == 'no-store'
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert response.headers['X-Frame-Options'] == 'DENY'
        policy = response.headers['Content-Security-Policy']
        assert "script-src 'self'" in policy and "frame-ancestors 'none'" in policy
        assert "'unsafe-inline'" not in policy
    assets = re.findall(r'(?:src|href)="(/assets/[^" ]+)"', html)
    assert assets, 'Built reader assets missing'
    for asset in assets:
        with urllib.request.urlopen(base_url + asset) as response:
            assert response.status == 200 and response.read()
            assert 'immutable' in response.headers['Cache-Control']
    for path in ('/assets/missing.js', '/assets/../pocketcontext.json', '/assets/%2e%2e%2fpocketcontext.json', '/assets/pocketcontext.json'):
        try:
            urllib.request.urlopen(base_url + path)
        except urllib.error.HTTPError as error:
            assert error.code == 404, (path, error.code)
        else:
            raise AssertionError('Unexpected exposed path: ' + path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True)
    args = parser.parse_args()
    with server(args.binary) as request, controller(seed(request)) as control_url, tempfile.TemporaryDirectory(prefix='wikicontext-ui-') as temporary:
        check_static(request.base_url)
        env = dict(os.environ, WIKICONTEXT_TEST_URL=request.base_url, WIKICONTEXT_TEST_CONTROL=control_url,
                   WIKICONTEXT_TEST_OUTPUT=temporary)
        subprocess.run(['pnpm', 'exec', 'playwright', 'test', '--config', 'e2e/playwright.config.ts'],
                       cwd=ROOT / 'ui', env=env, check=True)
    print('PASS: real browser reader, synthetic publication and authentication lifecycle')


if __name__ == '__main__':
    main()
