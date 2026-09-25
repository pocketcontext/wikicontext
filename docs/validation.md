# Local validation

Validated against PocketContext `381f81042586afdaa6498b8c0e2a78229a55bdff`, built with the installed Go 1.27.1 toolchain and CGO. All 17 commands in README passed using synthetic isolated data. The portable skill validator also passed.

Coverage includes shared default-user identity; synthetic Google JIT claims and PKCE; disabled-account SQL/REST/realtime/protected-file revocation; source hashes, immutable originals and concurrent deduplication; interrupted extraction; citation and graph validation; publication conflict detection and transactional rollback; copied-out portable client; deterministic export, pinned history, original retrieval, local edit/collision/path checks and crash recovery; complete populated database/original snapshot restore; deployment configuration and disabled fixed-target wrappers.

Docker is unavailable in this environment. Container build/config/smoke/restore workflows are prepared but have not run. No immutable image digest exists. Real Google browser login, live Groq transcription, external deployment and existing-wiki migration have not been performed. No real records or credentials were used in tests.
