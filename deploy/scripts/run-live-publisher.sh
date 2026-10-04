#!/usr/bin/env bash

set -Eeuo pipefail

APP_DIR="${ELECTION_APP_DIR:-/opt/election-results-platform}"
VENV_DIR="${ELECTION_VENV_DIR:-${APP_DIR}/.venv}"
PYTHON_BIN="${VENV_DIR}/bin/python"

STATE_DIR="${LIVE_PUBLISH_STATE_DIR:-/var/lib/election-results-platform/live}"
STAGE_DIR="${LIVE_PUBLISH_STAGE_DIR:-${STATE_DIR}/stage}"

PUBLISH_SCRIPT="${LIVE_PUBLISH_SCRIPT:-${APP_DIR}/deploy/scripts/publish-live-results.sh}"

cd "${APP_DIR}"

echo "=== PREPARE LIVE UPDATE ==="

"${PYTHON_BIN}"     -m collector.src.live_publisher     prepare

if [[ -s "${STAGE_DIR}/version.json" ]]; then
    echo
    echo "=== PUBLISH LIVE UPDATE ==="

    /bin/bash         "${PUBLISH_SCRIPT}"
else
    echo
    echo "Live publish: no changed targets."
fi

echo
echo "=== COMMIT LIVE STATE ==="

"${PYTHON_BIN}"     -m collector.src.live_publisher     commit
