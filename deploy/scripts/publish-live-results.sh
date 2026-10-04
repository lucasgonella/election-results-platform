#!/usr/bin/env bash

set -Eeuo pipefail

APP_DIR="${ELECTION_APP_DIR:-/opt/election-results-platform}"

STATE_DIR="${LIVE_PUBLISH_STATE_DIR:-/var/lib/election-results-platform/live}"
STAGE_DIR="${LIVE_PUBLISH_STAGE_DIR:-${STATE_DIR}/stage}"

EXPECTED_TARGETS="${LIVE_PUBLISH_EXPECTED_TARGETS:-${PUBLISH_EXPECTED_TARGETS:-137}}"

SSH_RETRIES="${LIVE_PUBLISH_SSH_RETRIES:-3}"
SSH_RETRY_DELAY="${LIVE_PUBLISH_SSH_RETRY_DELAY:-2}"

SSH_KEY="${PUBLISH_SSH_KEY:-/var/lib/election-results-platform/.ssh/locaweb_publisher}"
KNOWN_HOSTS="${PUBLISH_KNOWN_HOSTS:-/var/lib/election-results-platform/.ssh/known_hosts}"

REMOTE_HOST="${PUBLISH_REMOTE_HOST:?PUBLISH_REMOTE_HOST is required}"
REMOTE_USER="${PUBLISH_REMOTE_USER:?PUBLISH_REMOTE_USER is required}"
REMOTE_DIR="${PUBLISH_REMOTE_DIR:?PUBLISH_REMOTE_DIR is required}"

if [[ ! -d "${STAGE_DIR}" ]]; then
    echo "Live stage directory not found: ${STAGE_DIR}" >&2
    exit 2
fi

if [[ ! -s "${STAGE_DIR}/manifest.json" ]]; then
    echo "Live manifest not found." >&2
    exit 2
fi

if [[ ! -s "${STAGE_DIR}/version.json" ]]; then
    echo "Live version file not found." >&2
    exit 2
fi

if [[ ! -s "${STAGE_DIR}/alerts.json" ]]; then
    echo "Live alerts file not found." >&2
    exit 2
fi

if [[ ! -f "${SSH_KEY}" ]]; then
    echo "SSH key not found: ${SSH_KEY}" >&2
    exit 2
fi

if [[ ! -s "${KNOWN_HOSTS}" ]]; then
    echo "known_hosts not found or empty: ${KNOWN_HOSTS}" >&2
    exit 2
fi

PYTHON_BIN="${APP_DIR}/.venv/bin/python"

"${PYTHON_BIN}" - "${STAGE_DIR}" "${EXPECTED_TARGETS}" <<'PY'
import json
import sys
from pathlib import Path

stage = Path(sys.argv[1])
expected_targets = int(sys.argv[2])

manifest = json.loads(
    (stage / "manifest.json").read_text(
        encoding="utf-8"
    )
)

version = json.loads(
    (stage / "version.json").read_text(
        encoding="utf-8"
    )
)

alerts = json.loads(
    (stage / "alerts.json").read_text(
        encoding="utf-8"
    )
)

if manifest.get("result_count") != expected_targets:
    raise SystemExit(
        "ERROR: live manifest target count mismatch."
    )

if (
    manifest.get("generated_at")
    != version.get("generated_at")
):
    raise SystemExit(
        "ERROR: live version mismatch."
    )

if (
    alerts.get("generated_at")
    != version.get("generated_at")
):
    raise SystemExit(
        "ERROR: live alerts version mismatch."
    )

changed = [
    path
    for path in stage.rglob("*.json")
    if path.name
    not in {
        "manifest.json",
        "version.json",
        "alerts.json",
    }
]

if not changed:
    raise SystemExit(
        "ERROR: live stage has no changed targets."
    )

manifest_paths = {
    item["path"]
    for item in manifest["results"]
}

for path in changed:
    relative = path.relative_to(
        stage
    ).as_posix()

    if relative not in manifest_paths:
        raise SystemExit(
            "ERROR: staged target missing from manifest: "
            + relative
        )

print("changed_targets:", len(changed))
print("LIVE LOCAL STAGE: OK")
PY

SSH_OPTIONS=(
    -i "${SSH_KEY}"
    -o IdentitiesOnly=yes
    -o HostKeyAlgorithms=+ssh-rsa
    -o PubkeyAcceptedAlgorithms=+ssh-rsa
    -o UserKnownHostsFile="${KNOWN_HOSTS}"
    -o StrictHostKeyChecking=yes
    -o ConnectTimeout=5
    -o ServerAliveInterval=15
)

REMOTE="${REMOTE_USER}@${REMOTE_HOST}"
REMOTE_STAGE="${REMOTE_DIR}.live-new"

retry_operation() {
    local description="$1"
    shift

    local attempt=1
    local status=0

    while true; do
        if "$@"; then
            return 0
        else
            status=$?
        fi

        if (( attempt >= SSH_RETRIES )); then
            echo "${description} failed after ${attempt} attempts." >&2
            return "${status}"
        fi

        echo "${description} failed (attempt ${attempt}/${SSH_RETRIES}). Retrying in ${SSH_RETRY_DELAY}s..." >&2
        sleep "${SSH_RETRY_DELAY}"
        attempt=$((attempt + 1))
    done
}

prepare_remote_stage() {
    ssh         "${SSH_OPTIONS[@]}"         "${REMOTE}"         "rm -rf '${REMOTE_STAGE}' && mkdir -p '${REMOTE_STAGE}'"
}

upload_live_delta() {
    tar         -C "${STAGE_DIR}"         -czf -         .     | ssh         "${SSH_OPTIONS[@]}"         "${REMOTE}"         "tar -xzf - -C '${REMOTE_STAGE}'"
}

activate_live_delta() {
    ssh         "${SSH_OPTIONS[@]}"         "${REMOTE}"         sh -s --         "${REMOTE_DIR}"         "${REMOTE_STAGE}" <<'REMOTE'
set -eu

remote_dir="$1"
stage_dir="$2"

if [ ! -s "${stage_dir}/manifest.json" ]; then
    echo "Live remote manifest missing." >&2
    exit 1
fi

if [ ! -s "${stage_dir}/version.json" ]; then
    echo "Live remote version missing." >&2
    exit 1
fi

if [ ! -s "${stage_dir}/alerts.json" ]; then
    echo "Live remote alerts missing." >&2
    exit 1
fi

mkdir -p "${remote_dir}"

find "${stage_dir}"     -type f     -name '*.json'     ! -path "${stage_dir}/manifest.json"     ! -path "${stage_dir}/version.json" | while IFS= read -r source
do
    relative="${source#"${stage_dir}/"}"
    destination="${remote_dir}/${relative}"

    mkdir -p "$(dirname "${destination}")"

    cp         "${source}"         "${destination}"
done

cp     "${stage_dir}/manifest.json"     "${remote_dir}/manifest.json"

cp     "${stage_dir}/version.json"     "${remote_dir}/version.json"

rm -rf "${stage_dir}"

echo "LIVE REMOTE DELTA: OK"
REMOTE
}

echo
echo "=== PREPARE LIVE REMOTE STAGE ==="

retry_operation     "Prepare live remote stage"     prepare_remote_stage

echo
echo "=== UPLOAD LIVE DELTA ==="

retry_operation     "Upload live delta"     upload_live_delta

echo
echo "=== ACTIVATE LIVE DELTA ==="

retry_operation     "Activate live delta"     activate_live_delta

echo
echo "LIVE STATIC PUBLISH: OK"
