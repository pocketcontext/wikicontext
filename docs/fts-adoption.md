# Proposed publication-scoped search

This is a design for a later implementation, not an enabled search API or an
application migration. Adopting JSON traversal and percentile functions does not
enable FTS in WikiContext. The reader and portable skill retain lexical search.

## Existing boundaries

PocketContext's [search contract](https://github.com/pocketcontext/pocketcontext/blob/28337607721c3b671dfc6416a5f01ad40f5ffb00/docs/search.md)
accepts an index, literal query and bounded limit. It has no publication scope,
offset, cursor or index generation. Its separate read-only engine validates the
canonical content-storing `unicode61` index and executes fixed parameterized SQL.
Ordinary SQL cannot read its FTS or shadow tables. See the inspected
[engine](https://github.com/pocketcontext/pocketcontext/blob/28337607721c3b671dfc6416a5f01ad40f5ffb00/internal/searchread/engine.go).

WikiContext's [publication hook](../pb_hooks/integrity.js) commits an immutable
manifest with the run transition and audit. The [reader API](../ui/src/api.ts)
selects exactly the revisions in that manifest and excludes archived revisions.
The [portable client](../skills/wikicontext/scripts/knowledge.py) also pins a
publication. These semantics must survive FTS adoption. Filtering a globally
limited hit list afterward can omit relevant pages and is not a valid substitute.

## Proposed generic server contract

Extend the separate search endpoint, preserving its fixed SQL, authentication,
resource limits and shared-workspace visibility. No application-specific
publication logic belongs in PocketContext.

An index's configuration would declare a scope collection, a JSON object field
whose values identify indexed source records, and a generation collection,
fixed record ID and token field. All referenced collections and fields must be
ordinary, nonhidden, SQL-readable application data. Configuration supplies
identifiers; requests supply only values. Scope is result membership, not a new
authorization boundary. Every admitted user can still search configured scopes.

For WikiContext, the scope collection is `publications`, the selector is its
record ID, and the membership field is `manifest`. The generation is a separate
application-maintained record. Illustrative request fields, not implemented:

```json
{
  "index": "pages",
  "query": "deployment safety",
  "scope": "publication0001",
  "limit": 50,
  "offset": 0,
  "expectedGeneration": "opaque-index-generation"
}
```

The first request may omit `expectedGeneration`. The response returns the scope,
generation, hits and `hasMore`. Subsequent pages require that generation. The
server rejects a changed generation with 409, and the client restarts results
instead of appending a potentially inconsistent page. Offsets and scope sizes
need explicit bounds; WikiContext's current publication budget is 10,000 pages.

Within one read transaction the server must validate the scope and generation,
validate the index, filter membership before pagination, and read results ordered
by BM25 score then record ID. A missing scope must not become an unscoped search.
Malformed membership must fail closed. Missing indexed members alone cannot
establish corruption: archived revisions intentionally have no index entry.
WikiContext's maintenance and recovery checks establish expected coverage.

The response limit remains bounded. Requesting one additional hit determines
`hasMore`; there is no promise of a cheap total count. Stable generation checking
is needed with either offset or keyset pagination. Signing a cursor alone would
not stabilize a changing ranking corpus.

## Application index and maintenance

Start with one index over `page_revisions`, using the immutable revision ID as
`record_id`, and title, summary and body as its text columns. Keep canonical
content-storing `unicode61` DDL. Measure title/summary/body weights before choosing
defaults. Slug, kind and normalized Markdown projections are outside this first
index; clients can fetch display metadata through the selected manifest.

Index each distinct nonarchived revision that has appeared in any committed
publication, once. Never index staging revisions. Archiving a page later must
not delete earlier nonarchived revisions: they remain searchable through earlier
manifests. The archive revision itself is not indexed, so it yields no hit in a
manifest selecting that archive. Historical revisions cannot leak into current
results because membership filtering precedes the limit.

Trusted publication hooks insert newly published searchable revisions and rotate
the generation token in the same transaction as publication, run state and audit.
Clients cannot write the generation record or derived index through ordinary
record APIs. Backfill traverses committed manifests and deduplicates revision
IDs. Rebuilds atomically replace derived contents and rotate the generation even
if publication identity is unchanged. Failed publication or rebuild rolls back
all derived changes. A restored database must contain mutually consistent
manifests, revisions, index and generation.

Generation is an application consistency promise: every index mutation,
including maintenance, must rotate it. It must not be inferred from a connection's
SQLite `data_version`, row count, maximum rowid or latest publication ID. Those
are insufficient to detect every rebuild or update across pooled requests.

## Ranking and client behavior

An all-history index uses global BM25 statistics. Even when membership is pinned
to an immutable publication, adding another revision can change the scores and
order of that publication's results. Generation checking prevents mixed pages;
it does not promise historically reproducible scores. Reproducible rankings
would require a separate design with stable statistics or stored search results.
Measure how repeated historical text affects relevance before shipping.

Browser and portable skill must use the same scope and generation contract.
Live views adopt a new publication and restart search; historical views keep their
publication but restart pagination if the corpus generation changes. Opening a
hit must resolve its page through that same publication. Preserve search query
and publication in navigation, and provide explicit restart, loading, empty and
error states. Continuous writes may repeatedly invalidate pagination; do not
silently append mixed-generation results to hide that limitation.

The existing endpoint treats whitespace-separated terms as literal FTS phrases
joined by AND. It provides neither prefix matching nor arbitrary substring
matching. Excerpts are untrusted plain text without match offsets. Render them
as text; faithful highlights, prefix matching and source-passage search require
separate contracts and tests.

## Implementation gates

1. Extend and test generic scope/generation configuration, fixed query generation,
   authorizer permissions, limits and HTTP conflict behavior in PocketContext.
   Preserve denials for hidden/auth/system fields, arbitrary SQL, FTS shadows,
   metadata, extensions and filtered-snapshot configurations.
2. Build synthetic fixtures covering drafts, archives, earlier nonarchived
   revisions, multiple revisions per page, publication conflicts, rollback,
   membership corruption and concurrent publication between result pages.
3. Implement application backfill, transactional maintenance and generation
   protection. Verify rebuild failure, complete backups and populated restores.
4. Benchmark near the page budget with realistic revision history and document
   lengths. Measure relevance, broad/missing queries, concurrent readers,
   publication cost, index growth and generation restarts. The existing core
   [benchmark](https://github.com/pocketcontext/pocketcontext/blob/28337607721c3b671dfc6416a5f01ad40f5ffb00/docs/search-benchmark.md)
   does not establish a general speedup; per-request corpus validation is O(N).
5. Adopt the tested server pin, then enable the application index and common
   browser/skill contract. Run the README application, UI and container/restore
   gates, including keyboard/mobile navigation and hostile excerpt content.

Latest-only FTS plus lexical historical search is not the chosen design: it would
give the same reader different retrieval semantics without solving complete
pagination. Keep lexical search functional until the scoped contract is ready.
