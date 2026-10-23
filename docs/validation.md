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

## Background snapshots — 23 October 2026

The adopted server is `934a63a13c3fa97be5e5f0e0329b793375bc8f08`.

Local synthetic checks passed for publication integration, space privacy, account
authentication, realtime access/publications, private search and populated search
restore. The new background-copy test verifies complete available results, a
fresh read after a committed write, requester-bound minimum generations, exact
generation conflicts and immediate disabled-account denial. Copied-client skill
checks passed with and without tracing; both packaged schema snapshots were
regenerated from the candidate server. Search, background-copy and copied-client
checks passed again after the concurrent disk-reservation fix.

The Python client passed 19 unit tests. The reader passed type checking, 146 unit
tests, a production build and all 31 isolated Chromium scenarios, including
mobile/keyboard behavior, history, publication updates and access revocation while
reads are pending. Unit tests cover status polling without another publication
event, evidence refresh, generation fencing and distinct snapshot/result failures.
The final status-GET timeout change was typechecked, unit tested and rebuilt.
Deployment-workflow tests passed after adding the background-copy check to CI.
These checks made no production reads, deployments or transcription-provider calls.

The remaining README backend/client gates also passed: populated space migration,
tracing, publication review/home/properties, OAuth integration, knowledge,
ingestion/concurrency, export, deployment/maintenance, transcript bundle import,
timing review, and all listed client/unit/launcher checks. The space migration
fixture now explicitly requests fresh SQL for its immediate revocation assertions.
Both mocked Gemini pipelines passed the warning-enabled handoff and byte-exact
artifact recovery using the CI-pinned Gemini package in an isolated environment;
the host's optional `GEMINI_MODEL` override was unset for this two-model fixture.
Container image/recovery gates and a live Google browser sign-in were not run as
part of this source change.

PocketContext's complete Go race suite and build passed, along with DealContext's
integration, portable skill, deployment and intake regressions. After publishing
client commit `80236fda59b7b406390bd5b39a41e3e1d4246e65` on the feature branch,
the portable launcher was pinned to it and tested unchanged from an unrelated
directory, including the full skill workflow with and without tracing. The
launcher checks used the installed uv binary directly because the test's isolated
home cannot resolve this host's asdf shim. Production has not been changed.

Feature-branch CI passed the application suite on AMD64 and ARM64. Both container
recovery jobs exposed a stale read in the smoke harness after creating personal
space evidence. Its SQL and search verification now explicitly requests fresh
copies with a 130-second transport timeout. The deployment regression reproduces
the original failure and passes with this fix; all 10 deployment-workflow checks
also pass. Main's native container gates must pass before publication/deployment.
