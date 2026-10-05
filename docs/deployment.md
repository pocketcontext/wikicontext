# Deployment procedures

WikiContext is deployed at `wiki.pocketcontext.com`, using the public image
`ghcr.io/pocketcontext/wikicontext`. See [the release record](../DEPLOYMENT.md) for
source/digests, completed checks and remaining browser verification.
Fixed-target bootstrap, installer and update wrappers are enabled for that hostname.
CI builds and exercises containers natively on AMD64 and ARM64. Publication on main
requires both architecture checks (configuration, smoke and complete restore) and
the full application test suite on both architectures. Release archive access follows
repository visibility; registry package visibility is configured independently.
CD runs only when `COLORS_PROFILE` names the configured GitHub deployment environment.

The container exposes HTTP port 80 and `/up`; mount persistent `/storage`.
The root URL serves the bundled read-only wiki reader. Its static assets are built
in a separate Node stage; the runtime remains the existing Go/Python image. Keep
the same Google OAuth redirect at the approved origin's `/api/oauth2-redirect`.
No new hostname, OAuth client or cloud resources are required for the reader.
It builds the commit in `POCKETCONTEXT_VERSION` with CGO. The pinned Go/base images
and Litestream checksums are inherited from AccountContext. Container CI must build
and verify them before any release. Run:

```sh
python3 docker/smoke.py config --image wikicontext:ci
python3 docker/smoke.py smoke --image wikicontext:ci
python3 docker/smoke.py restore --image wikicontext:ci
```

The restore check uses synthetic original attachments and an isolated MinIO fixture.
It kills the first writer, destroys its volume, restores the database and original
bytes, then checks that a graceful stop saves a late upload. Never run a restore
writer against the production replica beside the live instance.

## Configuration

Set `BASE_URL` to the approved HTTPS origin. Set paired
`WIKICONTEXT_SUPERUSER_EMAIL`/`WIKICONTEXT_SUPERUSER_PASSWORD` for maintenance bootstrap;
ordinary operations use default `users`. Enable a separate Internal Google Web client
with `WIKICONTEXT_GOOGLE_CLIENT_ID`, `WIKICONTEXT_GOOGLE_CLIENT_SECRET` and
`WIKICONTEXT_GOOGLE_WORKSPACE_DOMAIN`. Configure both the CLI loopback redirect
`http://127.0.0.1:8765/callback` and the approved origin's `/api/oauth2-redirect`.
Every admitted, enabled user can read and edit shared wiki content. Google JIT must
verify trusted claims; public password signup stays blocked.

Use a dedicated private R2 bucket `wikicontext-backup` and prefix
`once-pocketcontext/wikicontext`. Required settings are `LITESTREAM_BUCKET`,
`LITESTREAM_PATH`, `LITESTREAM_ACCESS_KEY_ID`, `LITESTREAM_SECRET_ACCESS_KEY`, with
`LITESTREAM_REGION` and `LITESTREAM_ENDPOINT` for R2. Never reuse sibling replicas.
Store deployment credentials under `COLORS_PAR_APP_WIKICONTEXT_*` in the private
scaffold `.envrc.private`, preserving existing entries. Groq transcription credentials belong to
the ingestion agent environment, not container deployment labels.

The image enables `WIKICONTEXT_RATE_LIMITS=true`. An explicitly isolated development
instance can set `LITESTREAM_DISABLED=true`. Production must use replication.

## Complete recovery

Litestream protects the database; complete backups additionally contain every
immutable source original referenced by an online SQLite snapshot. `backup.py`
checks recorded source SHA-256 values, packages database and originals together,
and publishes the latest pointer only after successful upload. Archives live under
`<LITESTREAM_PATH>/full-backups`. Backups include identities and private settings;
protect them as credentials. Every archive is independent: removing an older
archive does not remove evidence from a retained archive.

The container enables `WIKICONTEXT_BACKUP_PRUNE=true`. After a successful archive
upload and latest-pointer publication, retention keeps all snapshots from the
last 48 hours, the newest per UTC day through 30 days, and the newest per UTC
month through 365 days. It always preserves the latest pointer's target and the
three newest archives, regardless of age. Set the flag to `false` to suspend
automatic pruning; running the script outside the image defaults to disabled.
Retention bounds duplicate copies, not the size of the growing evidence corpus.

Pruning only recognizes timestamp/UUID archive names under the dedicated
`full-backups/` prefix. It leaves unknown objects, `latest.json`, and Litestream
replica objects untouched. Missing, invalid or dangling pointers abort cleanup.
Upload and pruning share the local volume lock; this assumes the required single
writer and does not coordinate independent hosts. Cleanup failures are reported
separately and do not stop the application or invalidate a successful backup.

Before initial cleanup, inspect the plan and restore a retained archive into
isolated storage. With the existing R2 environment available:

```sh
python3 /usr/local/bin/wikicontext-backup.py prune --dry-run
# Explicit cleanup using the same policy:
python3 /usr/local/bin/wikicontext-backup.py prune
# Choose an exact archive key from the inventory; use an empty destination:
WIKICONTEXT_DATA_DIR=/private/isolated-recovery \
  python3 /usr/local/bin/wikicontext-backup.py restore --archive "$ARCHIVE_KEY"
```

Dry-run output includes retained/deletable counts and bytes plus deletion
candidates. Keep this operational inventory private. Do not apply age-based R2
expiration to the complete-backup prefix: it cannot preserve the last good
archive through an extended backup outage. Historical archives carry internal
database/original checksums; only the latest pointer additionally records the
outer archive checksum. Do not run a recovered server against the live replica.

A complete backup runs shortly after startup, every
`WIKICONTEXT_BACKUP_INTERVAL` seconds (default 3600, allowed 1–3600), and after a
successful graceful shutdown. The complete-backup interval bounds original-file
recovery; frequent database replication does not reduce that interval. Monitor
backup failures and last successful archive time before treating the service as
production-ready.

On an empty volume the entrypoint restores the latest verified complete archive
before considering database-only recovery, then verifies all original references
before starting. Existing volumes are never replaced automatically. Database-only
recovery fails startup if referenced originals are missing. Recover into a fresh
isolated directory/volume; verify hashes, ordinary-user queries and protected file
access before switching service. Backup retention never deletes live immutable
originals or records. A generated Obsidian vault is not a backup.

For a local, synthetic drill without Docker:

```sh
python3 tests/backup.py
python3 tests/backup_integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/bootstrap.py
python3 tests/deploy_workflow.py
```

## Updates

Disable ONCE automatic updates. Install the
root-owned fixed-target wrapper with `deploy/install.py`, preserving sibling SSH
keys. The wrapper locks, verifies the exact existing application/image, pulls,
gracefully stops the sole writer, and updates that target. It refuses forced-stop
or ambiguous-container results and avoids starting a second writer during recovery.
Reinstall it after scaffold convergence rewrites authorized keys. Do not use an
ordinary overlapping ONCE update. The bootstrap takes only a root-owned, mode-0600
private payload and bounded registry credentials; remove its temporary key after
initial deployment.

## Runtime migration freeze

The application pins PocketContext `94d4549b4cffe7f2754e65467efdd9be16450a25`,
which provides the runtime maintenance API. Deploy an image with this pin before
attempting a production freeze. Older images do not expose the API.

An operator with an existing valid superuser token reads
`GET /api/context/maintenance`, then sends `PUT /api/context/maintenance` with
`{"readOnly":true,"expectedGeneration":N}`, using the returned generation.
Wait for `state: "read_only"` before taking the final migration snapshot. A draining
or failed transition is not a completed freeze. Ordinary users cannot change this
state, and superusers do not bypass the content freeze. Keep the operator token
private and available for the explicit unfreeze operation.

Existing authenticated sessions retain SQL queries, searches and protected file
reads. Token refresh and protected file-token requests remain available. Password
login, OAuth login/linking, signup, uploads, publication, batch writes and other
mutations are unavailable while frozen. Complete interactive login before the
freeze. This is a migration maintenance window, not permanent public read-only
hosting.

The server owns `pb_data/maintenance.json`; retain it with the active volume. On a
frozen restart, the container requires the existing database and skips archive
restore, replica restore and superuser upsert. The bootstrap hook preserves stored
settings and OAuth configuration instead of applying changed environment values.
Invalid maintenance state stops startup. Do not remove or edit the marker to
unfreeze the process: send the same PUT with `readOnly:false` and the latest
generation after confirming this host remains the authorized writer.

This flag freezes application database and HTTP mutations, not independent backup
or Litestream processes. Those publishers keep running until explicitly fenced.
Before promoting a recovered host, stop the old replica publisher and deployment
automation, and independently verify the final database and originals. Never
restart a stale source after destination writes have begun. The marker is separate
from `data.db` and is not transferred by database-only Litestream recovery; enforce
destination maintenance before making the recovered application reachable.

A cold Litestream restore supplies only `data.db`. Frozen startup also requires
PocketBase's compatible `auxiliary.db`; it cannot initialize a missing auxiliary
database while frozen. Copy that database consistently from the stopped source,
or complete a controlled bootstrap on an isolated destination before installing
the freeze. Do not expose that destination or attach a competing replica publisher
during preparation. A same-volume frozen container restart already retains both
databases and is a different operation from cold replica recovery.

Validate with synthetic isolated data:

```sh
python3 tests/maintenance_entrypoint.py
python3 tests/maintenance.py --binary /absolute/path/to/maintenance-capable/pocketcontext
```

## Attribution

Container, Litestream, immutable-file backup, smoke/MinIO fixture, bootstrap and
single-writer deployment patterns were adapted from sibling AccountContext.
WikiContext changes the protected attachment collection to `sources`, tests shared
user visibility, and restricts operational deployment to its approved fixed target.
