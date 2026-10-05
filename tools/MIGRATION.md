# Production file migration preparation

`migrate_files.py` is an operator maintenance tool, not a knowledge ingestion
client. It reads a consistent offline PocketBase database snapshot and local
storage. It does not modify database records, initialize replication, change
settings, delete objects, or switch deployments.

The snapshot and storage directory are private inputs outside Git. Take the
snapshot using SQLite's backup API (or the existing complete-backup tool) after
freezing application writes; do not copy an open `data.db` without its WAL.
An initial snapshot can support pre-copy while production remains online, but
only a final frozen snapshot and reconciliation establish the migration boundary.
The tool refuses WAL/journal siblings and requires a standalone snapshot. That
check does not itself prove that the operator supplied a consistent snapshot.
Use a read-only mount and no concurrent writers for final verification.

Inventory covers every file field in every non-view collection, including auth
collection file fields. PocketBase keys retain collection ID, record ID and
filename. Source originals also must match their stored SHA-256. Missing files,
unsafe path components and symlink storage entries stop the operation. Thumbnails
and unreferenced files are not transferred: they are not authoritative referenced
originals. Preserve the old complete volume separately for recovery.

```sh
python3 tools/migrate_files.py inventory \
  --database /private/final-snapshot/data.db \
  --storage /private/source-storage \
  --manifest /private/final-files.json
```

The manifest is created exclusively with mode 0600 and includes private object
keys, sizes, hashes and the exact snapshot database digest. Output contains only
counts and bytes. Reusing the manifest path fails rather than replacing evidence.
Each later command regenerates the inventory and requires exact manifest equality.

Install boto3 in an isolated environment for the next commands. Load scoped
`WIKICONTEXT_S3_BUCKET`, `WIKICONTEXT_S3_ENDPOINT`, `WIKICONTEXT_S3_REGION`,
`WIKICONTEXT_S3_ACCESS_KEY_ID`, and `WIKICONTEXT_S3_SECRET_ACCESS_KEY` privately;
never echo them or put them on the command line. Use the reviewed dedicated
production destination bucket, never an experiment replica bucket.

```sh
python3 tools/migrate_files.py copy \
  --database /private/final-snapshot/data.db \
  --storage /private/source-storage \
  --manifest /private/final-files.json
python3 tools/migrate_files.py verify \
  --database /private/final-snapshot/data.db \
  --storage /private/source-storage \
  --manifest /private/final-files.json
```

Copy first reads any existing object. Equal objects are reused. Missing objects
are created with `If-None-Match: *`, then downloaded and hashed in full. A racing
creation is accepted only if its complete bytes match. Different existing bytes
fail without overwrite. Access-denied and other read errors never count as
absence. Interrupted copies can be resumed; uploaded objects are never deleted.
Verify never issues writes. Single objects above 5 GiB are explicitly unsupported.
The tool assumes trusted offline files with no concurrent replacement; it is not
a sandbox for a hostile filesystem.

## Remaining cutover gates

1. Deploy and test the runtime freeze. Confirm it drained accepted mutations,
   including external file operations. Disable competing CD and automatic updates.
2. Freeze, retain the original volume and complete backup, and create the final
   standalone database snapshot. Run the final inventory/copy/verify above.
3. Configure destination S3 through supported settings/bootstrap, preserving all
   record IDs. Establish a dedicated fresh replica path. The tool does not enable
   S3 or seed Litestream.
4. Prove a strict empty-volume restore from that replica; compare the full logical
   database, not only table counts. Configuration changes must be explicitly
   accounted for when comparing with the original production snapshot.
5. Validate content, protected downloads, authentication and ordinary reads while
   destination writes remain disabled. Read-only support must cover destination
   startup settings and maintenance authentication.
6. Fence the old process, its replica publisher and deployment credentials before
   opening destination writes. A runtime freeze is not cross-host fencing.
7. Switch ONCE hostname, effective BASE_URL, TLS, DNS, policy and deployment checks
   while preserving ONCE application identity and volume. Retire the old v2 URL.
8. Retain recovery copies. After destination writes, the original snapshot is no
   longer a lossless rollback target.

The existing v2 migration drill proves synthetic recovery only. Production file
counts and bytes require running inventory on a private production snapshot.
Conditional object creation must also be rehearsed against the intended provider
with disposable synthetic objects before production execution.

Validation: `python3 -B tests/migrate_files.py` uses synthetic SQLite fixtures and
an in-memory object client. No live database, cloud resources or credentials are
used by the test suite.
