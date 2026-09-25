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
protect them as credentials. Nothing automatically deletes old backups.

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
access before switching service. Keep original immutable files until a deliberate
retention policy is implemented. A generated Obsidian vault is not a backup.

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

## Attribution

Container, Litestream, immutable-file backup, smoke/MinIO fixture, bootstrap and
single-writer deployment patterns were adapted from sibling AccountContext.
WikiContext changes the protected attachment collection to `sources`, tests shared
user visibility, and restricts operational deployment to its approved fixed target.
