#!/usr/bin/env python3
"""Complete immutable-evidence snapshots; never restore a DB without its originals.

Online SQLite backup establishes the snapshot point. Sources are immutable and cannot
be deleted, so copying exactly the snapshot's references afterwards is consistent. Each
snapshot has its own DB/file checksums. A latest pointer is published only after the archive
upload succeeds. Optional retention prunes independent archives. R2 credentials never reach the server.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

DATA = Path(os.environ.get('WIKICONTEXT_DATA_DIR', '/storage/pb_data'))


def digest(path):
    with open(path, 'rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def refs(data):
    """Get immutable original paths and recorded hashes from the snapshot DB."""
    db = data / 'data.db'
    if not db.exists():
        return {}
    with closing(sqlite3.connect(f'file:{db}?mode=ro', uri=True)) as conn:
        if conn.execute('PRAGMA quick_check').fetchone() != ('ok',):
            raise RuntimeError('database integrity check failed')
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='sources' AND type='table'").fetchone():
            return {}
        collection = conn.execute("SELECT id FROM _collections WHERE name='sources'").fetchone()[0]
        result = {}
        for record, filename, sha in conn.execute('SELECT id, original, sha256 FROM sources'):
            if not filename:
                raise RuntimeError('source has no original')
            parts = (collection, record, filename)
            if any(not x or x in ('.', '..') or '/' in x or '\\' in x for x in parts):
                raise RuntimeError('unsafe evidence path')
            if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
                raise RuntimeError('source has no valid checksum')
            result['storage/' + '/'.join(parts)] = sha
        return result


def verify(data):
    for name, expected in refs(data).items():
        path = data / name
        if path.is_symlink() or not path.is_file() or digest(path) != expected:
            raise RuntimeError('missing or corrupt original evidence; startup refused')


def snapshot(data, dest):
    dest.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(f'file:{data / "data.db"}?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(dest / 'data.db')) as target:
            source.backup(target)
            target.execute('PRAGMA journal_mode=DELETE')
    expected = refs(dest)
    for name, sha in expected.items():
        source, target = data / name, dest / name
        if source.is_symlink() or not source.is_file():
            raise RuntimeError('missing original evidence')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if digest(target) != sha:
            raise RuntimeError('original checksum mismatch')
    expected['data.db'] = digest(dest / 'data.db')
    (dest / 'manifest.json').write_text(json.dumps({'version': 1, 'files': expected}, sort_keys=True))
    verify(dest)


def unpack(archive, dest):
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar.getmembers():
            path = Path(member.name)
            if path.is_absolute() or '..' in path.parts or not member.isfile():
                raise RuntimeError('unsafe snapshot archive')
            target = dest / path
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
    manifest = json.loads((dest / 'manifest.json').read_text())
    if manifest.get('version') != 1:
        raise RuntimeError('unsupported snapshot')
    expected = manifest['files']
    actual = {str(p.relative_to(dest)) for p in dest.rglob('*') if p.is_file()} - {'manifest.json'}
    if actual != set(expected) or 'data.db' not in expected:
        raise RuntimeError('incomplete snapshot manifest')
    for name, sha in expected.items():
        if digest(dest / name) != sha:
            raise RuntimeError('snapshot checksum mismatch')
    verify(dest)


def remote():
    import boto3
    from botocore.config import Config
    client = boto3.client('s3', endpoint_url=os.environ.get('LITESTREAM_ENDPOINT') or None,
                          region_name=os.environ.get('LITESTREAM_REGION') or 'us-east-1',
                          aws_access_key_id=os.environ['LITESTREAM_ACCESS_KEY_ID'],
                          aws_secret_access_key=os.environ['LITESTREAM_SECRET_ACCESS_KEY'],
                          config=Config(connect_timeout=10, read_timeout=30,
                                        retries={'max_attempts': 2}, s3={'addressing_style': 'path'}))
    return client, os.environ['LITESTREAM_BUCKET'], os.environ['LITESTREAM_PATH'].rstrip('/') + '/full-backups'


def archive_time(key, prefix):
    """Recognize only this writer's exact archive names in the dedicated prefix."""
    match = re.fullmatch(re.escape(prefix) + r'/(\d{8}T\d{6}Z)-[0-9a-f]{32}\.tar\.gz', key)
    if not match:
        return None
    try:
        return datetime.strptime(match[1], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def read_pointer(client, bucket, prefix):
    response = client.get_object(Bucket=bucket, Key=prefix + '/latest.json')
    with closing(response['Body']) as body:
        raw = body.read(4097)
    if len(raw) > 4096:
        raise RuntimeError('invalid snapshot pointer')
    pointer = json.loads(raw)
    if (not isinstance(pointer, dict) or
            not isinstance(pointer.get('key'), str) or archive_time(pointer['key'], prefix) is None or
            not isinstance(pointer.get('sha256'), str) or
            re.fullmatch('[0-9a-f]{64}', pointer['sha256']) is None or
            type(pointer.get('created')) is not int or pointer['created'] < 0):
        raise RuntimeError('invalid snapshot pointer')
    client.head_object(Bucket=bucket, Key=pointer['key'])
    return pointer


def retention_plan(client, bucket, prefix, now=None):
    """Plan from archive timestamps; unknown keys are never deletion candidates."""
    if now is None:
        now = datetime.now(timezone.utc)
    elif isinstance(now, (int, float)):
        now = datetime.fromtimestamp(now, timezone.utc)
    if now.tzinfo is None:
        raise ValueError('retention time must have a timezone')
    now = now.astimezone(timezone.utc)
    pointer = read_pointer(client, bucket, prefix)
    archives = {}
    ignored = 0
    for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix + '/'):
        for obj in page.get('Contents', []):
            key = obj['Key']
            stamp = archive_time(key, prefix)
            if stamp is None:
                ignored += 1
                continue
            size = obj['Size']
            if type(size) is not int or size < 0:
                raise RuntimeError('invalid archive size')
            archives[key] = (stamp, size)
    if pointer['key'] not in archives:
        raise RuntimeError('latest archive missing from listing')
    ordered = sorted(archives, key=lambda key: (archives[key][0], key), reverse=True)
    keep = set(ordered[:3]) | {pointer['key']}
    days, months = set(), set()
    for key in ordered:
        stamp, _ = archives[key]
        age = (now - stamp).total_seconds()
        if age <= 48 * 3600:  # Future timestamps are preserved too.
            keep.add(key)
        elif age <= 30 * 86400:
            day = stamp.date()
            if day not in days:
                keep.add(key)
                days.add(day)
        elif age <= 365 * 86400:
            month = (stamp.year, stamp.month)
            if month not in months:
                keep.add(key)
                months.add(month)
    retained = [{'key': key, 'size': archives[key][1]} for key in ordered if key in keep]
    delete = [{'key': key, 'size': archives[key][1]} for key in ordered if key not in keep]
    return {'retained': retained, 'delete': delete, 'ignored_count': ignored,
            'retained_bytes': sum(obj['size'] for obj in retained),
            'delete_bytes': sum(obj['size'] for obj in delete),
            'latest_key': pointer['key'], 'pointer': pointer}


def _prune(client, bucket, prefix, dry_run=False, now=None):
    plan = retention_plan(client, bucket, prefix, now)
    report = {'dry_run': dry_run, 'retained_count': len(plan['retained']),
              'delete_count': len(plan['delete']), 'ignored_count': plan['ignored_count'],
              'retained_bytes': plan['retained_bytes'], 'delete_bytes': plan['delete_bytes']}
    if dry_run:
        report['delete'] = plan['delete']
    print(json.dumps(report, sort_keys=True), flush=True)
    if dry_run:
        return plan
    for offset in range(0, len(plan['delete']), 1000):
        # This check supplements the local lock; deployments must still have one writer.
        if read_pointer(client, bucket, prefix) != plan['pointer']:
            raise RuntimeError('latest pointer changed during pruning')
        batch = plan['delete'][offset:offset + 1000]
        response = client.delete_objects(Bucket=bucket, Delete={
            'Objects': [{'Key': obj['key']} for obj in batch], 'Quiet': False})
        deleted = {obj['Key'] for obj in response.get('Deleted', [])}
        if response.get('Errors') or deleted != {obj['key'] for obj in batch}:
            raise RuntimeError('archive deletion incomplete')
    return plan


def prune(data, dry_run=False):
    # Same volume lock as uploads; do not run against a concurrent remote writer.
    data.mkdir(parents=True, exist_ok=True)
    with (data / '.complete-backup.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _prune(*remote(), dry_run=dry_run)


def prune_enabled():
    value = os.environ.get('WIKICONTEXT_BACKUP_PRUNE', 'false')
    if value not in ('true', 'false'):
        raise RuntimeError('WIKICONTEXT_BACKUP_PRUNE must be true or false')
    return value == 'true'


def upload(data):
    enabled = prune_enabled()
    # Manual drills and scheduled/final snapshots serialize on this volume.
    with (data / '.complete-backup.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _upload(data)
        if enabled:
            try:
                _prune(*remote())
            except Exception as error:
                # Cleanup failure must not stop backups or the application writer.
                print('complete backup: pruning failed (' + type(error).__name__ +
                      '); retrying after next backup', file=sys.stderr, flush=True)


def _upload(data):
    client, bucket, prefix = remote()
    with tempfile.TemporaryDirectory(prefix='wikicontext-snapshot-') as temp:
        root = Path(temp)
        snapshot(data, root / 'snapshot')
        archive = root / 'snapshot.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            for path in sorted((root / 'snapshot').rglob('*')):
                if path.is_file():
                    tar.add(path, arcname=str(path.relative_to(root / 'snapshot')), recursive=False)
        key = prefix + '/' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex + '.tar.gz'
        client.upload_file(str(archive), bucket, key)
        pointer = json.dumps({'key': key, 'sha256': digest(archive), 'created': int(time.time())}).encode()
        client.put_object(Bucket=bucket, Key=prefix + '/latest.json', Body=pointer, ContentType='application/json')
    print('complete backup: uploaded verified database and originals', flush=True)


def restore(data, archive_key=None):
    if archive_key is not None and data.exists() and (not data.is_dir() or any(data.iterdir())):
        raise RuntimeError('historical restore requires an empty destination')
    # An existing local database always wins. Never roll it backwards automatically.
    if (data / 'data.db').exists():
        verify(data)
        return
    client, bucket, prefix = remote()
    pointer = None
    if archive_key is None:
        try:
            pointer = read_pointer(client, bucket, prefix)
        except client.exceptions.ClientError as error:
            # Only a missing pointer permits the entrypoint's empty-replica check.
            # A dangling pointer must fail closed instead of treating the bucket as empty.
            if error.response['Error']['Code'] in ('NoSuchKey', '404'):
                try:
                    client.head_object(Bucket=bucket, Key=prefix + '/latest.json')
                except client.exceptions.ClientError as missing:
                    if missing.response['Error']['Code'] in ('NoSuchKey', '404'):
                        return
                raise
            raise
        archive_key = pointer['key']
    elif archive_time(archive_key, prefix) is None:
        raise RuntimeError('invalid historical archive key')
    data.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='wikicontext-restore-', dir=data.parent) as temp:
        root = Path(temp)
        archive = root / 'snapshot.tar.gz'
        client.download_file(bucket, archive_key, str(archive))
        if pointer is not None and digest(archive) != pointer['sha256']:
            raise RuntimeError('snapshot archive checksum mismatch')
        unpack(archive, root / 'snapshot')
        data.mkdir(parents=True, exist_ok=True)
        if (data / 'storage').exists():
            raise RuntimeError('partial local storage exists; operator recovery required')
        if (root / 'snapshot/storage').exists():
            shutil.move(str(root / 'snapshot/storage'), data / 'storage')
        # Install the DB last, so partial restores never appear complete.
        os.replace(root / 'snapshot/data.db', data / 'data.db')
    verify(data)
    print('complete backup: restored verified database and originals', flush=True)


def supervise(command):
    interval = int(os.environ.get('WIKICONTEXT_BACKUP_INTERVAL', '3600'))
    if not 1 <= interval <= 3600:
        raise RuntimeError('backup interval must be between 1 and 3600 seconds')
    prune_enabled()  # Validate configuration before starting the application.
    child = subprocess.Popen(command)
    stopping = False
    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        if child.poll() is None:
            child.send_signal(signum)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    due = time.monotonic() + 5
    try:
        while child.poll() is None:
            if not stopping and time.monotonic() >= due and (DATA / 'data.db').exists():
                upload(DATA)
                due = time.monotonic() + interval
            time.sleep(0.2)
        code = child.wait()
        if code == 0 and (DATA / 'data.db').exists():
            upload(DATA)
        return code
    except BaseException:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=45)
        raise


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    restore_parser = modes.add_parser('restore')
    restore_parser.add_argument('--archive', dest='archive_key')
    modes.add_parser('verify')
    modes.add_parser('upload')
    prune_parser = modes.add_parser('prune')
    prune_parser.add_argument('--dry-run', action='store_true')
    supervisor = modes.add_parser('supervise')
    supervisor.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.mode == 'supervise':
        return supervise(args.command)
    if args.mode == 'restore':
        restore(DATA, args.archive_key)
    elif args.mode == 'prune':
        prune(DATA, args.dry_run)
    else:
        {'verify': verify, 'upload': upload}[args.mode](DATA)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        # SDK errors can embed endpoints or credentials; never log their representations.
        print('complete backup failed (' + type(error).__name__ + '); operator recovery required', file=sys.stderr)
        sys.exit(1)
