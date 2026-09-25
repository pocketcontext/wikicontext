# WikiContext

An agent-maintained knowledge base on PocketContext. Sources, extracted passages, versioned pages, citations, links and publication history live in WikiContext. Obsidian consumes a reproducible Markdown export. Ingestion and questions always use the portable skill and authenticated APIs. There is no application frontend.

All admitted Workspace users share read/write access. PocketBase's existing default `users` collection supplies identities, with verified Workspace Google JIT and public signup blocked. New logins gain shared content access, never account administration. Operators disable accounts to revoke application sessions; Google suspension alone does not revoke an existing session. Re-enabling requires fresh login. Seven-day tokens renew during active Google client use.

## Run locally

Build the commit in `POCKETCONTEXT_VERSION` with its specified Go version, CGO and a C compiler:

```sh
# From a PocketContext checkout at the pinned revision:
make build
# From this application directory:
/path/to/pinned/pocketcontext serve --dir ./pb_data --http 127.0.0.1:8090
```

Keep data outside Git. Provision users through operator maintenance, or configure a separate Google Web client with `WIKICONTEXT_GOOGLE_CLIENT_ID`, `WIKICONTEXT_GOOGLE_CLIENT_SECRET` and `WIKICONTEXT_GOOGLE_WORKSPACE_DOMAIN`. Register `http://127.0.0.1:8765/callback` and the approved origin's `/api/oauth2-redirect`. Use ordinary user credentials for knowledge operations. Read [deployment preparation](docs/deployment.md) before hosting; this repository has not been deployed.

## Portable skill

Copy `skills/wikicontext/` to your agent's skill directory. It works outside this repository. Set `WIKICONTEXT_URL` and `WIKICONTEXT_USER_EMAIL`; use Google login or the optional `WIKICONTEXT_USER_PASSWORD` for an existing account.

```sh
python3 /path/to/wikicontext/scripts/wc.py login --google
python3 /path/to/wikicontext/scripts/wc.py check
python3 /path/to/wikicontext/scripts/wc.py ingest /path/to/source.md
python3 /path/to/wikicontext/scripts/wc.py search 'launch date'
python3 /path/to/wikicontext/scripts/wc.py lint
python3 /path/to/wikicontext/scripts/wc.py export-obsidian /path/to/vault
```

Over SSH, forward the CLI loopback port from your browser computer with `ssh -L 8765:127.0.0.1:8765 user@host`. The cache contains only the application token with private permissions. `logout` removes the local cache; it does not revoke copies elsewhere.

The `ingest` command uploads the immutable original and extracts passages. The agent then follows the skill to synthesize summaries/concepts, create citations/links, and publish a staging run. Uploading/extracting alone is not a completed knowledge-ingestion workflow. The server validates publication and rejects stale synthesis with 409. No LLM runs inside the server or Markdown exporter.

Supported extraction: UTF-8 text/Markdown and related text formats; text PDFs using local `pdftotext`; audio using `ffmpeg`, `ffprobe` and the configured Groq service. Audio ingestion authorizes transcription; originals are retained. Set only this application's `WIKICONTEXT_GROQ_API_KEY` in the agent environment. Missing tools, scanned PDFs without text, oversize derivatives and provider errors stop extraction with resumable source storage. No OCR or background crawler is supplied.

The exporter writes `wiki/` and `raw/` under the destination. Numbered source footnotes, wiki-links, page metadata, index and publication log are deterministic. Exports pin one immutable publication; `--sequence N` selects history. An ownership manifest detects local edits/deletions, prevents overwriting unrelated files, and supports interrupted-export recovery. `.obsidian/` remains untouched. Avoid concurrent local editing during export; the exporter lock coordinates exporters, not external editors. Use a fresh destination for initial migration: existing authored wiki files are not silently adopted. Downloaded files cannot be revoked remotely.

See [data model](docs/data-model.md) and [skill workflows](skills/wikicontext/references/workflows.md) for synthesis, idempotency, queries, corrections and publication. Structural lint does not establish semantic correctness. The current search scans published page text through SQL and does not supply native FTS/vector search. Raw SQL queries must explicitly distinguish draft revisions from the published manifest.

## Validation

Use synthetic isolated databases only. From this repository, with the pinned server built:

```sh
python3 tests/integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/publication_review.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/auth.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/realtime_access.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/oauth_integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/skill.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/ingest_integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/export_integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/deploy.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/backup_integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/oauth.py
python3 tests/client.py
python3 tests/ingest.py
python3 tests/exporter.py
python3 tests/backup.py
python3 tests/bootstrap.py
python3 tests/deploy_workflow.py
```

Regenerate the SQL reference only after reviewing intentional changes: `tests/skill.py --binary ... --write-schema`. Container CI additionally runs configuration, persistence, crash restore and graceful shutdown checks. Main-branch image publication is gated on application tests and native container checks; deployment additionally requires the configured `COLORS_PROFILE` environment. A real Google browser login, live Groq transcription and container checks remain separate from local synthetic acceptance.

## Existing wiki migration

The existing `wiki/` checkout has not been modified or migrated. Import originals through ordinary API ingestion, retrieve actual Git LFS audio rather than its pointer, and import authored pages as explicitly labelled legacy revisions with mapped evidence. Preserve slugs, original citations and legacy log text; do not claim imported legacy logs are server audit events. Compare a fresh generated vault before switching Obsidian. Never use direct SQLite writes or production data for migration tests. A bulk legacy importer is not supplied in this version.

## Infrastructure provenance

Authentication and portable OAuth client adapted from RaiseContext `44f8f10537388f9a934a2bc1800d3df6a046c580`; revision/concurrency and realtime test patterns from TaskContext `5bb214ef32fcffa9a42bb1de2d13cfd4052dc80f`; protected originals, complete backups and container/deployment patterns from AccountContext `2b78c0f38680381376b0ce485312ff659037a13f`. WikiContext's domain schema and publication/export model are independent. Server pin: `381f81042586afdaa6498b8c0e2a78229a55bdff`.
