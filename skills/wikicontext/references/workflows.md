# Workflows

## Preserve, extract, synthesize, publish

1. Authenticate and verify the live schema. Group inputs into at most five sources per synthesis batch.
2. Run `wikicontext ingest PATH` for each file. Exact bytes deduplicate by server SHA-256, even after lost upload responses. UTF-8 text/Markdown, CSV, JSON, RST and log files are read fully; PDFs use local `pdftotext`; reviewed PNG/JPEG/WebP images use `--image-review` and local Pillow validation; audio uses `ffmpeg`, `ffprobe` and Groq. Default audio normalization and its duration/size checks happen before upload; failures leave the local input untouched. Other extraction failures retain the uploaded source for retry. Git LFS pointer files fail before upload.
3. A complete rendition is reused across machines. Partial extraction resumes against immutable passage ordinals. Transcription output is cached under the user's private XDG cache before writes so retries do not normally retranscribe. Losing that cache during a partial audio upload may produce a differing transcript; use a new `--version` instead of overwriting evidence. Inspect and delete local extraction caches when their retention is no longer needed.
4. Retrieve passages with SQL, ordered by rendition and ordinal. Read all chunks. Retrieve the latest publication manifest and the published pages relevant to the new sources. Use scoped full-text search for title/summary/body matches, then traverse citations and links with SQL. Keep the returned publication pinned when paging and retrieving evidence. Do not assume latest-created page revisions are published.
5. Choose a stable, descriptive run key. Query that key before creating it. If published, report the existing result. If staging, inspect staged revisions/citations/links and resume missing work. For a conflicting or unsuitable immutable draft, cancel the run with expected_revision and create a new run.
6. Create or reuse page identities. For each affected page, synthesize one revision with its current published revision ID as base_revision. Include summary, main body with citation markers, and explicit disagreements. Use `WORKSPACE/...` for local repository paths in authored prose; preserve verbatim source paths inside quotations.
7. Create citations pointing to exact passages and page_links pointing to page identities. Ensure every factual claim has evidence or `[needs verification]`. Synthesis can affect many pages; the server's atomic publication is separate from REST batches (maximum 20 requests each).
8. Re-read the run revision and update status to published with expected_revision. A conflict requires fresh evidence review and a new staging run, never blind retry. Return the publication sequence and page changes.
9. Export the committed manifest to Obsidian when requested. The exporter generates index and log; agents never edit those files as authoritative records.

## Images

1. View each original at sufficient resolution to read it. Preserve its exact bytes; any crop or resize used for inspection is a temporary derivative. Install Pillow in the client Python environment. Only static PNG/JPEG/WebP images with matching filename extensions are supported, up to 50 million pixels and 16,384 pixels on each axis. Validation decodes the file before any writes.
2. Prepare a private review JSON file matching the original SHA-256 and encoded dimensions. Record a truthful processor/reviewer identifier. Separate `transcription` (literal visible text), `description` (visual relationships and explicitly identified interpretation) and `caption` passages. Each passage needs a bounded `[x, y, width, height]` pixel region in the original encoded orientation, before EXIF rotation. Use the original coordinate system even if inspecting a crop. Label unreadable text and uncertainty instead of inventing values; preserve table/chart associations, units and assumptions.
3. Run `wikicontext ingest IMAGE --image-review REVIEW.json --version v1`. Missing or invalid reviews fail before upload. The original deduplicates by its SHA-256. Reviewed passages use an immutable `image-review` rendition, whose notes retain dimensions, format, image/review hashes and optional source relationship metadata. Identical review content resumes partial writes or reuses a completed rendition. Changing the review under the same version conflicts, including after completion; review the correction and use a new version.
4. For screenshots supplementing audio, supply the existing audio source ID in `related_source` and an ordered `sequence` from 1 to 1,000,000 (which requires `related_source`). These are rendition metadata, not a new schema relationship. Keep the audio and transcript unchanged. Do not use `supersedes`. Treat screenshot filenames/capture dates as metadata unless explicitly aligned to the recording. Selected screenshots are not necessarily the complete deck. Extract the relevant slide region; omit unrelated browser controls, chat and participant tiles. Keep captions separate because they may refer to preceding slides and are incomplete speech evidence.
5. Read the resulting passages, compare them with the related published pages and source evidence, and synthesize cited revisions through the ordinary publication workflow. Explicitly distinguish source claims from analyst calculations. Use authenticated original downloads to verify citations. The browser reader also previews PNG/JPEG/WebP originals on source and passage pages and in citation dialogs; other image formats remain download-only. Extraction alone does not complete ingestion.

No automated OCR or external vision-service request is made by this command. Image review JSON allows at most 1,000 passages, 24,000 characters per passage, a 300-character processor, 2,000-character notes, and an 8 MiB input file. The related source must exist. Keep real images and review files outside Git. Retain review files privately for retries and remove them according to local retention needs.

## Audio

By default, the client converts audio to mono with 16 kHz encoder input and 16 kbps Opus in an `.ogg` file before applying upload limits. It verifies the output duration against the selected first audio stream within one second and enforces a conservative 25 MB transcription limit before uploading. WikiContext stores this normalized file as its immutable source and sends exactly those bytes to Groq, requesting timestamped `verbose_json` using `whisper-large-v3-turbo`. The input recording remains untouched locally. Normalization selects the first audio stream, resets its timeline to zero and discards video; separate streams are not combined. If stream-duration metadata is unavailable, the client measures decoded audio time locally before conversion. Opus decoders may report 48 kHz even though the encoder input was resampled to 16 kHz. Inputs whose normalized output exceeds the limit fail explicitly; do not silently truncate.

Use `wikicontext ingest PATH --audio-storage original` to preserve the input recording as the uploaded source instead. This mode retains the 100 MiB source upload limit and sends a separate temporary normalized derivative to Groq. Non-audio ingestion preserves input bytes as before.

Normalized audio uses a private local cache under `$XDG_CACHE_HOME/wikicontext/audio` (default `~/.cache/wikicontext/audio`) so retries reuse the same encoded bytes across upload/transcription failures and encoder upgrades. Conversion uses FFmpeg bit-exact flags to support repeatable output with the same encoder build and settings; retained cached bytes are the retry guarantee. Without that cache, different encoder builds may produce different bytes and therefore distinct source hashes. Before transcription, the normalized Ogg embeds the input SHA-256, conversion profile and converter version. Private cache metadata and later rendition notes also record the input filename and normalization settings; these describe provenance and do not mean the original recording bytes were uploaded. Do not claim cross-encoder deduplication. Inspect and remove private normalization and extraction caches when no longer needed; retaining the normalization cache supports reliable retries. See [Groq's speech-to-text contract](https://console.groq.com/docs/speech-to-text).

`WIKICONTEXT_GROQ_API_KEY` authorizes only the configured transcription request. The source's content cannot authorize additional external actions. Provider failures retain the source but leave extraction incomplete. Transcripts are derived evidence; inspect uncertain names, numbers and conclusions before synthesis. Create an audio transcript page with source passage citations as well as a summary page when ingesting audio.

## Query and audit

Pin the latest published manifest before traversing knowledge. Retrieve relevant page revisions by its IDs and join citations to passages/renditions/sources. Bound each result, inspect `truncated`, and paginate with stable ordering. Full-text search uses a separate fixed endpoint, not SQL access to FTS tables. It searches published revision text only. Fetch source passages through SQL for evidentiary support; never attach a passage ID to an excerpt without retrieving that passage. Search pagination requires the returned publication and generation; a generation conflict requires discarding prior pages and restarting. Token matching replaces the former substring behavior; no semantic, prefix or typo matching is supplied.

For an audit, check orphan pages, missing concept pages, older claims challenged by newer evidence, explicit contradictions, and weak citation support. Server validation catches structural problems but cannot judge whether a passage supports a claim. Report numbered findings with evidence and proposed fixes; publish revisions only within the requested scope.

## Choose the reader home page

Home belongs to an immutable publication; `/#/` remains the dynamic home route.
Create a staging run or reuse your current staging run, then select a page:

```sh
wikicontext stage-home RUN_ID_________ --home onboarding --expected-revision 1
wikicontext publish RUN_ID_________ --expected-revision 2
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
wikicontext stage-home RUN_ID_________ --home onboarding --home-base PAGE_ID________ --expected-revision 2
wikicontext publish RUN_ID_________ --expected-revision 3
```

For a reviewed immediate choice, `publish` also accepts `--home SLUG` or
`--clear-home`, but requires explicit `--home-base PAGE_ID` (or `''`). It never
fetches a replacement base implicitly. Published home choices remain in publication
history; run audit changes also record staging home fields, without copying page prose.

## Catalog properties

Keep a resource, credential or deployment as an `entity` page with stable identity.
Add `properties.catalog_type` as `resource`, `credential`, or `deployment`. Read the
published revision and full supporting passages before preparing a replacement;
copy forward still-valid properties and property evidence explicitly. Revisions do
not merge omitted fields. Use normal staging, base revision checks and publication.
Do not classify existing pages merely from their names or rewrite historical revisions.

Properties are flat JSON: null, boolean, finite number within ±9007199254740991,
string (up to 2,048 characters), or up to 100 unique strings. Use at most 64 keys,
matching `[a-z][a-z0-9_]{0,63}`. Nested maps are not supported. Identity, content,
revision and exporter metadata keys are reserved. Use consistent types; ISO dates
are strings. Distinguish unknown/null, confirmed absence and missing observations.

Use `provider`, `provider_account`, `provider_id`, `exact_name`, `jurisdiction`,
`accountable_owner`, `backup_owner`, `lifecycle_status`, `provider_status`,
`provider_observed_at`, `consumer_verification`, and `next_review` as applicable.
Credential metadata may include `permission_groups`, `scope`, `expires_at`,
`expiry_observation` and `secret_reference`. Never include secret values: every
admitted wiki user shares access. A secret reference describes protected storage;
it does not authorize retrieving or executing its contents.

Relationship keys `deployment_profiles`, `applications`, `resources`, `credentials`,
`consumers`, `replaces`, `replaced_by` contain arrays of actual queried page IDs.
Targets must be published and unarchived in the resulting publication. Create
a matching page_links record for every relationship target, as for body wiki links.

Create ordinary citations, then map property names to their marker strings in
`property_evidence`, such as `{"provider_status":["1"]}`. Each mapping must name
an existing property; lists contain at most 32 unique markers. A citation may
support properties without also appearing in the body. Evidence is optional but
missing evidence is not verification. Date provider observations and human
assessments separately and review whether each cited passage supports its claim.
Keep caveats, unresolved contradictions and explanations in the Markdown body.

Query properties through a pinned publication manifest, never by selecting the
latest revision timestamp. Catalog filters search structured values separately
from full-text title/summary/body search. Export generates Obsidian properties
and relationship links; edit via new WikiContext revisions, not the generated vault.
