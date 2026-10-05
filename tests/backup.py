#!/usr/bin/env python3
"""Synthetic complete-backup tests: WAL snapshot, evidence hashes, hostile archives."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('backup', Path(__file__).resolve().parents[1] / 'docker/backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class FakeClientError(Exception):
    def __init__(self, code):
        self.response = {'Error': {'Code': code}}


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.exceptions = type('Exceptions', (), {'ClientError': FakeClientError})
        self.deleted = []
        self.pages = 0
        self.page_size = 2
        self.delete_errors = set()

    def upload_file(self, path, bucket, key):
        self.objects[key] = Path(path).read_bytes()

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise FakeClientError('NoSuchKey')
        return {'Body': io.BytesIO(self.objects[Key])}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise FakeClientError('NoSuchKey')
        return {'ContentLength': len(self.objects[Key])}

    def get_paginator(self, operation):
        assert operation == 'list_objects_v2'
        return self

    def paginate(self, Bucket, Prefix):
        objects = [{'Key': key, 'Size': len(value)} for key, value in sorted(self.objects.items()) if key.startswith(Prefix)]
        for offset in range(0, len(objects), self.page_size):
            self.pages += 1
            yield {'Contents': objects[offset:offset + self.page_size]}

    def delete_objects(self, Bucket, Delete):
        result = {'Deleted': [], 'Errors': []}
        for item in Delete['Objects']:
            key = item['Key']
            if key in self.delete_errors:
                result['Errors'].append({'Key': key, 'Code': 'AccessDenied'})
            else:
                self.objects.pop(key, None)
                self.deleted.append(key)
                result['Deleted'].append({'Key': key})
        return result

    def download_file(self, bucket, key, path):
        Path(path).write_bytes(self.objects[key])


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'live'
        self.original = self.data / 'storage/col/doc/synthetic.txt'
        self.original.parent.mkdir(parents=True)
        self.original.write_bytes(b'Synthetic original source knowledge\n')
        self.conn = sqlite3.connect(self.data / 'data.db')
        self.addCleanup(self.conn.close)
        self.conn.executescript('PRAGMA journal_mode=WAL; CREATE TABLE _collections(id TEXT,name TEXT); INSERT INTO _collections VALUES("col","sources"); CREATE TABLE sources(id TEXT,original TEXT,sha256 TEXT);')
        self.conn.execute('INSERT INTO sources VALUES(?,?,?)', ('doc','synthetic.txt',backup.digest(self.original)))
        self.conn.commit()

    def test_remote_original_verification_needs_no_local_storage(self):
        client = FakeS3()
        key = 'col/doc/synthetic.txt'
        client.objects[key] = self.original.read_bytes()
        self.original.unlink()
        env = {'WIKICONTEXT_S3_' + name: 'synthetic' for name in
               ('BUCKET', 'ENDPOINT', 'REGION', 'ACCESS_KEY_ID', 'SECRET_ACCESS_KEY')}
        with patch.dict(os.environ, env):
            backup.verify_remote(self.data, client)
            client.objects[key] = b'Corrupted'
            with self.assertRaises(RuntimeError):
                backup.verify_remote(self.data, client)
            del client.objects[key]
            with self.assertRaises(FakeClientError):
                backup.verify_remote(self.data, client)

    def test_persisted_remote_mode_without_environment_refuses_even_empty_database(self):
        self.conn.execute('DELETE FROM sources')
        self.conn.execute('CREATE TABLE _params(id TEXT, value TEXT)')
        self.conn.execute('INSERT INTO _params VALUES(?,?)', ('settings', json.dumps({'s3': {'enabled': True}})))
        self.conn.commit()
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(RuntimeError):
            backup.verify(self.data)

    def test_invalid_interval_never_starts_writer(self):
        for value in ('invalid', '0', '3601'):
            with patch.dict(os.environ, {'WIKICONTEXT_BACKUP_INTERVAL': value}), patch.object(backup.subprocess, 'Popen') as start:
                with self.assertRaises((ValueError, RuntimeError)):
                    backup.supervise(['synthetic-writer'])
                start.assert_not_called()

    def archive(self, source, path):
        with tarfile.open(path,'w:gz') as tar:
            for p in source.rglob('*'):
                if p.is_file():
                    tar.add(p,arcname=str(p.relative_to(source)),recursive=False)

    def test_snapshot_recovers_wal_database_and_exact_original(self):
        snapshot = self.root / 'snapshot'
        backup.snapshot(self.data, snapshot)
        archive = self.root / 'snapshot.tar.gz'
        self.archive(snapshot, archive)
        backup.unpack(archive, self.root / 'restored')
        backup.verify(self.root / 'restored')
        self.assertEqual((self.root / 'restored/storage/col/doc/synthetic.txt').read_bytes(),self.original.read_bytes())
        with closing(sqlite3.connect(self.root / 'restored/data.db')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM sources').fetchone()[0],1)

    def test_missing_original_refuses_snapshot_and_startup(self):
        self.original.unlink()
        with self.assertRaises(RuntimeError): backup.verify(self.data)
        with self.assertRaises(RuntimeError): backup.snapshot(self.data,self.root/'snapshot')

    def test_corrupt_original_refuses_snapshot(self):
        self.original.write_bytes(b'changed')
        with self.assertRaises(RuntimeError): backup.snapshot(self.data,self.root/'snapshot')

    def test_corrupt_archive_fails_checksum(self):
        snapshot = self.root/'snapshot'
        backup.snapshot(self.data,snapshot)
        (snapshot/'storage/col/doc/synthetic.txt').write_bytes(b'changed')
        archive=self.root/'snapshot.tar.gz'
        self.archive(snapshot,archive)
        with self.assertRaises(RuntimeError): backup.unpack(archive,self.root/'restored')

    def test_path_traversal_rejected(self):
        archive=self.root/'evil.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            info=tarfile.TarInfo('../outside');info.size=1
            tar.addfile(info,io.BytesIO(b'x'))
        with self.assertRaises(RuntimeError): backup.unpack(archive,self.root/'restored')
        self.assertFalse((self.root/'outside').exists())

    def test_existing_database_never_fetches_remote(self):
        with patch.object(backup,'remote') as remote:
            backup.restore(self.data)
            remote.assert_not_called()

    def test_newer_live_reference_not_in_snapshot_is_detected(self):
        backup.snapshot(self.data,self.root/'snapshot')
        self.conn.execute('INSERT INTO sources VALUES(?,?,?)',('later','absent.txt','a'*64));self.conn.commit()
        with self.assertRaises(RuntimeError): backup.verify(self.data)
        backup.verify(self.root/'snapshot')

    def test_remote_pointer_restores_complete_snapshot(self):
        remote = FakeS3()
        with patch.object(backup, 'remote', return_value=(remote, 'synthetic-bucket', 'synthetic/full-backups')):
            backup.upload(self.data)
            self.assertIn('synthetic/full-backups/latest.json', remote.objects)
            backup.restore(self.root / 'remote-restore')
            backup.verify(self.root / 'remote-restore')
            self.assertEqual((self.root / 'remote-restore/storage/col/doc/synthetic.txt').read_bytes(), self.original.read_bytes())

    def test_archive_upload_failure_never_publishes_pointer(self):
        remote = FakeS3()
        with patch.object(backup, 'remote', return_value=(remote, 'synthetic-bucket', 'synthetic/full-backups')), patch.object(remote, 'upload_file', side_effect=OSError):
            with self.assertRaises(OSError): backup.upload(self.data)
            self.assertFalse(remote.objects)

    def test_corrupt_remote_archive_never_installs_database(self):
        remote = FakeS3()
        with patch.object(backup, 'remote', return_value=(remote, 'synthetic-bucket', 'synthetic/full-backups')):
            backup.upload(self.data)
            pointer = json.loads(remote.objects['synthetic/full-backups/latest.json'])
            remote.objects[pointer['key']] = b'corrupt archive'
            with self.assertRaises(RuntimeError): backup.restore(self.root / 'remote-restore')
            self.assertFalse((self.root / 'remote-restore/data.db').exists())


    def test_pruning_failure_is_nonfatal_after_successful_publication(self):
        remote = FakeS3()
        with patch.dict(os.environ, {'WIKICONTEXT_BACKUP_PRUNE': 'true'}), patch.object(backup, 'remote', return_value=(remote, 'bucket', 'synthetic/full-backups')), patch.object(backup, '_prune', side_effect=RuntimeError('sensitive SDK detail')) as prune, patch('sys.stderr', new_callable=io.StringIO) as err:
            backup.upload(self.data)
            prune.assert_called_once()
            self.assertIn('synthetic/full-backups/latest.json', remote.objects)
            self.assertNotIn('sensitive SDK detail', err.getvalue())

    def test_failed_archive_or_pointer_upload_never_prunes(self):
        for operation in ('upload_file', 'put_object'):
            with self.subTest(operation=operation):
                remote = FakeS3()
                with patch.dict(os.environ, {'WIKICONTEXT_BACKUP_PRUNE': 'true'}), patch.object(backup, 'remote', return_value=(remote, 'bucket', 'synthetic/full-backups')), patch.object(remote, operation, side_effect=OSError), patch.object(backup, '_prune') as prune:
                    with self.assertRaises(OSError):
                        backup.upload(self.data)
                    prune.assert_not_called()

    def test_explicit_historical_restore_without_pointer(self):
        remote = FakeS3()
        with patch.object(backup, 'remote', return_value=(remote, 'bucket', 'synthetic/full-backups')):
            backup.upload(self.data)
            pointer = json.loads(remote.objects.pop('synthetic/full-backups/latest.json'))
            target = self.root / 'historical'
            backup.restore(target, archive_key=pointer['key'])
            backup.verify(target)
            self.assertEqual((target / 'storage/col/doc/synthetic.txt').read_bytes(), self.original.read_bytes())

    def test_historical_restore_refuses_nonempty_destination(self):
        key = 'synthetic/full-backups/20260901T120000Z-' + 'a' * 32 + '.tar.gz'
        for target in (self.data, self.root / 'unrelated'):
            target.mkdir(exist_ok=True)
            (target / 'operator-file').write_text('preserve')
            with patch.object(backup, 'remote') as remote:
                with self.assertRaises(RuntimeError):
                    backup.restore(target, archive_key=key)
                remote.assert_not_called()
                self.assertEqual((target / 'operator-file').read_text(), 'preserve')

    def test_historical_corrupt_manifest_never_installs_database(self):
        for change in ('checksum', 'manifest'):
            with self.subTest(change=change):
                snapshot = self.root / ('bad-' + change)
                backup.snapshot(self.data, snapshot)
                if change == 'checksum':
                    (snapshot / 'storage/col/doc/synthetic.txt').write_bytes(b'corrupt')
                else:
                    manifest = json.loads((snapshot / 'manifest.json').read_text())
                    del manifest['files']['data.db']
                    (snapshot / 'manifest.json').write_text(json.dumps(manifest))
                archive = self.root / (change + '.tar.gz')
                self.archive(snapshot, archive)
                remote = FakeS3()
                key = 'synthetic/full-backups/20260901T120000Z-' + 'a' * 32 + '.tar.gz'
                remote.objects[key] = archive.read_bytes()
                target = self.root / ('restore-' + change)
                with patch.object(backup, 'remote', return_value=(remote, 'bucket', 'synthetic/full-backups')):
                    with self.assertRaises(RuntimeError):
                        backup.restore(target, archive_key=key)
                self.assertFalse((target / 'data.db').exists())

    def test_missing_restore_pointer_is_empty_but_dangling_pointer_fails(self):
        remote = FakeS3()
        with patch.object(backup, 'remote', return_value=(remote, 'bucket', 'synthetic/full-backups')):
            backup.restore(self.root / 'empty')
            self.assertFalse((self.root / 'empty/data.db').exists())
            backup.upload(self.data)
            pointer = json.loads(remote.objects['synthetic/full-backups/latest.json'])
            del remote.objects[pointer['key']]
            with self.assertRaises(FakeClientError):
                backup.restore(self.root / 'dangling')
            self.assertFalse((self.root / 'dangling/data.db').exists())

    def test_pruning_requires_explicit_enablement(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(backup.prune_enabled())
        for value in ('false', 'true'):
            with patch.dict(os.environ, {'WIKICONTEXT_BACKUP_PRUNE': value}):
                self.assertEqual(backup.prune_enabled(), value == 'true')
        for value in ('yes', '', 'TRUE', '1'):
            with patch.dict(os.environ, {'WIKICONTEXT_BACKUP_PRUNE': value}), patch.object(backup.subprocess, 'Popen') as start:
                with self.assertRaises(RuntimeError):
                    backup.supervise(['synthetic-writer'])
                start.assert_not_called()

    def test_complete_recovery_after_pruning_old_archives(self):
        remote = FakeS3()
        prefix = 'synthetic/full-backups'
        now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
        with patch.object(backup, 'remote', return_value=(remote, 'bucket', prefix)):
            backup.upload(self.data)
            pointer = json.loads(remote.objects[prefix + '/latest.json'])
            keys = []
            for i, age in enumerate((1, 3, 500, 600), start=1):
                moment = now - timedelta(days=age)
                key = f'{prefix}/{moment:%Y%m%dT%H%M%SZ}-{i:032x}.tar.gz'
                remote.objects[key] = remote.objects[pointer['key']]
                keys.append(key)
            backup._prune(remote, 'bucket', prefix, now=now)
            self.assertTrue(remote.deleted)
            backup.restore(self.root / 'latest-after-prune')
            backup.restore(self.root / 'historical-after-prune', archive_key=keys[0])
            for name in ('latest-after-prune', 'historical-after-prune'):
                backup.verify(self.root / name)
                self.assertEqual((self.root / name / 'storage/col/doc/synthetic.txt').read_bytes(), self.original.read_bytes())


class RetentionTests(unittest.TestCase):
    prefix = 'synthetic/full-backups'
    now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)

    def setUp(self):
        self.remote = FakeS3()
        self.serial = 0

    def add(self, days=0, hours=0):
        self.serial += 1
        moment = self.now - timedelta(days=days, hours=hours)
        key = f'{self.prefix}/{moment:%Y%m%dT%H%M%SZ}-{self.serial:032x}.tar.gz'
        self.remote.objects[key] = b'synthetic archive'
        return key

    def pointer(self, key):
        self.remote.objects[self.prefix + '/latest.json'] = json.dumps({'key': key, 'sha256': 'a' * 64, 'created': int(self.now.timestamp())}).encode()

    def plan(self):
        return backup.retention_plan(self.remote, 'bucket', self.prefix, now=self.now)

    def test_hourly_daily_monthly_boundaries_and_pagination(self):
        newest = self.add()
        self.pointer(newest)
        recent = [self.add(hours=1), self.add(hours=47), self.add(hours=48)]
        daily = self.add(days=3)
        daily_duplicate = self.add(days=3, hours=1)
        edge_daily = self.add(days=30)
        monthly = self.add(days=31)
        monthly_duplicate = self.add(days=32)
        # Exactly one year remains eligible, one second older does not.
        year_edge = self.add(days=365)
        expired = self.add(days=365, hours=1)
        plan = self.plan()
        kept = {item['key'] for item in plan['retained']}
        deleted = {item['key'] for item in plan['delete']}
        self.assertTrue({newest, *recent, daily, edge_daily, monthly, year_edge} <= kept)
        self.assertEqual(deleted, {daily_duplicate, monthly_duplicate, expired})
        self.assertGreater(self.remote.pages, 1)
        self.assertEqual(plan['retained_bytes'], sum(len(self.remote.objects[k]) for k in kept))
        self.assertEqual(plan['delete_bytes'], sum(len(self.remote.objects[k]) for k in deleted))
        self.assertEqual(plan['latest_key'], newest)

    def test_sparse_history_always_keeps_three_newest_and_latest_target(self):
        keys = [self.add(days=days) for days in (400, 450, 500, 550, 600)]
        self.pointer(keys[-1])
        plan = self.plan()
        self.assertEqual({item['key'] for item in plan['retained']}, set(keys[:3] + [keys[-1]]))
        self.assertEqual([item['key'] for item in plan['delete']], [keys[3]])

    def test_unknown_objects_and_other_prefix_never_deleted(self):
        keys = [self.add(days=days) for days in (1, 2, 3, 700)]
        self.pointer(keys[0])
        unknown = [self.prefix + '/notes.txt', self.prefix + '/20260999T120000Z-' + 'a' * 32 + '.tar.gz', self.prefix + '/nested/' + keys[-1].rsplit('/', 1)[-1], 'synthetic/litestream/snapshot', 'synthetic/full-backups-other/' + keys[-1].rsplit('/', 1)[-1]]
        for key in unknown:
            self.remote.objects[key] = b'leave untouched'
        backup._prune(self.remote, 'bucket', self.prefix, now=self.now)
        self.assertEqual(self.remote.deleted, [keys[-1]])
        self.assertTrue(all(key in self.remote.objects for key in unknown))

    def test_invalid_missing_and_dangling_pointer_abort(self):
        newest = self.add()
        invalid = [None, b'not-json', b'[]', b'{}', json.dumps({'key': 'elsewhere/snapshot.tar.gz', 'sha256': 'a' * 64}).encode(), json.dumps({'key': newest, 'sha256': 'bad', 'created': 0}).encode()]
        for body in invalid:
            with self.subTest(body=body):
                self.remote.objects.pop(self.prefix + '/latest.json', None)
                if body is not None:
                    self.remote.objects[self.prefix + '/latest.json'] = body
                with self.assertRaises(Exception):
                    backup._prune(self.remote, 'bucket', self.prefix, now=self.now)
                self.assertEqual(self.remote.deleted, [])
        self.pointer(newest)
        del self.remote.objects[newest]
        with self.assertRaises(Exception):
            backup._prune(self.remote, 'bucket', self.prefix, now=self.now)
        self.assertEqual(self.remote.deleted, [])

    def test_dry_run_does_not_mutate_bucket(self):
        keys = [self.add(days=days) for days in (1, 2, 3, 700)]
        self.pointer(keys[0])
        before = self.remote.objects.copy()
        backup._prune(self.remote, 'bucket', self.prefix, dry_run=True, now=self.now)
        self.assertEqual(before, self.remote.objects)
        self.assertEqual(self.remote.deleted, [])

    def test_pointer_change_aborts_before_deletion(self):
        keys = [self.add(days=days) for days in (1, 2, 3, 700)]
        self.pointer(keys[0])
        original_plan = backup.retention_plan
        def change(*args, **kwargs):
            plan = original_plan(*args, **kwargs)
            self.pointer(keys[-1])
            return plan
        with patch.object(backup, 'retention_plan', side_effect=change):
            with self.assertRaises(RuntimeError):
                backup._prune(self.remote, 'bucket', self.prefix, now=self.now)
        self.assertEqual(self.remote.deleted, [])

    def test_partial_delete_failure_is_reported_and_latest_survives(self):
        keys = [self.add(days=days) for days in (1, 2, 3, 700, 701)]
        self.pointer(keys[0])
        self.remote.delete_errors.add(keys[-1])
        with self.assertRaises(RuntimeError):
            backup._prune(self.remote, 'bucket', self.prefix, now=self.now)
        self.assertIn(keys[0], self.remote.objects)
        self.assertIn(keys[-1], self.remote.objects)
        self.assertNotIn(keys[-2], self.remote.objects)

    def test_incomplete_delete_response_is_failure(self):
        keys = [self.add(days=days) for days in (1, 2, 3, 700)]
        self.pointer(keys[0])
        with patch.object(self.remote, 'delete_objects', return_value={}):
            with self.assertRaises(RuntimeError):
                backup._prune(self.remote, 'bucket', self.prefix, now=self.now)
        self.assertIn(keys[0], self.remote.objects)

    def test_future_snapshots_are_kept(self):
        keys = [self.add(hours=-hour) for hour in (1, 2, 3, 4, 5)]
        self.pointer(keys[0])
        self.assertEqual(self.plan()['delete'], [])

    def test_large_deletion_batches_are_bounded(self):
        keys = [self.add(days=700 + i) for i in range(1105)]
        self.pointer(keys[0])
        self.remote.page_size = 1000
        with patch.object(self.remote, 'delete_objects', wraps=self.remote.delete_objects) as delete:
            backup._prune(self.remote, 'bucket', self.prefix, now=self.now)
        self.assertEqual(len(self.remote.deleted), 1102)
        self.assertGreater(delete.call_count, 1)
        self.assertTrue(all(len(call.kwargs['Delete']['Objects']) <= 1000 for call in delete.call_args_list))


if __name__=='__main__': unittest.main()
