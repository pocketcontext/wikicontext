#!/usr/bin/env python3
"""Synthetic private S3 upload/recovery drill; requires dedicated disposable bucket.

Set WIKICONTEXT_S3_* to a local MinIO fixture. Never target real application buckets.
This test deliberately corrupts/deletes only its own uploaded synthetic object.
"""
import argparse
from contextlib import closing, ExitStack
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
import urllib.error
from unittest.mock import patch

import boto3
from botocore.config import Config
import importlib.util
from integration import ROOT, server

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True)
    parser.add_argument('--synthetic-bucket', required=True, help='Exact dedicated test bucket; authorizes destructive fixture checks')
    args = parser.parse_args()
    bucket = os.environ['WIKICONTEXT_S3_BUCKET']
    assert bucket == args.synthetic_bucket
    endpoint = os.environ['WIKICONTEXT_S3_ENDPOINT']
    if '://' not in endpoint:
        endpoint = 'https://' + endpoint
    s3 = boto3.client('s3', endpoint_url=endpoint, region_name=os.environ['WIKICONTEXT_S3_REGION'],
        aws_access_key_id=os.environ['WIKICONTEXT_S3_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['WIKICONTEXT_S3_SECRET_ACCESS_KEY'],
        config=Config(s3={'addressing_style': 'path'}))
    verifier = load('remote_entrypoint', ROOT / 'docker/entrypoint.py')
    smoke = load('remote_smoke', ROOT / 'docker/smoke.py')
    with tempfile.TemporaryDirectory(prefix='wikicontext-s3-test-') as tmp, ExitStack() as stack:
        request = stack.enter_context(server(args.binary))
        admin = smoke.superuser_token(request.base_url, 'admin@example.com', 'SyntheticAdminPassword123!')
        password = 'SyntheticRemotePassword123!'
        user = smoke.provision_user(request.base_url, admin, 'remote@example.test', password)
        client = smoke.Client(request.base_url, 'remote@example.test', password, None)
        doc, meta = smoke.write_record(client, user)
        key = '/'.join((meta[0], doc, meta[1]))
        try:
            # Failed destructive requests must preserve the exact upload and its hash,
            # including operator requests: backup consistency relies on immutability.
            path = '/api/collections/sources/records/' + doc
            for token in (client.token, admin):
                for changes in ({'original': ''}, {'sha256': '0' * 64}, {'title': 'overwritten'}):
                    request('PATCH', path, changes, token=token, expected=(400, 403))
                request('DELETE', path, token=token, expected=(400, 403))
                boundary = 'synthetic-replacement'
                body = (f'--{boundary}\r\nContent-Disposition: form-data; name="original"; filename="replacement.txt"\r\n'
                        f'Content-Type: text/plain\r\n\r\nSynthetic replacement\r\n--{boundary}--\r\n').encode()
                replacement = urllib.request.Request(request.base_url + path, data=body, method='PATCH',
                    headers={'Authorization': token, 'Content-Type': 'multipart/form-data; boundary=' + boundary})
                try:
                    urllib.request.urlopen(replacement, timeout=10).close()
                except urllib.error.HTTPError as error:
                    assert error.code in (400, 403)
                else:
                    raise AssertionError('original replacement was allowed')
            smoke.check_records(client, doc, meta)
            assert not (request.data_dir / 'storage' / key).exists()
            assert s3.get_object(Bucket=bucket, Key=key)['Body'].read() == meta[2]
            verifier.verify(request.data_dir)
            # Database-only recovery must work without any local original-file copies.
            restored = Path(tmp) / 'restored'
            restored.mkdir()
            with closing(sqlite3.connect(f'file:{request.data_dir / "data.db"}?mode=ro', uri=True)) as source:
                with closing(sqlite3.connect(restored / 'data.db')) as dest:
                    source.backup(dest)
            stack.close()  # Stop the original writer before opening the recovered database.
            verifier.verify(restored)
            without_s3 = {key: value for key, value in os.environ.items() if not key.startswith('WIKICONTEXT_S3_')}
            with patch.dict(os.environ, without_s3, clear=True):
                try: verifier.verify(restored)
                except verifier.StartupError: pass
                else: raise AssertionError('stored remote configuration accepted without S3 environment')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            base = f'http://127.0.0.1:{port}'
            with (Path(tmp) / 'server.log').open('w+') as log:
                proc = subprocess.Popen([args.binary, 'serve', '--http=' + base.removeprefix('http://'),
                    '--dir=' + str(restored), '--hooksDir=' + str(ROOT / 'pb_hooks'),
                    '--migrationsDir=' + str(ROOT / 'pb_migrations')], cwd=ROOT, stdout=log, stderr=log)
                try:
                    for _ in range(150):
                        try:
                            urllib.request.urlopen(base + '/up', timeout=1).close(); break
                        except OSError:
                            if proc.poll() is not None: raise AssertionError('restore startup failed')
                            time.sleep(.1)
                    else: raise AssertionError('restore startup timed out')
                    smoke.check_records(smoke.Client(base, 'remote@example.test', password, None), doc, meta)
                finally:
                    proc.terminate(); proc.wait(timeout=15)
            s3.put_object(Bucket=bucket, Key=key, Body=b'Corrupted synthetic original')
            try: verifier.verify(restored)
            except verifier.StartupError: pass
            else: raise AssertionError('corrupt original accepted')
            s3.delete_object(Bucket=bucket, Key=key)
            try: verifier.verify(restored)
            except Exception: pass
            else: raise AssertionError('missing original accepted')
        finally:
            s3.delete_object(Bucket=bucket, Key=key)
    print('PASS: API S3 upload, remote checksum, protected download, database-only recovery, corrupt/missing rejection')


if __name__ == '__main__':
    main()
