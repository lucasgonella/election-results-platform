#!/usr/bin/env bash
# Called by run-live-publisher.sh only after a successful prepare.
set -Eeuo pipefail
APP_DIR="${ELECTION_APP_DIR:-/opt/election-results-platform}"
STATE_DIR="${LIVE_PUBLISH_STATE_DIR:-/var/lib/election-results-platform/live}"
PYTHON="${ELECTION_VENV_DIR:-$APP_DIR/.venv}/bin/python"
test -f "$STATE_DIR/stage/version.json"
exec "$PYTHON" "$APP_DIR/deploy/scripts/publish-live-results-https.py" \
  --stage "$STATE_DIR/stage" --send --publish-official
