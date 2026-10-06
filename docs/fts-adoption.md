# Publication-scoped full-text search

WikiContext uses PocketContext's separate authenticated `/api/context/search`
endpoint. Browser and portable client search published revision title, summary and
body with the same publication scope, ranking and generation checks. FTS indexes
are derived data; immutable revisions, publication manifests and evidence remain
authoritative. Ordinary SQL cannot read FTS or shadow tables.

## Contract

```json
{
  "index": "pages",
  "query": "deployment safety",
  "scope": "publication0001",
  "limit": 20,
  "offset": 0
}
```

Use a real publication record ID for `scope`. Results contain `scope`,
`generation`, `hits`, `hasMore` and `truncated`; hits contain revision `id`, BM25
`score` and plain-text `excerpt`. Lower scores rank first, with revision ID as the
stable tie-breaker within one index generation. Clients hydrate page identity,
slug, kind, title and summary through the same immutable manifest and fail if a
hit is absent or archived. Scope membership is filtered before the result limit.

The first request may omit `expectedGeneration`. Later pages send the returned
generation, the same scope and query, and an increased offset. HTTP 409 means the
index changed: discard accumulated pages and restart at zero without the old
generation. Browser results expose a restart action rather than silently mixing
pages; the portable client exits with code 4 and prints restart instructions.

The returned generation is an opaque digest of the application state token, index
configuration, ranking contract, SQLite identity, selected scope and validated
membership. Replay the API response token; the raw SQL `search_state.generation`
value is not a pagination token. Configuration or membership changes invalidate
continuation even when the application state token stays unchanged.

Limits are 1–100 results per request (default 20), 0–10,000 offset, 10,000 scope
members, 4096 query UTF-8 bytes and 16 whitespace-separated terms. Every term is
encoded as a literal FTS phrase joined with AND. There is no raw FTS expression,
prefix, arbitrary substring, typo correction or semantic search. This deliberately
changes the old substring search behavior. Slugs and page kinds are display
metadata, not indexed text. Empty browser input returns to browsing.

Excerpts are untrusted plain text. Clients render them without source HTML or
fabricated highlighting. They are navigation aids, not passage citations. Source
passages and originals remain available through the evidence viewer and SQL/file
APIs; they are not part of this search index.

## Publication and history

`published_pages_fts` is one canonical content-storing `unicode61` index over
`page_revisions`. `record_id` is the immutable revision ID. Initial
title/summary/body weights are 8/3/1; see [measurements](search-benchmark.md) for
the synthetic evaluation and its limits.

The migration backfills each distinct nonarchived revision selected by any
committed publication. Publication hooks insert newly published nonarchived
revisions and rotate `search_state/pagesindexstate.generation` in the same
transaction as the publication, run transition and audit. Failed publication
rolls back both derived and canonical changes. Staged revisions are never indexed.

Archiving later does not delete an earlier nonarchived revision: historical
publications must still find it. An archive revision itself is not indexed. The
selected publication's manifest controls which historical revision can match.

An all-history index uses global BM25 statistics. Additional publications may
change the scores/order of an older publication's results. Generation checking
prevents inconsistent pagination; it does not provide historically reproducible
rankings. Continuous publication can require repeated restarts. A restart with
changed ranking configuration also invalidates existing pagination tokens.

## Maintenance and recovery

The `search_state` collection is SQL-readable but server-maintained. Record API
creation, update and deletion are rejected even for superusers. Ordinary users
cannot write FTS tables or rotate the generation.

An operator with an existing superuser maintenance session may call
`POST /api/wiki/search/rebuild` with no request body. The route validates all
publication manifests, atomically rebuilds the derived index from canonical
records, and rotates the application state token. Its `stateGeneration` response
is the raw maintenance token, not the opaque search pagination token. Failure preserves the previous complete
index and token. A rebuild holds the writer transaction and can delay publication;
use a maintenance window for large histories. It repopulates a valid index, not
a dropped or noncanonical FTS schema; restore trusted schema or a verified backup
before rebuilding such an index. Do not expose maintenance credentials to knowledge clients or
use this endpoint as part of ordinary search. Search never repairs indexes.

Litestream database replicas include the index and generation. After
restore, validate historical/live membership and protected originals. Rebuild can
repair derived contents from valid canonical data; it cannot repair invalid
publication manifests. Preserve the single-writer deployment procedure.

## Validation and resource limits

The server validates canonical FTS/shadow DDL and every indexed ID on each search,
then reads the scope, generation and ranked matches in the same read transaction.
It rejects malformed, missing or duplicate scope keys and missing source records.
Archived revisions may legitimately have no index entry; application tests and
maintenance establish index coverage. Scope is a result filter, not a separate
permission model: all admitted workspace users share search access.

Whole-index validation is O(N), where N includes historical indexed revisions.
A result limit does not cap ranking/validation work. The configured two-second
deadline, one-MiB response cap, shared SQLite heap bound and four-connection search
pool still apply. Timeouts or unavailable indexes produce explicit failures;
clients do not silently fall back to a different retrieval model.

Run the README's full validation suite, including `tests/search_integration.py`,
portable client pagination/conflicts, UI browser checks and complete populated
container restore gates. `tests/search_benchmark.py` measures synthetic relevance,
latency, publication cost and storage across revision history; it is not a live
WikiContext performance guarantee.
