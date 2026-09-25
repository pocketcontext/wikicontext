# WikiContext deployment

Deployed on 25 September 2026 at https://wiki.pocketcontext.com through the existing ONCE host. The application starts empty; the prior Markdown wiki has not been migrated.

| Item | Verified value |
| --- | --- |
| Public source repository | https://github.com/pocketcontext/wikicontext |
| Released application source | `3269b646190809e6b19e985a1386787beea7813b` |
| PocketContext pin | `381f81042586afdaa6498b8c0e2a78229a55bdff` |
| Public image | `ghcr.io/pocketcontext/wikicontext:latest` |
| Multiarchitecture image digest | `sha256:73084165c8631653c148e47d1ea0da773fb6c704306fe6efaaafa55fc72816e0` |
| ARM64 platform manifest | `sha256:b6dfd1cbf798cc78200e552b6f4233d6cd0e92c2cd4b57a044068134d54e0589` |
| AMD64 platform manifest | `sha256:21fdd2b03546e0696c40c2ac9e82afa6edf811f7b53d1679963bf7b81c383bf2` |
| Release CI | [36191718062](https://github.com/pocketcontext/wikicontext/actions/runs/36191718062) — passed |
| Source-pinned image archives | [Release](https://github.com/pocketcontext/wikicontext/releases/tag/image-3269b646190809e6b19e985a1386787beea7813b) |
| Production resources | ARM64, one CPU, 512 MiB, persistent `/storage`, one writer, automatic updates disabled |
| R2 backup | Dedicated `wikicontext-backup` EU bucket; prefix `once-pocketcontext/wikicontext` |

## Release and live checks

All application validation commands passed on AMD64 and ARM64 in CI. Each architecture passed container configuration, startup/persistence, populated crash restore and graceful-stop recovery before publication. Anonymous registry requests verified the multiarchitecture manifest, both platform manifests, configurations and all layers; the image can be pulled without credentials. Package visibility was verified independently of repository visibility.

Scaffold build/dry-run passed. A targeted DNS plan created only the proxied WikiContext A record at the existing host; authenticated record and public DNS checks passed. No compute/SMTP convergence or sibling replacement was performed.

HTTPS health, maintenance login, the existing default `users` collection, OAuth-only signup rule, dedicated Google provider/client, anonymous schema/SQL rejection and initially empty knowledge collections passed. The server environment matches the configured Workspace domain and dedicated OAuth/R2 settings. No production test user or knowledge record was created. One writer, resource limits, persistent storage, image revision/architecture and disabled automatic updates were checked after the controlled update. Sibling container IDs, running state and deployment keys were preserved; public health checks passed for the sibling applications and demos.

Google Workspace JIT is configured for `pocketcontext.com`: verified first login creates an ordinary shared-workspace identity. The client is separate from sibling clients; a Google invalid-code credential probe returned `invalid_grant`. This does not prove the provider audience, redirect configuration or a successful human login. **A real Google Workspace browser sign-in remains unverified.** Live Groq transcription was not exercised by deployment.

## Backups and recovery

Dedicated R2 write/read/list/delete probes passed and the temporary probe was removed. Nonempty database replicas, a complete database/original archive and its latest-complete pointer were verified.

An isolated read-only recovery drill fetched the complete production snapshot, verified the database/original manifest, then started a disposable loopback-only server with replication disabled. An ordinary synthetic identity created only in that disposable database authenticated and queried the allowed SQL schema; auth-table access was rejected. Complete restore plus hash verification took **1.48 seconds** for the initial empty knowledge base. This is not a populated-production recovery benchmark; populated-original recovery is covered by the native container gates. The drill container and temporary restored storage were removed. No second writer used the production replica.

Complete snapshots run shortly after startup, hourly by default, and on graceful shutdown. Actual recovery-point age includes upload time and failures; monitor the latest successful complete pointer. Database replication alone does not recover newer missing originals. Follow [recovery instructions](docs/deployment.md) and preserve a single production writer. A generated Obsidian vault is not a complete application backup.

## Deployment control

A dedicated restricted key invokes `/usr/local/sbin/deploy-wikicontext` with no command arguments. Its root-owned wrapper locks, pulls, gracefully stops the exact current writer, verifies clean exit, and updates only WikiContext with automatic updates disabled. A controlled update from the initial pinned image to the verified `latest` image passed. Sibling keys remain intact. No temporary bootstrap key or payload was used.

The GitHub environment `once-pocketcontext` holds the dedicated SSH secret and pinned host identity. `COLORS_PROFILE=once-pocketcontext` enables later gated CI deployments. Registry credentials supplied by CI exist only in a private temporary Docker configuration; the tested image also supports anonymous pulls.

Operator, Google and R2 credentials and the dedicated key reference remain only in the scaffold's ignored mode-0600 `.envrc.private` under `COLORS_PAR_APP_WIKICONTEXT_*`. Never print full ONCE labels, environments or private backup contents.

## Rollback

Acquire `/run/lock/deploy-wikicontext.lock`, stop the sole writer gracefully, and preserve its volume. Use a tested earlier image only after checking schema compatibility. For incompatible schema changes, restore a selected complete backup into isolated storage, verify it, and choose a deliberate replica strategy before switching traffic; do not connect a restored writer to the active production replica. The normal fixed-target wrapper is an update command, not a general rollback interface. Repeat auth, original-byte, health, image and sibling checks after recovery.
