# Background SQL snapshots

WikiContext enables `snapshot.background`. Each authenticated requester has a
private complete SQLite copy of the SQL tables and rows permitted at capture
time. Arbitrary permitted read SQL remains available. Builds stream values into
disk files and atomically replace the completed generation; a failed or cancelled
build never becomes readable. Available reads keep using the previous completed
generation while a replacement builds. This includes eventual membership
revocation for SQL and search. Account authentication, REST, realtime and protected
files continue to enforce their independent current authorization.

WikiContext enables `snapshot.trackChanges`. The server checks transactional
change tokens for the exported tables, their filter inputs and the `users`
collection. Commits confined to other tables leave a completed generation in
place. Changes to a tracked table refresh each cached requester, even when the
changed row belongs to another space. Each refresh builds a complete SQL copy
and its current-publication search indexes.

The first startup with tracking enabled requires a writable database to install
and seed the version table and its triggers. Later frozen restarts verify the
installed definitions. Rolling back the application image also restores its
previous configuration. The installed triggers continue to update their tokens
when that image writes.

## Consistency

`POST /api/context/query` and `/api/context/search` accept `consistency: available`
or `fresh`. Available is the asynchronous-mode default. Fresh waits for a copy
covering the source version observed at request start, reusing a completed copy
when it already covers that version. Writes arriving later do not move this
barrier. A fresh request after a successful REST write therefore observes it.
Fresh is a read requirement; it never replays or changes a write.

`atLeast` accepts a previously returned snapshot generation for the same requester.
It is a minimum copy generation, not a REST write watermark. Query
`expectedGeneration` requires an exact current copy. Search instead uses
`snapshotGeneration` for this exact requirement; its existing `expectedGeneration`
continues to mean the FTS content fingerprint. Retired copies are not replayable.

Query and search JSON responses include `snapshot` with `generation`, `capturedAt`,
`refreshing`, `stale`, `rows`, `diskBytes` and optional `lastError`. CSV exposes
equivalent `X-Context-Snapshot-*` headers. `GET /api/context/snapshot` reports only
the authenticated requester's status and schedules a dirty refresh without waiting.
Before the first completed copy, the generation is absent.

Operators can read process-wide counters at `GET /api/context/snapshot/metrics`
with superuser authentication. `unrelatedChanges` counts observations that
skipped a refresh. One observation can cover several commits.
`generationBytes` sums logical SQL and warmed search file sizes at publication.
Compare these counters with process write-byte deltas over the same uptime
interval to measure background work and disk I/O.

The Python client requests fresh SQL/search reads centrally, including ingestion
deduplication, recovery after a lost write response, export and publication
verification. Its transport timeout is 130 seconds. The browser uses available
reads, carries `atLeast` from observed SQL/search responses, and polls status while
refreshing or stale. Completion reconciles publication and evidence views without
requiring another realtime event. Membership, evidence-space resolution and latest
publication checks request fresh consistency. Previously displayed complete views
remain available while a new publication loads.

## Resource and failure bounds

The application configures 1 GiB total snapshot disk, 256 MiB minimum free disk,
one builder, at most 16 cached requesters, a 120-second build/fresh wait, a
one-second refresh/retry interval and a 16 MiB per-value streaming guard. These
are finite resource bounds, not row or corpus-byte caps. Complete copies still
require enough disk and time; refresh can temporarily retain old and new files.
Latest-publication FTS files belong to the copy, with historical scopes built
on demand. SQL and FTS files share the overall 1 GiB disk budget; legacy
`search.maxIndexBytes` and `search.cacheBytes` apply only in synchronous mode.
Disk growth is serialized and competing builds wait for a reservation. The
server retires idle requesters after 15 minutes and evicts requesters at the
16-requester cache limit. In-flight reads retain their generation until their
leases close. A subsequent read after eviction or restart builds a new copy.
Source databases/WAL and SQLite temporary working files require additional
host capacity.

The legacy `snapshot.maxRows`/`maxBytes` settings remain for separate filtered-read
budgets and synchronous fallback. They do not limit an asynchronous full SQL copy.
Final SQL output remains limited to 500 rows/1 MiB and query execution to two
seconds. Existing publication, evidence and field limits are unchanged.

`snapshot_pending` is HTTP 503 with `Retry-After: 1` when the requested copy is not
ready within its wait. `snapshot_resource_limit` is HTTP 503 for resource failure;
clients report it rather than reducing SQL page sizes. `snapshot_generation_conflict`
is HTTP 409 for an unusable generation requirement. A client can discard an old
minimum token after restart and retry once under the same authentication.
`result_limit` is HTTP 413 for final response size, where paging or narrower output
can help. Failed refreshes retain the last completed copy and expose status;
fresh operations fail rather than treating older data as current.
If the server cannot validate source tracking, status reports
`source_check_failed` and new SQL and search reads fail, including available
reads. A source schema change requires a restart to revalidate tracking.
