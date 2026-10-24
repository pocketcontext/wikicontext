# Private WikiContext migration rehearsal

For the completed **local, synthetic Basecamp ONCE test**, use
[LOCAL_ONCE.md](LOCAL_ONCE.md). It runs an isolated Docker-in-Docker engine with
loopback-only outer ports and exercises actual ONCE restore, backup, stop-first
update, rollback, and repeat migration. The recorded result is in
[the local rehearsal receipt](../../docs/local-once-rehearsal.md).

These are preparation tools, not a record of a cloud deployment or production-data
copy. [The recovery assessment](../../docs/predeployment-recovery.md) defines the
checkpoint, original-file and old-image requirements.

A shared-host loopback mode for the former `pocketdeploy-v1` demo host was
removed after that host was retired on 24 October 2026; it was never run there.

## Fresh-host configuration

`prepare_config.py spec.json NEW_DIRECTORY` generates non-secret JSON-compatible
YAML phases using the current PocketDeploy schema: empty `host.yml`, old-image
`restored.yml`, candidate `candidate.yml`, and an initially empty `colors.yml`.
It refuses existing directories, broad SSH CIDRs, non-loopback clone names, mutable
images and reused source profiles. Its deadline must be within seven days; cost
ceiling/deadline are recorded scope, not provider billing or automatic cleanup.

Fill `spec.example.json` with the approved provider/network identifiers, machine
and disk bounds, operator /32 addresses, source identity, digests, deadline and
cost ceiling. GCP fields are shown; OCI and DigitalOcean exact field sets are
listed in `prepare_config.py` and PocketDeploy's provider reference. No cloud
credential is accepted in the specification. All nine generated provider/phase
combinations were checked against PocketDeploy's current schema without resolving
bindings or contacting providers.

These files are **only for a new dedicated host**, never an existing deployment
profile: converging an empty application list there would remove managed
applications. On a dedicated host, no HTTP ingress is allowed; ONCE's local
HTTP health probe works with `disable_tls`, `manage-dns:false`, no SMTP and no
GitHub delivery. After a separately verified ONCE restore bootstrap, adoption must
use the running old image, all exact named-volume destinations, its safe settings
fingerprint and disabled previous delivery. Then activate the candidate phase and
use stop-first convergence. These templates do not supply that ONCE bootstrap and
are not evidence that adoption has been rehearsed.

## Validation performed

```sh
python3 -B -m unittest discover -s deploy/rehearsal/tests
python3 deploy/rehearsal/isolation_test.py --image LOCAL_WIKICONTEXT_TEST_IMAGE
```

The first command uses synthetic mocked operations and checks configuration
generation, local ONCE lifecycle boundaries and prepared-clone verification. The
second uses temporary local Docker networks/container/volume with synthetic HTTP
content and verifies loopback publication plus denial from another application
bridge; it does not invoke cloud APIs. It passed with the final locally built
WikiContext image.
