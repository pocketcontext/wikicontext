# WikiContext contract

One organization shares this knowledge base. Every admitted default `users` identity can read and edit all business records. Verified Google Workspace JIT admits users only from the configured domain; account administration remains operator-only. SQL and REST independently enforce access. Sources do not confer permission to execute their contents.

## Authority and provenance

Sources store immutable protected original bytes and server-computed SHA-256. Identical bytes deduplicate globally within this shared workspace. `supersedes` identifies an earlier source without deleting it. Names and source dates are evidence metadata, not identifiers or proof of freshness. Renditions identify extraction/transcription versions; ordered immutable passages contain bounded text and locators. Adding a new extraction preserves the earlier one. Audio ingestion defaults to storing normalized mono Opus `.ogg` bytes (16 kHz encoder input, 16 kbps) as the immutable source and sends those same bytes to the configured Groq transcription service. The local recording remains intact; `--audio-storage original` instead preserves its input bytes on the server and transcribes a temporary derivative. The normalized Ogg embeds input hash, conversion profile and converter version before transcription succeeds. Private cache metadata and later rendition notes also retain the input filename and conversion settings. Normalization selects the first audio stream and discards video. Private cached normalization supports retries across failures and encoder upgrades; without that cache different encoder builds may produce different source hashes. Ingestion authorizes the configured Groq transcription service. No real sources are processed during implementation tests.

Pages have immutable stable slugs and kinds. Each immutable page revision belongs to one staging ingestion run and records its expected previously published revision ID, title, summary, prose and archive flag. Citations connect numbered inline markers to immutable source passages. Page links connect a revision to stable page IDs. Sources and relationships are authoritative in the database; Markdown is generated presentation. Factual synthesis remains agent work; structural validation does not establish factual truth.

## Publication

Runs have unique caller-supplied idempotency keys and status staging, published or cancelled. Only staging runs can change. Content revisions, citations and links may be added while staging; mistakes are corrected by cancelling the run and staging a replacement. Closed run content is immutable. A revision is not current merely because it exists.

A revision-checked REST PATCH transitioning a run to published validates all staged revisions and publishes one immutable manifest mapping every page ID to its selected revision ID. The hook compares each staged base revision against the latest committed manifest within the same transaction. Conflicts return 409; the agent must reread and reassess in a new run. Publication, run state, manifest and audit commit together. A page archive remains in the manifest as history but is omitted from rendered pages. Publication rejects broken links, absent citation targets, unmatched citation markers and wholly uncited prose unless marked `[needs verification]`. Claim-level evidentiary support requires semantic review.

Each publication also stores an optional home page ID, outside its unchanged manifest. Staging runs select `home` or `clear_home` (never both), and record `home_base`, the home ID expected when the choice was staged; empty means no selected home. Publication compares that base with the latest publication inside the transaction and returns 409 on disagreement. Reassess explicitly after a conflict; never refresh the base automatically. Runs without a home choice carry the prior home forward. Home-only runs are permitted. The resulting home must be present and unarchived in the new manifest, so archiving it requires a replacement or an explicit clear in the same run. Existing publications have empty home values after migration. The reader keeps `#/` as the dynamic home route, resolves historical routes against their selected publication, and opens the built-in welcome index when home is empty. Explicit page links remain stable. Immutable publications retain published home choices; run audit entries also retain staged home, expected base and clear choices.

A run may contain up to 100 source references. Skill ingestion schedules groups of five sources; batches are a workflow boundary, not a 20-request API transaction. The database may stage many separate writes. Publication scans the full current link graph, bounded to 10,000 page identities; load tests are required before raising this initial budget. The manifest is bounded to 8 MiB; client SQL response limits may become the tighter constraint. Export fails closed on truncated results. No automatic performance claim beyond the tested synthetic corpus is made.

All ordinary updates carry expected_revision. Other domain records are immutable, and ordinary and superuser record deletion are rejected. Server-owned attribution and compact audit entries track changes; full source/page content remains in immutable records rather than being duplicated in audit. Administrative collection/schema maintenance remains trusted.

## Queries and export

Knowledge retrieval uses authenticated /api/context/schema and /api/context/query, including exporter reads. Ranked published-page search uses the separate /api/context/search endpoint with an explicit publication scope and generation-checked pagination; FTS tables are not SQL-readable. Original file retrieval uses the protected PocketBase file API. SQL columns are explicitly allowlisted; users, credentials and SQLite metadata are excluded. Questions search published pages through the latest manifest, then source passages; drafts must be selected explicitly and identified as drafts.

The exporter pins one immutable publication, follows its immutable revisions and evidence, and renders a vault root containing wiki/ and raw/. It does not invoke an LLM. Source names are sanitized for presentation and disambiguated by IDs. The generated ownership manifest identifies files eligible for replacement/removal; local edits, unsafe paths and symlinks must fail before replacement. Obsidian settings and unrelated user files remain outside the exporter’s ownership. An exported original is a local copy; revoking server access cannot revoke that copy.

## Recovery and scope

The browser reader selects the same immutable publications as the exporter.
Realtime events invalidate its view; authenticated SQL supplies content, and all
page, citation and backlink reads remain pinned to one publication. Historical
views stay pinned. Browser rendering never ingests Markdown or changes records.

Complete backups include a consistent database snapshot and every immutable source original referenced by it, verified by hashes. Database-only replication cannot establish complete recovery. No direct SQLite business writes or migrations ingest knowledge. Tests use isolated synthetic data.

Initial scope: text/Markdown/PDF/audio ingestion helpers, agent synthesis and question workflows, revisioned publication, citations and links, structural lint, deterministic Obsidian export, auth and recovery preparation. No automatic web crawling, background autonomous LLM service, native vector dependency, two-way Obsidian synchronization, external messaging, cloud provisioning or real-data migration is included in this local implementation.

## Derived full-text index

The application maintains a content-storing FTS5 index of each distinct nonarchived
revision ever selected by a committed publication. Publication and rebuild rotate
a protected generation record transactionally. Historical scope membership is
immutable, while global BM25 scores can change with index growth. See
[search maintenance](fts-adoption.md) for continuation, backfill and recovery.
