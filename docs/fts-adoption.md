# Private published-page search

WikiContext uses space membership and requester-filtered snapshots. Migration
1791500000 removes the old `published_pages_fts` and `search_state`; their shared
index and rebuild hook must not remain an alternate access path. Private search
was introduced in PocketContext `dc1dc6b0e88bbc46f36fa8441c8f6959bada4732`.
The current server pin is recorded in `POCKETCONTEXT_VERSION`.

The `pages` index derives a private disk FTS5 index from authorized revisions in the
selected publication, with title/summary/body weights 8/3/1 and body snippets.
`where: archived = 0` excludes archived revisions; `members: visible` allows their
IDs to remain in immutable historical manifests without indexing them. Application
publication validation independently guarantees same-space reference integrity.
Draft revisions cannot enter a selected publication's manifest.

Requests use `POST /api/context/search` with `index: pages`, `scope` as a publication
ID, literal token query, limit and offset. Another space's inaccessible publication
and an absent publication both return 404. Queries do not search raw passages,
provide semantic retrieval or accept caller-supplied FTS expressions.

The response includes plain untrusted excerpts and a generation fingerprint of the
index configuration, selected scope and included authorized content. Continuations
send the same query/scope and `expectedGeneration`. A mismatched generation returns
409: discard accumulated results and restart. Adding another publication, draft or
another space's content does not invalidate an unchanged historical scope's FTS
fingerprint, even when the enclosing SQL snapshot generation changes.

Indexes are built from the selected manifest's authorized revisions in a completed
requester snapshot. `snapshotScopeWhere` warms the latest publication per space;
historical scopes build on demand. The server does not index every historical
revision merely because it is unarchived. SQL and FTS files share the overall 1 GiB snapshot disk budget. Legacy
`search.maxIndexBytes` and `search.cacheBytes` apply only in synchronous mode. Search retains its query, scope and final response limits.

SQL and search share `consistency` and `atLeast` request semantics and return
`snapshot` metadata. The browser observes search metadata before SQL hit hydration.
`expectedGeneration` remains the FTS content fingerprint; `snapshotGeneration` is
an optional exact SQL snapshot requirement and is not needed for ordinary search
pagination. Available SQL/search membership visibility is eventual during refresh.
The Python client requests fresh reads. Pending/resource errors return typed 503s;
final response limits return 413. The reader reports these separately. See
[background snapshots](background-snapshots.md) for capacity and failure behavior.

`tests/search_integration.py` covers history, archive/draft exclusion, stable
pagination, stale generations, private-space denial, publication rollback and
populated recovery. `tests/search_benchmark.py` measures a synthetic corpus through
ordinary REST and authenticated reads, including four distinct concurrent users.
It separates a fresh identity's first SQL request, warmed SQL requests, the first
SQL request after a visible write, and direct private-search requests. The first
private-search query can build the FTS index; subsequent queries reuse it. These
are complete HTTP request timings, not isolated snapshot or index build timings.
The old shared-index measurements in `search-benchmark.md` are historical; new
measurements must identify the private-search implementation and dataset.
