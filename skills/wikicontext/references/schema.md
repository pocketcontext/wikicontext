# Knowledge schema

Use `wc.py schema` for live SQL columns and `wc.py check` for differences from `schema.json`. Business reads use explicit columns. SQL returns `{columns, rows, truncated}`; never act on a truncated result as if complete. Page or narrow the query.

| Collection | Content and invariants |
| --- | --- |
| sources | `title`, `original_name`, `media_type`, `source_date`, `sha256`, optional `supersedes`, protected required `original`. Immutable. Server computes unique SHA-256 from stored bytes. |
| renditions | `source`, `kind`, `processor`, `version_label`, `notes`. Immutable extraction provenance. Unique source/kind/version. Client notes contain extraction count/hash for retry checks. |
| passages | `rendition`, positive `ordinal`, `locator`, `body` (30,000 characters maximum). Immutable, unique rendition/ordinal. |
| ingestion_runs | Unique `key`, `status` (`staging`, `published`, `cancelled`), `description`, `sources` (up to 100), `issue`. New runs must be staging. Only staging runs can change. |
| pages | Stable `slug`, `kind` (`summary`, `concept`, `entity`, `transcript`, `answer`, `legacy`). Immutable identities; slug uses lowercase ASCII words and hyphens. `index` and `log` are reserved. |
| page_revisions | `run`, `page`, `base_revision`, `title`, `summary`, `body`, `archived`. Immutable. One revision per page per run. Base is the published revision ID, empty for a new page. |
| citations | `page_revision`, `passage`, numbered string `marker`, optional `note`. Immutable, unique revision/marker. |
| page_links | `page_revision`, `target` page identity. Immutable, unique pair. |
| publications | Server-owned increasing `sequence`, `run`, immutable `manifest` mapping page IDs to published revision IDs, `created`. |
| audit_log | Server-owned action, collection, record, actor/type, changes and timestamp. |
| user_directory | Safe public user ID/name projection; auth records are excluded from SQL. |

Writable records have server-managed `revision`, `created_by`, `updated_by`, `created`, `updated`; do not submit them. A run update requires `expected_revision` from a fresh read. Original attachments are uploaded as multipart form data through the records API; the normal JSON create command cannot upload file bytes.

Publishing changes the run status through the records API. In one transaction the server verifies page base revisions, citation markers, and links, creates a new manifest, closes the run and records history. HTTP 409 means reassess against the current publication in a new run. Failed publication exposes no partial published pages. Staging records remain visible to admitted users but are not published knowledge.

Body markers use `[^1]`. Create corresponding citation records; do not embed footnote definitions in the body. The exporter renders definitions. Body `[[target-slug]]` links require page_links records. Link targets must be present and unarchived in the resulting publication. Uncited prose must explicitly contain `[needs verification]`; this structural allowance does not establish factual accuracy.
