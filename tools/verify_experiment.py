#!/usr/bin/env python3
"""Explicit synthetic verification for https://wiki-v2.pocketcontext.com only.

No network request occurs unless --api-and-r2 is supplied. Uses private environment
credentials, emits only check outcomes, and writes a private synthetic-file manifest.
Never point this tool at production. Synthetic immutable source evidence is retained.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
import urllib.error
import urllib.request

BASE = 'https://wiki-v2.pocketcontext.com'


def request(method, path, token=None, data=None, content_type='application/json'):
    headers = {'Content-Type': content_type}
    if token:
        headers['Authorization'] = token
    if isinstance(data, dict):
        data = json.dumps(data).encode()
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b''  # Never expose API payloads or authentication details.


def api(method, path, token=None, data=None):
    status, body = request(method, path, token, data)
    if status != 200:
        raise RuntimeError('API verification request failed')
    return json.loads(body)


def s3(prefix):
    import boto3
    from botocore.config import Config
    endpoint = os.environ[prefix + 'ENDPOINT']
    if '://' not in endpoint:
        endpoint = 'https://' + endpoint
    return boto3.client('s3', endpoint_url=endpoint, region_name=os.environ[prefix + 'REGION'],
        aws_access_key_id=os.environ[prefix + 'ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ[prefix + 'SECRET_ACCESS_KEY'],
        config=Config(connect_timeout=10, read_timeout=30, retries={'max_attempts': 2},
                      s3={'addressing_style': 'path'}))


def local_check(data_dir, manifest):
    record = json.loads(manifest.read_text())
    if record.get('origin') != BASE or not (data_dir / 'data.db').is_file():
        raise RuntimeError('Experimental manifest or database directory missing')
    key = record['object_key']
    if not re.fullmatch(r'[a-zA-Z0-9_]+/[a-z0-9]{15}/[a-zA-Z0-9_.-]+', key):
        raise RuntimeError('Invalid synthetic manifest')
    if (data_dir / 'storage' / key).exists():
        raise RuntimeError('Original unexpectedly exists on local storage')
    print('PASS: synthetic original is absent from local PocketBase storage')


def verify(manifest):
    # Fixed, separately confirmed experiment identities prevent accidental production use.
    if os.environ.get('WIKICONTEXT_URL', BASE).rstrip('/') != BASE:
        raise RuntimeError('Experiment origin mismatch')
    if os.environ['WIKICONTEXT_S3_BUCKET'] != 'wikicontext-v2-files' or os.environ['LITESTREAM_BUCKET'] != 'wikicontext-v2-replica':
        raise RuntimeError('Experiment storage mismatch')
    # Avoid overwriting an earlier run's evidence manifest.
    with manifest.open('x') as out:
        os.chmod(manifest, 0o600)
        json.dump({'status': 'verification-started'}, out)
    admin = api('POST', '/api/collections/_superusers/auth-with-password', data={
        'identity': os.environ['WIKICONTEXT_SUPERUSER_EMAIL'],
        'password': os.environ['WIKICONTEXT_SUPERUSER_PASSWORD']})['token']
    suffix = secrets.token_hex(8)
    password = secrets.token_urlsafe(32)
    email = 'experiment-check-' + suffix + '@example.test'
    user = api('POST', '/api/collections/users/records', admin, {
        'name': 'Synthetic experiment verification', 'email': email,
        'password': password, 'passwordConfirm': password})
    try:
        token = api('POST', '/api/collections/users/auth-with-password', data={
            'identity': email, 'password': password})['token']
        evidence = ('Synthetic WikiContext v2 verification. No company data. ' + suffix + '\n').encode()
        boundary = 'wiki-v2-' + suffix
        body = bytearray()
        for key, value in {'title': 'Synthetic experiment verification', 'original_name': 'synthetic.txt', 'media_type': 'text/plain'}.items():
            body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="original"; filename="synthetic.txt"\r\nContent-Type: text/plain\r\n\r\n'.encode())
        body.extend(evidence)
        body.extend(f'\r\n--{boundary}--\r\n'.encode())
        status, raw = request('POST', '/api/collections/sources/records', token, bytes(body), 'multipart/form-data; boundary=' + boundary)
        if status != 200:
            raise RuntimeError('Synthetic upload failed')
        source = json.loads(raw)
        key = '/'.join((source['collectionId'], source['id'], source['original']))
        record = {'status': 'uploaded', 'origin': BASE, 'source_id': source['id'], 'object_key': key}
        manifest.write_text(json.dumps(record) + '\n')
        expected = hashlib.sha256(evidence).hexdigest()
        if source['sha256'] != expected:
            raise RuntimeError('Server checksum mismatch')
        status, _ = request('GET', '/api/files/' + key)
        if status not in (400, 403, 404):
            raise RuntimeError('Anonymous download was not denied')
        file_token = api('POST', '/api/files/token', token, {})['token']
        status, downloaded = request('GET', '/api/files/' + key + '?token=' + file_token)
        if status != 200 or downloaded != evidence:
            raise RuntimeError('Protected download mismatch')
        with closing(s3('WIKICONTEXT_S3_').get_object(Bucket='wikicontext-v2-files', Key=key)['Body']) as stream:
            if hashlib.sha256(stream.read()).hexdigest() != expected:
                raise RuntimeError('Object storage checksum mismatch')
        print('PASS: ordinary-user API upload, server checksum, protected download, anonymous denial, R2 bytes')
    finally:
        # Operator maintenance only: disable the disposable account and its sessions.
        api('PATCH', '/api/collections/users/records/' + user['id'], admin, {'disabled': True})
    replica = s3('LITESTREAM_')
    prefix = os.environ['LITESTREAM_PATH'].strip('/') + '/'
    for attempt in range(18):
        listing = replica.list_objects_v2(Bucket='wikicontext-v2-replica', Prefix=prefix, MaxKeys=1000)
        if any(item['Key'].endswith('.ltx') for item in listing.get('Contents', [])):
            break
        time.sleep(5)
    else:
        raise RuntimeError('No Litestream replica objects found')
    record['status'] = 'api-and-r2-verified'
    manifest.write_text(json.dumps(record) + '\n')
    print('PASS: replica objects exist; this does not establish final replication or recovery equality')
    print('Synthetic source retained; disposable account disabled; manifest written privately')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--api-and-r2', action='store_true', help='Perform synthetic API writes on fixed experimental origin')
    mode.add_argument('--check-local-storage', type=Path, metavar='PB_DATA', help='Read-only local absence check against the synthetic manifest')
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if args.api_and_r2:
        verify(args.manifest)
    else:
        local_check(args.check_local_storage, args.manifest)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Experiment verification failed; details suppressed to protect credentials and data', file=sys.stderr)
        sys.exit(1)
