# WikiContext contract

One organization shares this knowledge base. Every admitted default `users` identity can read and edit all business records. Verified Google Workspace JIT admits users only from the configured domain; account administration remains operator-only. SQL and REST independently enforce access. Sources do not confer permission to execute their contents.

## Authority and provenance

Sources store immutable protected original bytes and server-computed SHA-256. Identical bytes deduplicate globally within this shared workspace. `supersedes` identifies an earlier source without deleting it. Names and source dates are evidence metadata, not identifiers or proof of freshness. Renditions identify extraction/transcription versions; ordered immutable passages contain bounded text and locators. Adding a new extraction preserves the earlier one. Audio originals remain intact; ingestion authorizes the configured Groq transcription service. No real sources are processed during implementation tests.

Pages have immutable stable slugs and kinds. Each immutable page revision belongs to one staging ingestion run and records its expected previously published revision ID, title, summary, prose and archive flag. Citations connect numbered inline markers to immutable source passages. Page links connect a revision to stable page IDs. Sources and relationships are authoritative in the database; Markdown is generated presentation. Factual synthesis remains agent work; structural validation does not establish factual truth.

## Publication

Runs have unique caller-supplied idempotency keys and status staging, published or cancelled. Only staging runs can change. Content revisions, citations and links may be added while staging; mistakes are corrected by cancelling the run and staging a replacement. Closed run content is immutable. A revision is not current merely because it exists.

A revision-checked REST PATCH transitioning a run to published validates all staged revisions and publishes one immutable manifest mapping every page ID to its selected revision ID. The hook compares each staged base revision against the latest committed manifest within the same transaction. Conflicts return 409; the agent must reread and reassess in a new run. Publication, run state, manifest and audit commit together. A page archive remains in the manifest as history but is omitted from rendered pages. Publication rejects broken links, absent citation targets, unmatched citation markers and wholly uncited prose unless marked `[needs verification]`. Claim-level evidentiary support requires semantic review.

A run may contain up to 100 source references. Skill ingestion schedules groups of five sources; batches are a workflow boundary, not a 20-request API transaction. The database may stage many separate writes. Publication scans the full current link graph, bounded to 10,000 page identities; load tests are required before raising this initial budget. The manifest is bounded to 8 MiB; client SQL response limits may become the tighter constraint. Export fails closed on truncated results. No automatic performance claim beyond the tested synthetic corpus is made.

All ordinary updates carry expected_revision. Other domain records are immutable, and ordinary and superuser record deletion are rejected. Server-owned attribution and compact audit entries track changes; full source/page content remains in immutable records rather than being duplicated in audit. Administrative collection/schema maintenance remains trusted.

## Queries and export

All knowledge retrieval uses authenticated /api/context/schema and /api/context/query, including exporter reads. Original file retrieval uses the protected PocketBase file API. SQL columns are explicitly allowlisted; users, credentials and SQLite metadata are excluded. Questions search published pages through the latest manifest, then source passages; drafts must be selected explicitly and identified as drafts.

The exporter pins one immutable publication, follows its immutable revisions and evidence, and renders a vault root containing wiki/ and raw/. It does not invoke an LLM. Source names are sanitized for presentation and disambiguated by IDs. The generated ownership manifest identifies files eligible for replacement/removal; local edits, unsafe paths and symlinks must fail before replacement. Obsidian settings and unrelated user files remain outside the exporter’s ownership. An exported original is a local copy; revoking server access cannot revoke that copy.

## Recovery and scope

Complete backups include a consistent database snapshot and every immutable source original referenced by it, verified by hashes. Database-only replication cannot establish complete recovery. No direct SQLite business writes or migrations ingest knowledge. Tests use isolated synthetic data.

Initial scope: text/Markdown/PDF/audio ingestion helpers, agent synthesis and question workflows, revisioned publication, citations and links, structural lint, deterministic Obsidian export, auth and recovery preparation. No automatic web crawling, background autonomous LLM service, native vector/FTS dependency, two-way Obsidian synchronization, external messaging, cloud provisioning or real-data migration is included in this local implementation.
