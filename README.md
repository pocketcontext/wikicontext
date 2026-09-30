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
Each publication can select a home page. `/#/` opens that page and the sidebar marks it Home; unset or cleared choices open the built-in welcome index. Historical views retain their home choice, and explicit page links stay stable. The Welcome link (`/#/welcome`) always opens a searchable, topic-grouped index of every unarchived page in the selected publication, with an A–Z view and onboarding links drawn only from available pages. New or uncategorized pages remain visible under Other knowledge. Welcome search filters page titles, slugs and summaries; the sidebar retains full-text page search. No company page catalog is bundled into the reader.
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

Install with `npx skills add pocketcontext/wikicontext --skill wikicontext`, or copy `skills/wikicontext/` to your agent's skill directory. It works outside this repository. Set `WIKICONTEXT_URL` and `WIKICONTEXT_USER_EMAIL`; use Google login or the optional `WIKICONTEXT_USER_PASSWORD` for an existing account.

```sh
python3 /path/to/wikicontext/scripts/wc.py login --google
python3 /path/to/wikicontext/scripts/wc.py check
python3 /path/to/wikicontext/scripts/wc.py ingest /path/to/source.md
python3 /path/to/wikicontext/scripts/wc.py search 'launch date'
python3 /path/to/wikicontext/scripts/wc.py lint
python3 /path/to/wikicontext/scripts/wc.py export-obsidian /path/to/vault
```

Over SSH, forward the CLI loopback port from your browser computer with `ssh -L 8765:127.0.0.1:8765 user@host`. The authentication cache contains only the application token with private permissions. `logout` removes that token cache; it does not revoke copies elsewhere or remove the separate private audio and extraction caches.

The `ingest` command uploads an immutable source and extracts passages; audio is normalized before upload by default. The agent then follows the skill to synthesize summaries/concepts, create citations/links, and publish a staging run. Uploading/extracting alone is not a completed knowledge-ingestion workflow. The server validates publication and rejects stale synthesis with 409. Use `wc.py stage-home RUN_ID --home SLUG --expected-revision N` (or `--clear-home`) to stage the home choice and capture its expected base. Publish using the returned run revision without home flags. Home-only runs are supported; concurrent home changes return 409 and require reassessment. Direct `publish --home`/`--clear-home` requires an explicit `--home-base` page ID or empty string. No LLM runs inside the server or Markdown exporter.

Supported extraction: UTF-8 text/Markdown and related text formats; text PDFs using local `pdftotext`; audio using `ffmpeg`, `ffprobe` and the configured Groq service. Audio ingestion authorizes transcription. By default the client stores mono Opus `.ogg` audio encoded from 16 kHz input at 16 kbps, then sends those same bytes to Groq. It checks duration and the 25 MB transcription limit before upload; large input recordings can fit after normalization. Local recordings remain untouched. Use `ingest PATH --audio-storage original` to upload the input bytes and transcribe a separate derivative. Normalization selects the first audio stream and discards video. Normalized files are privately cached for retry across failures and encoder upgrades. The stored Ogg embeds the input hash, conversion profile and converter version before transcription; private cache metadata and later rendition notes also retain the input filename and conversion settings. Exact-byte deduplication applies to the stored file; different encoder builds can produce different bytes. Set only this application's `WIKICONTEXT_GROQ_API_KEY` in the agent environment. Missing tools or invalid/oversize normalized audio stop before upload in the default audio mode. Scanned PDFs without text and provider errors stop extraction with resumable source storage. No OCR or background crawler is supplied.

The exporter writes `wiki/` and `raw/` under the destination. Numbered source footnotes, wiki-links, page metadata, index and publication log are deterministic. Exports pin one immutable publication; `--sequence N` selects history. An ownership manifest detects local edits/deletions, prevents overwriting unrelated files, and supports interrupted-export recovery. `.obsidian/` remains untouched. Avoid concurrent local editing during export; the exporter lock coordinates exporters, not external editors. Use a fresh destination for initial migration: existing authored wiki files are not silently adopted. Downloaded files cannot be revoked remotely.

See [data model](docs/data-model.md) and [skill workflows](skills/wikicontext/references/workflows.md) for synthesis, idempotency, queries, corrections and publication. Structural lint does not establish semantic correctness. Full-text search indexes published revision title, summary and body; it uses token matching rather than the former arbitrary substring matching. It does not provide vector search or generated answers. Raw SQL queries must explicitly distinguish draft revisions from the published manifest.

## SQL diagnostics

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

Use synthetic isolated databases only. From this repository, with the pinned server built and `ffmpeg`/`ffprobe` available for the audio ingestion tests:

```sh
python3 tests/integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/tracing.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/publication_review.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/home.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/auth.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/realtime_access.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/realtime_publication.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/oauth_integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/skill.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/knowledge_integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/search_integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/ingest_integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/export_integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/deploy.py --binary /absolute/path/to/pinned/pocketcontext
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

CI runs reader type checks, unit tests and the production browser suite before
image publication. Container smoke checks also verify the shell and bundled assets.

Regenerate the SQL reference only after reviewing intentional changes: `tests/skill.py --binary ... --write-schema`. Container CI additionally runs configuration, persistence, crash restore and graceful shutdown checks. Main-branch image publication is gated on application tests and native container checks; deployment additionally requires the configured `COLORS_PROFILE` environment. Native AMD64/ARM64 container checks passed in release CI. A real Google browser login and live Groq transcription remain unverified; see the release record.

## Existing wiki migration

The existing `wiki/` checkout has not been modified or migrated. Import originals through ordinary API ingestion, retrieve actual Git LFS audio rather than its pointer, and import authored pages as explicitly labelled legacy revisions with mapped evidence. Preserve slugs, original citations and legacy log text; do not claim imported legacy logs are server audit events. Compare a fresh generated vault before switching Obsidian. Never use direct SQLite writes or production data for migration tests. A bulk legacy importer is not supplied in this version.

## Infrastructure provenance

Authentication and portable OAuth client adapted from RaiseContext `44f8f10537388f9a934a2bc1800d3df6a046c580`; revision/concurrency and realtime test patterns from TaskContext `5bb214ef32fcffa9a42bb1de2d13cfd4052dc80f`; protected originals, complete backups and container/deployment patterns from AccountContext `2b78c0f38680381376b0ce485312ff659037a13f`. WikiContext's domain schema and publication/export model are independent. Server pin: `91d7ef14b02a476b2212aa80b365b6c024a19c15`.

## Request observability

The pinned server enables an authenticated, bounded in-memory trace buffer for `wikicontext`. Collection is client opt-in; ordinary commands produce no traces. See [optional skill tracing](skills/wikicontext/references/tracing.md) for separate ObserveContext login, private upload, SQL-text consent, delivery retries and measurement limits. No ObserveContext credentials are installed on this server.
