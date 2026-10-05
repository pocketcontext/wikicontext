#!/usr/bin/env python3
"""Inventory an offline PocketBase snapshot and copy referenced files without overwrite.

This maintenance utility never edits SQLite, deletes objects, or changes deployment.
Supply a consistent standalone snapshot, not a running application's data.db.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys


class MigrationError(Exception):
    pass


def sha(stream):
    h = hashlib.sha256()
    size = 0
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        h.update(block)
        size += len(block)
    return h.hexdigest(), size


def component(value):
    if not isinstance(value, str) or not value or value in ('.', '..') or any(c in value for c in ('/', '\\', '\x00')):
        raise MigrationError('Unsafe file reference')
    return value


def quote(value):
    return '"' + value.replace('"', '""') + '"'


def local_file(root, key):
    path = root
    if root.is_symlink():
        raise MigrationError('Symlink storage root')
    for part in key.split('/'):
        path = path / component(part)
        if path.is_symlink():
            raise MigrationError('Symlink in storage path')
    if not path.is_file():
        raise MigrationError('Referenced file missing')
    return path


def inventory(database, storage):
    if not database.is_file() or database.is_symlink():
        raise MigrationError('Snapshot missing or symlinked')
    if any(Path(str(database) + suffix).exists() for suffix in ('-wal', '-journal')):
        raise MigrationError('Standalone snapshot required; journal or WAL present')
    entries = {}
    found_original = False
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as conn:
        if conn.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise MigrationError('Snapshot integrity check failed')
        for collection, name, kind, fields in conn.execute('SELECT id,name,type,fields FROM _collections'):
            if kind == 'view':
                continue
            for field in json.loads(fields):
                if field['type'] != 'file':
                    continue
                column = field['name']
                original = name == 'sources' and column == 'original'
                found_original |= original
                query = 'SELECT id,' + quote(column) + (',sha256' if original else '') + ' FROM ' + quote(name)
                for row in conn.execute(query):
                    raw = row[1]
                    if not raw:
                        if original:
                            raise MigrationError('Source original missing')
                        continue
                    filenames = json.loads(raw) if field.get('maxSelect', 1) > 1 else [raw]
                    if not isinstance(filenames, list) or (original and not filenames):
                        raise MigrationError('Invalid file field')
                    for filename in filenames:
                        key = '/'.join(map(component, (collection, row[0], filename)))
                        with local_file(storage, key).open('rb') as stream:
                            digest, size = sha(stream)
                        if original and digest != row[2]:
                            raise MigrationError('Source checksum mismatch')
                        entry = {'key': key, 'sha256': digest, 'size': size}
                        if key in entries and entries[key] != entry:
                            raise MigrationError('Conflicting file references')
                        entries[key] = entry
    if not found_original:
        raise MigrationError('WikiContext original file schema missing')
    with database.open('rb') as stream:
        db_sha, _ = sha(stream)
    return {'version': 1, 'database_sha256': db_sha, 'files': sorted(entries.values(), key=lambda e: e['key'])}


def remote_digest(client, bucket, key):
    try:
        result = client.get_object(Bucket=bucket, Key=key)
    except Exception as error:
        code = getattr(error, 'response', {}).get('Error', {}).get('Code')
        if code in ('NoSuchKey', '404'):
            return None
        raise MigrationError('Object read failed') from None
    with closing(result['Body']) as stream:
        return sha(stream)


def transfer(manifest, storage, client, bucket, verify_only=False):
    uploaded = 0
    for entry in manifest['files']:
        key = entry['key']
        expected = (entry['sha256'], entry['size'])
        if entry['size'] > 5 * 1024**3:
            raise MigrationError('File exceeds supported single-object upload size')
        path = local_file(storage, key)
        with path.open('rb') as stream:
            if sha(stream) != expected:
                raise MigrationError('Local file changed since inventory')
            actual = remote_digest(client, bucket, key)
            if actual is None:
                if verify_only:
                    raise MigrationError('Object missing')
                stream.seek(0)
                try:
                    client.put_object(Bucket=bucket, Key=key, Body=stream,
                                      ContentLength=entry['size'], IfNoneMatch='*')
                except Exception as error:
                    if getattr(error, 'response', {}).get('Error', {}).get('Code') not in ('PreconditionFailed', '412'):
                        raise MigrationError('Conditional object creation failed') from None
                else:
                    uploaded += 1
                actual = remote_digest(client, bucket, key)
            if actual != expected:
                raise MigrationError('Destination object mismatch; never overwritten')
    return uploaded


def client_from_env():
    import boto3
    from botocore.config import Config
    values = {name: os.environ.get('WIKICONTEXT_S3_' + name) for name in
              ('ENDPOINT', 'REGION', 'ACCESS_KEY_ID', 'SECRET_ACCESS_KEY', 'BUCKET')}
    if not all(values.values()):
        raise MigrationError('Complete WIKICONTEXT_S3 configuration required')
    endpoint = values['ENDPOINT']
    if '://' not in endpoint:
        endpoint = 'https://' + endpoint
    return boto3.client('s3', endpoint_url=endpoint, region_name=values['REGION'],
                       aws_access_key_id=values['ACCESS_KEY_ID'], aws_secret_access_key=values['SECRET_ACCESS_KEY'],
                       config=Config(connect_timeout=10, read_timeout=60, retries={'max_attempts': 3},
                                     s3={'addressing_style': 'path'})), values['BUCKET']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('inventory', 'copy', 'verify'))
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--storage', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    try:
        current = inventory(args.database, args.storage)
        if args.mode == 'inventory':
            fd = os.open(args.manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(current, stream, sort_keys=True)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            uploaded = 0
        else:
            with args.manifest.open() as stream:
                if json.load(stream) != current:
                    raise MigrationError('Snapshot or files differ from manifest')
            client, bucket = client_from_env()
            uploaded = transfer(current, args.storage, client, bucket, args.mode == 'verify')
        print(json.dumps({'files': len(current['files']), 'bytes': sum(e['size'] for e in current['files']), 'uploaded': uploaded}))
    except MigrationError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        # Provider exceptions and SQL errors can contain private values.
        print('Migration preparation failed; inspect private inputs locally', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
