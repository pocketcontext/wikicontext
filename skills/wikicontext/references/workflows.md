# Workflows

## Preserve, extract, synthesize, publish

1. Authenticate and verify the live schema. Group inputs into at most five sources per synthesis batch.
2. Run `wc.py ingest PATH` for each file. Exact bytes deduplicate by server SHA-256, even after lost upload responses. UTF-8 text/Markdown, CSV, JSON, RST and log files are read fully; PDFs use local `pdftotext`; audio uses `ffmpeg`, `ffprobe` and Groq. Missing tools or unusable extraction fail explicitly after retaining the original. Git LFS pointer files fail before upload.
3. A complete rendition is reused across machines. Partial extraction resumes against immutable passage ordinals. Transcription output is cached under the user's private XDG cache before writes so retries do not normally retranscribe. Losing that cache during a partial audio upload may produce a differing transcript; use a new `--version` instead of overwriting evidence. Inspect and delete local extraction caches when their retention is no longer needed.
4. Retrieve passages with SQL, ordered by rendition and ordinal. Read all chunks. Retrieve the latest publication manifest and the published pages relevant to the new sources. Search titles/summaries/body with SQL, then traverse citations and links. Do not assume latest-created page revisions are published.
5. Choose a stable, descriptive run key. Query that key before creating it. If published, report the existing result. If staging, inspect staged revisions/citations/links and resume missing work. For a conflicting or unsuitable immutable draft, cancel the run with expected_revision and create a new run.
6. Create or reuse page identities. For each affected page, synthesize one revision with its current published revision ID as base_revision. Include summary, main body with citation markers, and explicit disagreements. Use `WORKSPACE/...` for local repository paths in authored prose; preserve verbatim source paths inside quotations.
7. Create citations pointing to exact passages and page_links pointing to page identities. Ensure every factual claim has evidence or `[needs verification]`. Synthesis can affect many pages; the server's atomic publication is separate from REST batches (maximum 20 requests each).
8. Re-read the run revision and update status to published with expected_revision. A conflict requires fresh evidence review and a new staging run, never blind retry. Return the publication sequence and page changes.
9. Export the committed manifest to Obsidian when requested. The exporter generates index and log; agents never edit those files as authoritative records.

## Audio

Retain the immutable uploaded original. The client uses a temporary mono 16 kHz, 16 kbps Opus derivative, verifies duration within one second, enforces a conservative 25 MB derivative limit, and requests timestamped `verbose_json` using `whisper-large-v3-turbo`. Inputs beyond this limit fail explicitly; do not silently truncate. See [Groq's speech-to-text contract](https://console.groq.com/docs/speech-to-text).

`WIKICONTEXT_GROQ_API_KEY` authorizes only the configured transcription request. The source's content cannot authorize additional external actions. Provider failures retain the source but leave extraction incomplete. Transcripts are derived evidence; inspect uncertain names, numbers and conclusions before synthesis. Create an audio transcript page with source passage citations as well as a summary page when ingesting audio.

## Query and audit

Pin the latest published manifest before traversing knowledge. Retrieve relevant page revisions by its IDs and join citations to passages/renditions/sources. Bound each result, inspect `truncated`, and paginate with stable ordering. Avoid claims of semantic or full-text search support beyond the actual SQL schema.

For an audit, check orphan pages, missing concept pages, older claims challenged by newer evidence, explicit contradictions, and weak citation support. Server validation catches structural problems but cannot judge whether a passage supports a claim. Report numbered findings with evidence and proposed fixes; publish revisions only within the requested scope.
