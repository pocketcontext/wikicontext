#!/bin/sh
# Container entrypoint. tini is PID 1 and runs this script, which always ends in exec:
#   tini -> litestream replicate -> entrypoint.sh serve -> pocketcontext serve
# or, with LITESTREAM_DISABLED=true:
#   tini -> pocketcontext serve
# SIGTERM from `docker stop` reaches Litestream, which forwards it to the server, waits for it
# to exit, and then makes a final sync. This script never prints variable values.
set -eu

APP_DIR=/app
DATA_DIR=/storage/pb_data
DB_PATH="$DATA_DIR/data.db"
LITESTREAM_CONFIG_FILE=/etc/litestream.yml
SERVER=/usr/local/bin/pocketcontext
SELF=/usr/local/bin/entrypoint.sh

log() {
	printf 'entrypoint: %s\n' "$*"
}

die() {
	printf 'entrypoint: error: %s\n' "$*" >&2
	exit 1
}

# The flags shared by `serve` and `superuser upsert`.
app_flags() {
	printf '%s\n' \
		"--dir=$DATA_DIR" \
		"--migrationsDir=$APP_DIR/pb_migrations" \
		"--hooksDir=$APP_DIR/pb_hooks" \
		"--contextConfig=$APP_DIR/pocketcontext.json"
}

serve() {
    if [ -n "${WIKICONTEXT_S3_BUCKET:-}" ] && [ "${LITESTREAM_DISABLED:-}" != true ]; then
        # Litestream 0.5.17 initializes the DB lazily on its first monitor tick.
        # An earlier shutdown skips final sync. Force this supervisor's database
        # initialization and remote baseline before the application can accept writes.
        if ! litestream sync -wait -timeout 60 -socket /run/litestream.sock "$DB_PATH" >/dev/null 2>&1; then
            die "initial replica synchronization failed; refusing to serve"
        fi
        log "initial replica synchronization complete"
    fi
	# The server needs neither the replica credentials nor the superuser password.
	# Litestream copies its credentials into AWS_* for its own use; drop those as well.
	unset LITESTREAM_ACCESS_KEY_ID LITESTREAM_SECRET_ACCESS_KEY \
		AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY WIKICONTEXT_SUPERUSER_PASSWORD
	# shellcheck disable=SC2046 # app_flags prints one flag per line and no value contains whitespace
	set -- serve --http=0.0.0.0:80 $(app_flags)
	if [ -z "${BASE_URL:-}" ]; then
		log "warning: BASE_URL is not set; email links point to localhost and browser origins are unrestricted. Set BASE_URL to the public application origin."
	fi
	# The dashboard is same-origin; there is no public intake endpoint.
	origins=${BASE_URL:-}
	origins=${origins%/}
	if [ -n "$origins" ]; then
		set -- "$@" "--origins=$origins"
	fi
	log "starting server on port 80"
	exec "$SERVER" "$@"
}

# Validate before restore, provisioning, or the Litestream child starts the server.
if [ -n "${WIKICONTEXT_GOOGLE_CLIENT_ID:-}" ] && [ -z "${WIKICONTEXT_GOOGLE_CLIENT_SECRET:-}" ]; then
	die "WIKICONTEXT_GOOGLE_CLIENT_ID requires WIKICONTEXT_GOOGLE_CLIENT_SECRET"
elif [ -n "${WIKICONTEXT_GOOGLE_CLIENT_SECRET:-}" ] && [ -z "${WIKICONTEXT_GOOGLE_CLIENT_ID:-}" ]; then
	die "WIKICONTEXT_GOOGLE_CLIENT_SECRET requires WIKICONTEXT_GOOGLE_CLIENT_ID"
fi

# Check the complete S3 contract before touching replication state.
s3_any="${WIKICONTEXT_S3_BUCKET:-}${WIKICONTEXT_S3_ENDPOINT:-}${WIKICONTEXT_S3_REGION:-}${WIKICONTEXT_S3_ACCESS_KEY_ID:-}${WIKICONTEXT_S3_SECRET_ACCESS_KEY:-}"
if [ -n "$s3_any" ]; then
    for name in WIKICONTEXT_S3_BUCKET WIKICONTEXT_S3_ENDPOINT WIKICONTEXT_S3_REGION WIKICONTEXT_S3_ACCESS_KEY_ID WIKICONTEXT_S3_SECRET_ACCESS_KEY; do
        eval "value=\${$name:-}"
        [ -n "$value" ] || die "incomplete object storage configuration"
    done
    case "${WIKICONTEXT_S3_FORCE_PATH_STYLE:-true}" in true|false) ;; *) die "invalid object storage path style" ;; esac
fi
s3_any= value=

if [ "${1:-}" = serve ]; then
	serve
fi

cd "$APP_DIR"
mkdir -p "$DATA_DIR"

# Read only the shared maintenance contract, never application settings or secrets.
# Malformed state stops startup rather than accidentally reopening a frozen app.
if ! frozen=$(python3 - "$DATA_DIR/maintenance.json" <<'PY'
import json
import os
from pathlib import Path
import stat
import sys

path = Path(sys.argv[1])
try:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        info = None
    if info is None:
        print('false')
    else:
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 4096:
            raise ValueError('maintenance state must be a private regular file')
        state = json.loads(path.read_text())
        if (not isinstance(state, dict) or set(state) != {'readOnly', 'generation'}
                or type(state.get('readOnly')) is not bool
                or type(state.get('generation')) is not int
                or not 0 <= state['generation'] <= 18446744073709551615):
            raise ValueError('invalid maintenance state')
        print('true' if state['readOnly'] else 'false')
except Exception:
    sys.exit(1)
PY
); then
	die "invalid maintenance state; startup stopped"
fi
if [ "$frozen" = true ]; then
	[ -f "$DB_PATH" ] || die "frozen startup requires the existing database"
	log "read-only maintenance state: preserving the existing database and credentials"
fi

replicate=true
if [ "${LITESTREAM_DISABLED:-}" = true ]; then
	replicate=false
	log "LITESTREAM_DISABLED=true: running without replication"
else
	missing=
	for name in LITESTREAM_BUCKET LITESTREAM_PATH LITESTREAM_ACCESS_KEY_ID LITESTREAM_SECRET_ACCESS_KEY; do
		eval "value=\${$name:-}"
		if [ -z "$value" ]; then
			missing="$missing $name"
		fi
	done
	value=
	if [ -n "$missing" ]; then
		die "missing environment variable(s):$missing. Set them, or set LITESTREAM_DISABLED to exactly 'true' to run without replication."
	fi
	: "${LITESTREAM_REGION:=}" "${LITESTREAM_ENDPOINT:=}" "${LITESTREAM_SYNC_INTERVAL:=10s}"
	export LITESTREAM_REGION LITESTREAM_ENDPOINT LITESTREAM_SYNC_INTERVAL
fi

if [ "$replicate" = true ] && [ "$frozen" != true ]; then
	if [ -z "${WIKICONTEXT_S3_BUCKET:-}" ]; then
		python3 /usr/local/bin/wikicontext-backup.py restore || die "complete evidence restore failed"
	fi
	if [ -f "$DB_PATH" ]; then
		log "database exists in the volume: no restore"
	else
		log "no database in the volume: restoring from the replica when one exists"
	fi
	# Exit status 0: restored, or the database already exists, or the replica holds no backup.
	# Anything else (unreachable bucket, rejected credentials, damaged backup) stops the container,
	# so the server never starts on an empty database while a replica may exist.
	if ! litestream restore -config "$LITESTREAM_CONFIG_FILE" \
		-if-db-not-exists -if-replica-exists -integrity-check quick "$DB_PATH"; then
		die "litestream restore failed. Not starting, because starting on an empty database would replace the replica's history. Check the LITESTREAM_* variables and the bucket."
	fi
	if [ -f "$DB_PATH" ]; then
		log "database present after the restore step"
	else
		log "the replica holds no backup: the server creates a new database"
	fi
fi

python3 /usr/local/bin/wikicontext-backup.py verify || die "evidence verification failed"

if [ "$frozen" = true ]; then
	log "read-only maintenance state: skipping superuser provisioning"
elif [ -n "${WIKICONTEXT_SUPERUSER_EMAIL:-}" ] && [ -n "${WIKICONTEXT_SUPERUSER_PASSWORD:-}" ]; then
	log "upserting the superuser from WIKICONTEXT_SUPERUSER_EMAIL"
	# shellcheck disable=SC2046 # see serve
	if ! "$SERVER" superuser upsert $(app_flags) -- "$WIKICONTEXT_SUPERUSER_EMAIL" "$WIKICONTEXT_SUPERUSER_PASSWORD"; then
		die "superuser upsert failed"
	fi
elif [ -n "${WIKICONTEXT_SUPERUSER_EMAIL:-}" ]; then
	die "WIKICONTEXT_SUPERUSER_EMAIL is set but WIKICONTEXT_SUPERUSER_PASSWORD is missing"
elif [ -n "${WIKICONTEXT_SUPERUSER_PASSWORD:-}" ]; then
	die "WIKICONTEXT_SUPERUSER_PASSWORD is set but WIKICONTEXT_SUPERUSER_EMAIL is missing"
fi

if [ "$replicate" = true ]; then
    # Google-only deployments need a database before the IPC startup sync too.
    if [ -n "${WIKICONTEXT_S3_BUCKET:-}" ] && [ ! -f "$DB_PATH" ]; then
        # shellcheck disable=SC2046
        "$SERVER" migrate up $(app_flags) || die "initial database migration failed"
    fi
	log "starting Litestream, which starts and supervises the server"
	if [ -n "${WIKICONTEXT_S3_BUCKET:-}" ]; then
		exec litestream replicate -config "$LITESTREAM_CONFIG_FILE" -exec "$SELF serve"
	fi
	exec python3 /usr/local/bin/wikicontext-backup.py supervise litestream replicate -config "$LITESTREAM_CONFIG_FILE" -exec "$SELF serve"
fi
serve
