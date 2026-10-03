#!/usr/bin/env bash

set -Eeuo pipefail

APP_DIR="${ELECTION_APP_DIR:-/opt/election-results-platform}"
VENV_DIR="${ELECTION_VENV_DIR:-${APP_DIR}/.venv}"
PYTHON_BIN="${VENV_DIR}/bin/python"

STATE_DIR="${PUBLISH_STATE_DIR:-/var/lib/election-results-platform}"
LOCAL_DATA_DIR="${PUBLISH_DATA_DIR:-${STATE_DIR}/public/data}"

ENVIRONMENT="${TSE_ENVIRONMENT:-simulado2026}"
EXPECTED_TARGETS="${PUBLISH_EXPECTED_TARGETS:-137}"
EXPECTED_FILES=$((EXPECTED_TARGETS + 1))

SSH_KEY="${PUBLISH_SSH_KEY:-${STATE_DIR}/.ssh/locaweb_publisher}"
KNOWN_HOSTS="${PUBLISH_KNOWN_HOSTS:-${STATE_DIR}/.ssh/known_hosts}"

REMOTE_HOST="${PUBLISH_REMOTE_HOST:?PUBLISH_REMOTE_HOST is required}"
REMOTE_USER="${PUBLISH_REMOTE_USER:?PUBLISH_REMOTE_USER is required}"
REMOTE_DIR="${PUBLISH_REMOTE_DIR:?PUBLISH_REMOTE_DIR is required}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "Python not found: ${PYTHON_BIN}" >&2
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

if [[ ! "${EXPECTED_TARGETS}" =~ ^[1-9][0-9]*$ ]]; then
    echo "Invalid PUBLISH_EXPECTED_TARGETS: ${EXPECTED_TARGETS}" >&2
    exit 2
fi

mkdir -p "$(dirname "${LOCAL_DATA_DIR}")"

BUILD_DIR="${LOCAL_DATA_DIR}.new"
OLD_DIR="${LOCAL_DATA_DIR}.old"

rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

cleanup() {
    rm -rf "${BUILD_DIR}"
}

trap cleanup EXIT

cd "${APP_DIR}"

echo "=== BUILD STATIC DATA ==="

"${PYTHON_BIN}" \
    -m collector.src.static_site_builder \
    --environment "${ENVIRONMENT}" \
    --output-dir "${BUILD_DIR}"

echo
echo "=== VALIDATE LOCAL BUNDLE ==="

"${PYTHON_BIN}" - \
    "${BUILD_DIR}" \
    "${ENVIRONMENT}" \
    "${EXPECTED_TARGETS}" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
expected_environment = sys.argv[2]
expected_targets = int(sys.argv[3])

manifest_path = root / "manifest.json"

if not manifest_path.is_file():
    raise SystemExit(
        "ERROR: manifest.json not found."
    )

manifest = json.loads(
    manifest_path.read_text(
        encoding="utf-8"
    )
)

if (
    manifest["environment"]
    != expected_environment
):
    raise SystemExit(
        "ERROR: unexpected environment."
    )

if (
    manifest["result_count"]
    != expected_targets
):
    raise SystemExit(
        "ERROR: expected "
        f"{expected_targets} targets, "
        f"got {manifest['result_count']}."
    )

json_files = list(
    root.rglob("*.json")
)

expected_files = (
    expected_targets + 1
)

if len(json_files) != expected_files:
    raise SystemExit(
        "ERROR: expected "
        f"{expected_files} JSON files, "
        f"got {len(json_files)}."
    )

for item in manifest["results"]:
    path = root / item["path"]

    if not path.is_file():
        raise SystemExit(
            "ERROR: missing result file: "
            f"{item['path']}"
        )

print(
    "targets:",
    manifest["result_count"],
)
print(
    "candidates:",
    manifest["candidate_count"],
)
print(
    "json_files:",
    len(json_files),
)
print("LOCAL BUNDLE: OK")
PY

SSH_OPTIONS=(
    -i "${SSH_KEY}"
    -o IdentitiesOnly=yes
    -o HostKeyAlgorithms=+ssh-rsa
    -o PubkeyAcceptedAlgorithms=+ssh-rsa
    -o UserKnownHostsFile="${KNOWN_HOSTS}"
    -o StrictHostKeyChecking=yes
    -o ConnectTimeout=10
    -o ServerAliveInterval=15
)

REMOTE="${REMOTE_USER}@${REMOTE_HOST}"
REMOTE_STAGE="${REMOTE_DIR}.new"

echo
echo "=== PREPARE REMOTE STAGE ==="

ssh \
    "${SSH_OPTIONS[@]}" \
    "${REMOTE}" \
    "rm -rf '${REMOTE_STAGE}' && mkdir -p '${REMOTE_STAGE}'"

echo
echo "=== UPLOAD BUNDLE ==="

tar \
    -C "${BUILD_DIR}" \
    -czf - \
    . \
| ssh \
    "${SSH_OPTIONS[@]}" \
    "${REMOTE}" \
    "tar -xzf - -C '${REMOTE_STAGE}'"

echo
echo "=== VALIDATE AND ACTIVATE REMOTE BUNDLE ==="

ssh \
    "${SSH_OPTIONS[@]}" \
    "${REMOTE}" \
    bash -s -- \
    "${REMOTE_DIR}" \
    "${REMOTE_STAGE}" \
    "${EXPECTED_FILES}" <<'REMOTE'
set -eu

remote_dir="$1"
stage_dir="$2"
expected_files="$3"
old_dir="${remote_dir}.old"

if [ ! -s "${stage_dir}/manifest.json" ]; then
    echo "Remote manifest missing." >&2
    exit 1
fi

actual_files="$(
    find "${stage_dir}" \
        -type f \
        -name '*.json' \
    | wc -l \
    | tr -d ' '
)"

if [ "${actual_files}" != "${expected_files}" ]; then
    echo \
        "Remote validation failed: expected ${expected_files}, got ${actual_files}." \
        >&2

    exit 1
fi

rm -rf "${old_dir}"

if [ -d "${remote_dir}" ]; then
    mv "${remote_dir}" "${old_dir}"
fi

if mv "${stage_dir}" "${remote_dir}"; then
    rm -rf "${old_dir}"
else
    echo "Remote activation failed." >&2

    if [ -d "${old_dir}" ]; then
        mv "${old_dir}" "${remote_dir}"
    fi

    exit 1
fi

echo "REMOTE BUNDLE: OK"
REMOTE

echo
echo "=== ACTIVATE LOCAL BUNDLE ==="

rm -rf "${OLD_DIR}"

if [[ -d "${LOCAL_DATA_DIR}" ]]; then
    mv \
        "${LOCAL_DATA_DIR}" \
        "${OLD_DIR}"
fi

mv \
    "${BUILD_DIR}" \
    "${LOCAL_DATA_DIR}"

rm -rf "${OLD_DIR}"

trap - EXIT

echo
echo "STATIC PUBLISH: OK"
echo "Environment: ${ENVIRONMENT}"
echo "Targets: ${EXPECTED_TARGETS}"