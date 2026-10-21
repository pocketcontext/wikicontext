# Local validation

Validated against PocketContext `381f81042586afdaa6498b8c0e2a78229a55bdff`, built with the installed Go 1.27.1 toolchain and CGO. All 17 commands in README passed using synthetic isolated data. The portable skill validator also passed.

Coverage includes shared default-user identity; synthetic Google JIT claims and PKCE; disabled-account SQL/REST/realtime/protected-file revocation; source hashes, immutable originals and concurrent deduplication; interrupted extraction; citation and graph validation; publication conflict detection and transactional rollback; copied-out portable client; deterministic export, pinned history, original retrieval, local edit/collision/path checks and crash recovery; complete populated database/original snapshot restore; deployment configuration and fixed-target wrappers.

Docker is unavailable in the local development environment. Native AMD64/ARM64 CI subsequently passed container build/config/smoke/restore and the full application suite, and the image was deployed to ONCE. See [release verification](../DEPLOYMENT.md). Real Google browser login, live Groq transcription and existing-wiki migration have not been performed. Application tests used synthetic isolated records. The deployment recovery drill used the initially empty production snapshot only in disposable isolated storage.

## Browser-opening Google login — 21 October 2026

`login --google` opens the printed URL with the standard library browser module
unless `--no-browser` is given, `SSH_CONNECTION`/`SSH_TTY` is set or, outside macOS
and Windows, no graphical display is available. A failed open never fails login.
Unit tests mock the browser module. All README application, integration,
publication, ingestion, export, auth, realtime, OAuth integration, portable skill
(with and without tracing), deployment and maintenance commands passed against
server `20843b7c888daaba55f0646dd77455b7b309d4cc`, as did launcher, client (15),
OAuth (15), deployment-workflow (10) and the other unit suites. Gemini handoff,
browser UI and container checks were not rerun locally.
