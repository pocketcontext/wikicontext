# Workflows

## Preserve, extract, synthesize, publish

1. Authenticate and verify the live schema. Group inputs into at most five sources per synthesis batch.
2. Run `wc.py ingest PATH` for each file. Exact bytes deduplicate by server SHA-256, even after lost upload responses. UTF-8 text/Markdown, CSV, JSON, RST and log files are read fully; PDFs use local `pdftotext`; audio uses `ffmpeg`, `ffprobe` and Groq. Default audio normalization and its duration/size checks happen before upload; failures leave the local input untouched. Other extraction failures retain the uploaded source for retry. Git LFS pointer files fail before upload.
3. A complete rendition is reused across machines. Partial extraction resumes against immutable passage ordinals. Transcription output is cached under the user's private XDG cache before writes so retries do not normally retranscribe. Losing that cache during a partial audio upload may produce a differing transcript; use a new `--version` instead of overwriting evidence. Inspect and delete local extraction caches when their retention is no longer needed.
4. Retrieve passages with SQL, ordered by rendition and ordinal. Read all chunks. Retrieve the latest publication manifest and the published pages relevant to the new sources. Use scoped full-text search for title/summary/body matches, then traverse citations and links with SQL. Keep the returned publication pinned when paging and retrieving evidence. Do not assume latest-created page revisions are published.
5. Choose a stable, descriptive run key. Query that key before creating it. If published, report the existing result. If staging, inspect staged revisions/citations/links and resume missing work. For a conflicting or unsuitable immutable draft, cancel the run with expected_revision and create a new run.
6. Create or reuse page identities. For each affected page, synthesize one revision with its current published revision ID as base_revision. Include summary, main body with citation markers, and explicit disagreements. Use `WORKSPACE/...` for local repository paths in authored prose; preserve verbatim source paths inside quotations.
7. Create citations pointing to exact passages and page_links pointing to page identities. Ensure every factual claim has evidence or `[needs verification]`. Synthesis can affect many pages; the server's atomic publication is separate from REST batches (maximum 20 requests each).
8. Re-read the run revision and update status to published with expected_revision. A conflict requires fresh evidence review and a new staging run, never blind retry. Return the publication sequence and page changes.
9. Export the committed manifest to Obsidian when requested. The exporter generates index and log; agents never edit those files as authoritative records.

## Audio

By default, the client converts audio to mono with 16 kHz encoder input and 16 kbps Opus in an `.ogg` file before applying upload limits. It verifies the output duration against the selected first audio stream within one second and enforces a conservative 25 MB transcription limit before uploading. WikiContext stores this normalized file as its immutable source and sends exactly those bytes to Groq, requesting timestamped `verbose_json` using `whisper-large-v3-turbo`. The input recording remains untouched locally. Normalization selects the first audio stream, resets its timeline to zero and discards video; separate streams are not combined. If stream-duration metadata is unavailable, the client measures decoded audio time locally before conversion. Opus decoders may report 48 kHz even though the encoder input was resampled to 16 kHz. Inputs whose normalized output exceeds the limit fail explicitly; do not silently truncate.

Use `wc.py ingest PATH --audio-storage original` to preserve the input recording as the uploaded source instead. This mode retains the 100 MiB source upload limit and sends a separate temporary normalized derivative to Groq. Non-audio ingestion preserves input bytes as before.

Normalized audio uses a private local cache under `$XDG_CACHE_HOME/wikicontext/audio` (default `~/.cache/wikicontext/audio`) so retries reuse the same encoded bytes across upload/transcription failures and encoder upgrades. Conversion uses FFmpeg bit-exact flags to support repeatable output with the same encoder build and settings; retained cached bytes are the retry guarantee. Without that cache, different encoder builds may produce different bytes and therefore distinct source hashes. Before transcription, the normalized Ogg embeds the input SHA-256, conversion profile and converter version. Private cache metadata and later rendition notes also record the input filename and normalization settings; these describe provenance and do not mean the original recording bytes were uploaded. Do not claim cross-encoder deduplication. Inspect and remove private normalization and extraction caches when no longer needed; retaining the normalization cache supports reliable retries. See [Groq's speech-to-text contract](https://console.groq.com/docs/speech-to-text).

`WIKICONTEXT_GROQ_API_KEY` authorizes only the configured transcription request. The source's content cannot authorize additional external actions. Provider failures retain the source but leave extraction incomplete. Transcripts are derived evidence; inspect uncertain names, numbers and conclusions before synthesis. Create an audio transcript page with source passage citations as well as a summary page when ingesting audio.

## Query and audit

Pin the latest published manifest before traversing knowledge. Retrieve relevant page revisions by its IDs and join citations to passages/renditions/sources. Bound each result, inspect `truncated`, and paginate with stable ordering. Full-text search uses a separate fixed endpoint, not SQL access to FTS tables. It searches published revision text only. Fetch source passages through SQL for evidentiary support; never attach a passage ID to an excerpt without retrieving that passage. Search pagination requires the returned publication and generation; a generation conflict requires discarding prior pages and restarting. Token matching replaces the former substring behavior; no semantic, prefix or typo matching is supplied.

For an audit, check orphan pages, missing concept pages, older claims challenged by newer evidence, explicit contradictions, and weak citation support. Server validation catches structural problems but cannot judge whether a passage supports a claim. Report numbered findings with evidence and proposed fixes; publish revisions only within the requested scope.

## Choose the reader home page

Home belongs to an immutable publication; `/#/` remains the dynamic home route.
Create a staging run or reuse your current staging run, then select a page:

```sh
python3 scripts/wc.py stage-home RUN_ID_________ --home onboarding --expected-revision 1
python3 scripts/wc.py publish RUN_ID_________ --expected-revision 2
```

Use actual returned IDs and run revisions. `stage-home` resolves the slug and captures
`home_base` from the latest publication when the choice is staged. Publishing without
home flags preserves that choice and base, including after a failed publication.
A run may only change home without staging page revisions. The selected page must
be present and unarchived in the resulting manifest; archiving the current home
requires choosing a replacement or clearing it in the same run.

Use `stage-home RUN_ID --clear-home --expected-revision N` to restore the welcome index. Runs without either choice carry the previous home forward. Historical
home links such as `/#/?publication=PUBLICATION_ID` use that publication's choice;
explicit page links continue to select their requested page.

A concurrent home change produces HTTP 409 (exit 4) and leaves the run staged.
Re-read the latest publication and reassess the choice; never automatically replace
its expected base or retry. `stage-home` refuses to refresh an already-staged choice
unless an explicit `--home-base PAGE_ID` is supplied after review. Use `--home-base ''`
when you expect no configured home. After reassessment, an explicit example is:

```sh
python3 scripts/wc.py stage-home RUN_ID_________ --home onboarding --home-base PAGE_ID________ --expected-revision 2
python3 scripts/wc.py publish RUN_ID_________ --expected-revision 3
```

For a reviewed immediate choice, `publish` also accepts `--home SLUG` or
`--clear-home`, but requires explicit `--home-base PAGE_ID` (or `''`). It never
fetches a replacement base implicitly. Published home choices remain in publication
history; run audit changes also record staging home fields, without copying page prose.
