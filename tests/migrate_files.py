#!/usr/bin/env python3
"""Synthetic offline file migration checks; no network or application data."""
from contextlib import closing
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('migration', Path(__file__).resolve().parents[1] / 'tools/migrate_files.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Missing(Exception):
    response = {'Error': {'Code': 'NoSuchKey'}}


class Objects:
    def __init__(self):
        self.objects = {}
        self.puts = 0

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise Missing()
        return {'Body': io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, ContentLength, IfNoneMatch):
        assert IfNoneMatch == '*'
        assert Key not in self.objects
        self.objects[Key] = Body.read()
        assert len(self.objects[Key]) == ContentLength
        self.puts += 1


class Migration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'snapshot.db'
        self.storage = self.root / 'storage'
        self.storage.mkdir()
        self.key = 'collection/source/original.txt'
        self.path = self.storage / self.key
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b'synthetic original')
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('CREATE TABLE _collections (id TEXT, name TEXT, type TEXT, fields TEXT)')
            conn.execute('CREATE TABLE sources (id TEXT, original TEXT, sha256 TEXT)')
            conn.execute('INSERT INTO _collections VALUES (?,?,?,?)', ('collection', 'sources', 'base', json.dumps([{'name': 'original', 'type': 'file', 'maxSelect': 1}])))
            conn.execute('INSERT INTO sources VALUES (?,?,?)', ('source', 'original.txt', hashlib.sha256(self.path.read_bytes()).hexdigest()))

    def inventory(self):
        return m.inventory(self.db, self.storage)

    def test_copy_idempotent_and_verify(self):
        manifest = self.inventory()
        objects = Objects()
        self.assertEqual(m.transfer(manifest, self.storage, objects, 'test'), 1)
        self.assertEqual(m.transfer(manifest, self.storage, objects, 'test'), 0)
        self.assertEqual(m.transfer(manifest, self.storage, objects, 'test', True), 0)
        self.assertEqual(objects.puts, 1)

    def test_multifile_and_auth_collection(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('CREATE TABLE users (id TEXT, files TEXT)')
            conn.execute('INSERT INTO _collections VALUES (?,?,?,?)', ('auth', 'users', 'auth', json.dumps([{'name': 'files', 'type': 'file', 'maxSelect': 3}])))
            conn.execute('INSERT INTO users VALUES (?,?)', ('user', json.dumps(['a.txt', 'b.txt'])))
        for filename in ('a.txt', 'b.txt'):
            path = self.storage / 'auth/user' / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic')
        self.assertEqual(len(self.inventory()['files']), 3)

    def test_mismatch_never_overwritten(self):
        objects = Objects()
        objects.objects[self.key] = b'different'
        with self.assertRaises(m.MigrationError):
            m.transfer(self.inventory(), self.storage, objects, 'test')
        self.assertEqual(objects.puts, 0)
        self.assertEqual(objects.objects[self.key], b'different')

    def test_verify_never_writes(self):
        objects = Objects()
        with self.assertRaises(m.MigrationError):
            m.transfer(self.inventory(), self.storage, objects, 'test', True)
        self.assertEqual(objects.puts, 0)

    def test_changed_local_file(self):
        manifest = self.inventory()
        self.path.write_text('changed')
        with self.assertRaises(m.MigrationError):
            m.transfer(manifest, self.storage, Objects(), 'test')

    def test_corrupt_original(self):
        self.path.write_text('corrupt')
        with self.assertRaises(m.MigrationError):
            self.inventory()

    def test_missing_original(self):
        self.path.unlink()
        with self.assertRaises(m.MigrationError):
            self.inventory()

    def test_symlink_directory(self):
        original = self.path.parent
        original.rename(self.storage / 'retained')
        original.symlink_to(self.storage / 'retained', target_is_directory=True)
        with self.assertRaises(m.MigrationError):
            self.inventory()

    def test_traversal(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE sources SET original='../original.txt'")
        with self.assertRaises(m.MigrationError):
            self.inventory()

    def test_wal_refused(self):
        Path(str(self.db) + '-wal').touch()
        with self.assertRaises(m.MigrationError):
            self.inventory()


if __name__ == '__main__':
    unittest.main()
