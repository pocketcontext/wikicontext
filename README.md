# WikiContext

An agent-maintained knowledge base on PocketContext. Sources, extracted passages, versioned pages, citations, links and publication history live in WikiContext. The browser reader renders published pages and updates when agents publish. Obsidian consumes a reproducible Markdown export. Ingestion and agent questions use the portable skill and authenticated APIs.

All admitted Workspace users share read/write access. PocketBase's existing default `users` collection supplies identities, with verified Workspace Google JIT and public signup blocked. New logins gain shared content access, never account administration. Operators disable accounts to revoke application sessions; Google suspension alone does not revoke an existing session. Re-enabling requires fresh login. Seven-day tokens renew during active Google client use.

## Run locally

Build the commit in `POCKETCONTEXT_VERSION` with its specified Go version, CGO and a C compiler:

```sh
# From a PocketContext checkout at the pinned revision:
make build
# From this application directory:
/path/to/pinned/pocketcontext serve --dir ./pb_data --http 127.0.0.1:8090
```

The pinned build includes `sqlite_math_functions,sqlite_percentile,sqlite_fts5`.
Authenticated SQL supports `json_each`/`json_tree` and median/percentile aggregates.
Published-page search uses the authenticated FTS5 endpoint with immutable
publication scopes and generation-checked pagination. See the
[search contract and maintenance guide](docs/fts-adoption.md).

Keep data outside Git. Provision users through operator maintenance, or configure a separate Google Web client with `WIKICONTEXT_GOOGLE_CLIENT_ID`, `WIKICONTEXT_GOOGLE_CLIENT_SECRET` and `WIKICONTEXT_GOOGLE_WORKSPACE_DOMAIN`. Register `http://127.0.0.1:8765/callback` and the approved origin's `/api/oauth2-redirect`. Use ordinary user credentials for knowledge operations. Production runs at https://wiki.pocketcontext.com. See [release verification](DEPLOYMENT.md) and [deployment procedures](docs/deployment.md).

## Browser reader

Open the application origin and sign in with your Workspace Google identity.
Existing password accounts can use the secondary password form. The reader is
read-only; agents continue to ingest, synthesize and publish through the skill.
Search opens ranked published-page results with plain excerpts and Load more.
The sidebar collection selector browses Pages, Sources and Passages. Source/passage text filtering searches all shared evidence, including evidence not yet cited in a publication, with paginated URL state. Permanent `/#/sources/<id>` and `/#/passages/<id>` links support authenticated evidence navigation and protected original downloads; source pages link to their passages. Copy record/search links exclude temporary file tokens. Page controls copy live or publication-pinned historical links. The sidebar remains available for browsing. `/` or Ctrl/Cmd+K focuses search; query
and publication are preserved in navigation. Wiki links, backlinks, an outline and
source citations support navigation. A citation opens its original passage and
offers an authenticated original-file download.

The live view adopts complete publications and rechecks after reconnect or tab
focus. Selecting a historical publication pins the view until you return to live.
Each publication can select a home page. `/#/` opens that page and the sidebar marks it Home; unset or cleared choices open the built-in welcome index. Historical views retain their home choice, and explicit page links stay stable. The Welcome link (`/#/welcome`) always opens a searchable, topic-grouped index of every unarchived page in the selected publication, with an A–Z view and onboarding links drawn only from available pages. New or uncategorized pages remain visible under Other knowledge. Welcome and sidebar search use the same full-text search across published titles, summaries and contents. The sidebar starts with topic navigation; expand All pages for the complete catalog. The welcome directory supports topic browsing and an A–Z view, while additional onboarding guides remain under All onboarding guides. No company page catalog is bundled into the reader.
Unpublished revisions are never selected. Markdown supports tables, code, wiki
links with aliases/heading anchors, citation markers and callouts. Raw HTML and
embedded images are disabled. Obsidian plugins, block embeds, editing and two-way
vault synchronization are outside this reader's scope.

Frontend source is in `ui/`: React, TypeScript and Vite, with bundled Markdown
rendering and the PocketBase SDK. Content reads use authenticated SQL; the SDK
handles ordinary user authentication, protected file tokens and SSE notifications.
The official PocketBase SDK LocalAuthStore keeps the application token in local
storage under `wikicontext.reader.auth`, shared across tabs and browser restarts.
Logout synchronizes across tabs and clears reader state and subscriptions; account
changes discard pending responses and private views. Tokens remain accessible to
same-origin JavaScript. Active sessions renew at most every five minutes. Legacy
per-tab credentials are discarded, so the first visit after upgrading requires login. No provider secret is shipped to the browser.

With Node.js 24 and pnpm 10.33.2:

```sh
cd ui
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test
pnpm build
```

Run the pinned server from the application directory, then open its root URL.
The application hooks serve `ui/dist` with a restrictive Content Security Policy.
For frontend development, `pnpm dev` proxies `/api` to `127.0.0.1:8090`.
The production container builds and serves static assets without a Node runtime.
Do not commit `ui/dist` or browser test output.

## Portable skill

The standalone launcher `skills/wikicontext/wikicontext` requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). Add its directory to `PATH` to use the commands below. Its first run installs the client from a pinned Git revision. For development and validation, install the current package in a virtual environment with `python3 -m pip install .`. Release the tested package commit first, then update the launcher to that full commit and verify the copied launcher through uv. The package pins its ObserveContext instrumentation dependency separately.


Install with `npx skills add pocketcontext/wikicontext --skill wikicontext`, or copy `skills/wikicontext/` to your agent's skill directory. It works outside this repository. Set `WIKICONTEXT_URL` and `WIKICONTEXT_USER_EMAIL`; use Google login or the optional `WIKICONTEXT_USER_PASSWORD` for an existing account.

```sh
wikicontext login --google
wikicontext check
wikicontext ingest /path/to/source.md
wikicontext search 'launch date'
wikicontext lint
wikicontext export-obsidian /path/to/vault
```

Over SSH, forward the CLI loopback port from your browser computer with `ssh -L 8765:127.0.0.1:8765 user@host`. The authentication cache contains only the application token with private permissions. `logout` removes that token cache; it does not revoke copies elsewhere or remove the separate private audio and extraction caches.

The `ingest` command uploads an immutable source and extracts passages; audio is normalized before upload by default. The agent then follows the skill to synthesize summaries/concepts, create citations/links, and publish a staging run. Uploading/extracting alone is not a completed knowledge-ingestion workflow. The server validates publication and rejects stale synthesis with 409. Use `wikicontext stage-home RUN_ID --home SLUG --expected-revision N` (or `--clear-home`) to stage the home choice and capture its expected base. Publish using the returned run revision without home flags. Home-only runs are supported; concurrent home changes return 409 and require reassessment. Direct `publish --home`/`--clear-home` requires an explicit `--home-base` page ID or empty string. No LLM runs inside the server or Markdown exporter.

Supported extraction: reviewed PNG/JPEG/WebP images (see below); UTF-8 text/Markdown and related text formats; text PDFs using local `pdftotext`; audio using `ffmpeg`, `ffprobe` and the configured Groq service. Audio ingestion authorizes transcription. By default the client stores mono Opus `.ogg` audio encoded from 16 kHz input at 16 kbps, then sends those same bytes to Groq. It checks duration and the 25 MB transcription limit before upload; large input recordings can fit after normalization. Local recordings remain untouched. Use `ingest PATH --audio-storage original` to upload the input bytes and transcribe a separate derivative. Normalization selects the first audio stream and discards video. Normalized files are privately cached for retry across failures and encoder upgrades. The stored Ogg embeds the input hash, conversion profile and converter version before transcription; private cache metadata and later rendition notes also retain the input filename and conversion settings. Exact-byte deduplication applies to the stored file; different encoder builds can produce different bytes. Set only this application's `WIKICONTEXT_GROQ_API_KEY` in the agent environment. Missing tools or invalid/oversize normalized audio stop before upload in the default audio mode. Scanned PDFs without text and provider errors stop extraction with resumable source storage. No OCR or background crawler is supplied.

Pillow is installed automatically with the client package for reviewed image ingestion. Run `wikicontext ingest IMAGE --image-review REVIEW.json` after viewing the original and preparing reviewed evidence. The client verifies and decodes static PNG/JPEG/WebP images, requires matching extensions, limits dimensions to 16,384 pixels per axis and 50 million total pixels, and preserves the exact original bytes. Review JSON must match the original SHA-256 and encoded dimensions before upload. It separates transcription, visual description and captions into region-addressable passages. A changed review requires a new `--version`; identical reviewed input resumes interrupted writes. Related audio source IDs and screenshot sequence are recorded in rendition notes, without replacing the audio. Image ingestion makes no external OCR or vision-service request. See the [review format](skills/wikicontext/references/examples.md#reviewed-image-evidence) and [image workflow](skills/wikicontext/references/workflows.md#images). The reader previews PNG/JPEG/WebP originals on source and passage pages and in citation dialogs, with an enlarged view, actual-size scrolling, retry controls and protected original downloads. Previews clear when the source or signed-in identity changes. Other image formats remain download-only; previews do not add extraction or OCR.

The exporter writes `wiki/` and `raw/` under the destination. Numbered source footnotes, wiki-links, page metadata, index and publication log are deterministic. Exports pin one immutable publication; `--sequence N` selects history. An ownership manifest detects local edits/deletions, prevents overwriting unrelated files, and supports interrupted-export recovery. `.obsidian/` remains untouched. Avoid concurrent local editing during export; the exporter lock coordinates exporters, not external editors. Use a fresh destination for initial migration: existing authored wiki files are not silently adopted. Downloaded files cannot be revoked remotely.

See [data model](docs/data-model.md) and [skill workflows](skills/wikicontext/references/workflows.md) for synthesis, idempotency, queries, corrections and publication. Structural lint does not establish semantic correctness. Full-text search indexes published revision title, summary and body; it uses token matching rather than the former arbitrary substring matching. It does not provide vector search or generated answers. Raw SQL queries must explicitly distinguish draft revisions from the published manifest.

## SQL diagnostics

For an optional Python CLI experiment that ranks a full published snapshot using
OpenAI's metered API, see [the semantic search proof of concept](tools/semantic_search_poc/README.md).
Preparation is read-only; model searches upload the selected corpus to OpenAI.
This experiment does not replace the application's FTS search or browser UI.

For published-page body sizes, pin a publication sequence and expand its manifest:

```sql
SELECT count(*) AS pages,
       median(length(r.body)) AS median_body_characters,
       percentile_cont(length(r.body), 0.95) AS p95_body_characters
FROM publications AS pub
JOIN json_each(pub.manifest) AS selected
JOIN page_revisions AS r ON r.id = selected.value AND r.page = selected.key
WHERE pub.sequence = 1 AND r.archived = false;
```

Replace `1` with the selected publication sequence. This excludes drafts and
archived pages and returns one aggregate row. The statistics describe character
counts, not query latency or memory use; an empty publication returns NULL sizes.
`percentile_cont` takes a fraction from 0 to 1; `percentile` takes 0 to 100.

## Validation

Use synthetic isolated databases only. From this repository, with the pinned server built and `ffmpeg`/`ffprobe` available for audio tests and Pillow installed for image tests:

```sh
python3 tests/launcher.py
python3 tests/integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/tracing.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/publication_review.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/home.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/auth.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/realtime_access.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/realtime_publication.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/oauth_integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/skill.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/skill.py --binary /absolute/path/to/pinned/pocketcontext --trace
python3 tests/knowledge_integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/search_integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/ingest_integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/export_integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/deploy.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/maintenance.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/maintenance_entrypoint.py
python3 tests/backup_integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/oauth.py
python3 tests/client.py
python3 tests/knowledge.py
python3 tests/ingest.py
python3 tests/exporter.py
python3 tests/backup.py
python3 tests/bootstrap.py
python3 tests/deploy_workflow.py
```

After building the reader, install Chromium once and exercise the production
assets against a synthetic isolated database:

```sh
(cd ui && pnpm exec playwright install chromium)
python3 tests/ui_browser.py --binary /absolute/path/to/pinned/pocketcontext
```

The LocalAuthStore migration passed the backend validation commands above,
reader typecheck/build, 32 unit tests and four actual-server browser scenarios.
The added scenario covers independently opened tabs, reload, cross-tab account
changes/logout, restored deep links and rejection of legacy per-tab credentials.
Tests also cover realtime publications/reconnect, revocation, idle-token expiry
and late refresh.

The 30 September 2026 navigation change passed every validation command above
against the unchanged 91d7ef1 pin, reader typecheck, 32 unit tests, production
build and both actual-server browser scenarios (including evidence permalinks,
reload, collection search and keyboard navigation).

The Welcome and evidence layout update passed all 23 backend validation commands
against the unchanged 91d7ef1 pin, reader typecheck, 57 unit tests, production
build and all eight isolated browser scenarios. Browser checks include full-text
Welcome search, topic navigation, responsive evidence layout, protected image
enlargement, historical views and session isolation.

CI runs reader type checks, unit tests and the production browser suite before
image publication. Container smoke checks also verify the shell and bundled assets.

Regenerate the SQL reference only after reviewing intentional changes: `tests/skill.py --binary ... --write-schema`. Container CI additionally runs configuration, persistence, crash restore and graceful shutdown checks. Main-branch image publication is gated on application tests and native container checks; deployment additionally requires the configured `COLORS_PROFILE` environment. Native AMD64/ARM64 container checks passed in release CI. A real Google browser login and live Groq transcription remain unverified; see the release record.

## Existing wiki migration

The runtime migration freeze and its server-pin release prerequisite are described
in [deployment procedures](docs/deployment.md#runtime-migration-freeze).

The existing `wiki/` checkout has not been modified or migrated. Import originals through ordinary API ingestion, retrieve actual Git LFS audio rather than its pointer, and import authored pages as explicitly labelled legacy revisions with mapped evidence. Preserve slugs, original citations and legacy log text; do not claim imported legacy logs are server audit events. Compare a fresh generated vault before switching Obsidian. Never use direct SQLite writes or production data for migration tests. A bulk legacy importer is not supplied in this version.

## Infrastructure provenance

Authentication and portable OAuth client adapted from RaiseContext `44f8f10537388f9a934a2bc1800d3df6a046c580`; revision/concurrency and realtime test patterns from TaskContext `5bb214ef32fcffa9a42bb1de2d13cfd4052dc80f`; protected originals, complete backups and container/deployment patterns from AccountContext `2b78c0f38680381376b0ce485312ff659037a13f`. WikiContext's domain schema and publication/export model are independent. Server pin: `976ddf71a4734530adefe4a56633658a0894b449`.

## Request observability

The pinned server enables an authenticated, bounded in-memory trace buffer for `wikicontext`. Collection is client opt-in; ordinary commands produce no traces. See [optional skill tracing](skills/wikicontext/references/tracing.md) for separate ObserveContext login, private upload, SQL-text consent, delivery retries and measurement limits. No ObserveContext credentials are installed on this server.

## Object storage deployment

The application supports private PocketBase S3 file storage.
Set all of `WIKICONTEXT_S3_BUCKET`, `WIKICONTEXT_S3_ENDPOINT`,
`WIKICONTEXT_S3_REGION`, `WIKICONTEXT_S3_ACCESS_KEY_ID` and
`WIKICONTEXT_S3_SECRET_ACCESS_KEY`. Optional `WIKICONTEXT_S3_FORCE_PATH_STYLE`
is `true` by default. Partial settings stop startup without logging values.
Use a dedicated private bucket with no public downloads or lifecycle deletion.
Uploads and protected downloads still use PocketBase's ordinary authenticated API;
original checksums are streamed from its configured filesystem backend.
During a frozen restart, these values must match the stored backend and
credentials exactly; configuration changes are refused until an explicit thaw.

With this contract enabled, startup preserves a healthy local database or restores
an absent database from Litestream. Before HTTP starts, the supervised child calls
Litestream's private mode-0600 IPC socket with `sync -wait`, forcing database
initialization and a completed initial remote sync. Startup intentionally requires
a reachable replica; missing IPC or failed synchronization refuses serving.
Google-only fresh deployments bootstrap the database with migrations before this
handshake. This closes Litestream 0.5.17's early-stop gap: before its first monitor
tick, an uninitialized database otherwise skips final replication on shutdown. It never restores the legacy complete archive,
and no archive scheduler runs. Before opening the server, it streams every original
referenced by SQLite from S3 and verifies its recorded SHA-256. Missing, corrupt or
inaccessible evidence refuses startup. This costs a full evidence read on restart;
measure duration and allow sufficient ONCE startup time. Other PocketBase file
fields use the same storage backend; the integrity gate specifically covers sources.

Setting S3 does not migrate existing local files. Use the verified file-copy
procedure in [the migration runbook](tools/MIGRATION.md) before enabling remote
storage on an existing dataset. Local-storage deployments retain complete backup behavior. Do not
remove S3 configuration from a remote deployment or run legacy archive commands
against it. Litestream and file storage must use separate buckets and credentials.
Keep object retention at least as long as database recovery history. SQLite and S3
have no shared transaction: failed uploads can leave unreferenced objects, which
must not be automatically deleted based on a potentially stale restored database.

Exactly one application writer and replica publisher may operate per replica path.
For handover, stop the source cleanly, prevent its restart, restore into a separate
recovery location and compare the recovered committed database state with the
stopped source before starting the destination. Litestream 0.5.17 can exit zero
when its replica endpoint is unavailable; a clean process exit alone does not
prove final remote synchronization. Preserve the source volume until the recovered
state and all original-file hashes are verified. An unplanned host loss
can lose SQLite commits not yet replicated, even when uploaded objects survived.
No automatic cross-host fencing or zero-loss crash guarantee is provided.

For a disposable MinIO bucket only, install the package and `boto3`, set the S3
variables above, then run `python3 tests/object_storage_integration.py --binary
/absolute/path/to/pinned/pocketcontext --synthetic-bucket EXACT_TEST_BUCKET` on
one line. The test uploads synthetic evidence, proves protected downloads and
remote hashing, restores a database with no local files, then deliberately corrupts
and deletes its own object to prove verification fails closed.

## Isolated experiment CD (separate branch)

`.github/workflows/experiment.yml` runs on pushes to exactly
`experiment/object-storage`, using GitHub environment `once-v2`. That worktree
restricts its workflows to its own branch. Main retains the production image and
deployment workflow, with both legacy and object-storage recovery release gates.
The reusable test workflow keeps the same branch guard. Publication gates on the
complete reusable backend/reader suite, native ARM64 image checks, legacy recovery,
and `docker/object_storage_smoke.py` for real S3/Litestream fresh-volume recovery.
It publishes to the separate `ghcr.io/pocketcontext/wikicontext-v2` package
using unique `experiment-SHA-RUN-ATTEMPT` tags plus this separate package’s `latest`. The whole workflow is serialized, including tag
publication and deployment. ONCE policy tracks the separate package’s latest tag and resolves its
immutable digest before stopping; initial provisioning can pin a validated digest.

Environment `once-v2` must contain `SSH_PRIVATE_KEY`, `SERVER_IP`, `SERVER_USER=deploy`
and pinned `SSH_KNOWN_HOSTS`. The key must authorize only the experimental host's
forced command. No remote command or registry credentials are sent. The new
package must be made publicly pullable, or an operator must separately configure
root Docker registry authentication. Verification requires `/up` and the image's
non-secret `X-WikiContext-Revision` header to match the workflow commit.
The experimental worktree removes inherited production publication/deployment
jobs. Its deployment key must be retired before promoting that host to production;
production receives a separate main-only deployment environment and key.

For the standalone recovery test, set disposable MinIO S3 and Litestream settings
and run `python3 tests/object_storage_recovery.py --binary PINNED_SERVER
--litestream LITESTREAM_BINARY --synthetic-files-bucket TEST_FILES
--synthetic-replica-bucket TEST_REPLICA` on one line. For the actual image gate,
run `python3 docker/object_storage_smoke.py --image TEST_IMAGE --minio-image
LOCAL_MINIO_FIXTURE` on one line. Both use synthetic records and isolated replicas.

### Prepared live experiment verification

`tools/verify_experiment.py` is restricted to `https://wiki-v2.pocketcontext.com`
and the `wikicontext-v2-files` / `wikicontext-v2-replica` buckets. With experiment
credentials in the process environment and `boto3` installed, an explicitly
approved live check is:

```sh
python3 tools/verify_experiment.py --api-and-r2 --manifest /tmp/wiki-v2-synthetic-manifest.json
```

This creates a disposable default-users account with maintenance credentials,
then uploads one synthetic original as that ordinary user. It verifies the server
hash, protected download, anonymous denial and exact remote bytes. It disables the
disposable account in a finalizer. Immutable synthetic source evidence is retained.
Only check outcomes are printed; synthetic object metadata goes into a mode-0600
manifest, never credentials. Replica-object presence is checked separately and is
not proof that the latest write replicated.

To verify no local original remains, use the same script and synthetic manifest
inside the experimental container or against its mounted data directory:

```sh
python3 verify_experiment.py --check-local-storage /storage/pb_data --manifest /tmp/wiki-v2-synthetic-manifest.json
```

The script and manifest can be copied into the experimental container's `/tmp`
for this check and removed afterward. Do not print container environment or ONCE
labels when selecting the container. No live check is performed by preparing or
running `--help` on this script.

A migration gate must additionally stop the source and compare its database with
a fresh replica restore before destination activation:

```sh
python3 tests/object_storage_recovery.py --verify-source /stopped/data.db --verify-restored /restored/data.db
```

The comparator checks full integrity and logical schema/table/row contents without
printing source data. Keep the stopped source intact if comparison fails.

The actual-image S3 drill uses a one-hour remote sync interval and performs API
writes after the initial handshake. It strictly restores the replica into a
separate volume, compares every logical database record with the stopped source,
and only then destroys the source volume and starts the recovered writer. It also
checks missing-IPC startup refusal and fresh Google-only database initialization.
