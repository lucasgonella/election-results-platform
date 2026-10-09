#!/usr/bin/env bash
# Opt-in entrypoint. No source/eval of credential files; systemd supplies env.
set -Eeuo pipefail
APP_DIR="${ELECTION_APP_DIR:-/opt/election-results-platform}"
PYTHON_BIN="${ELECTION_VENV_DIR:-${APP_DIR}/.venv}/bin/python"
cd "${APP_DIR}"
export PYTHONDONTWRITEBYTECODE=1
exec "${PYTHON_BIN}" -B -m collector.src.ftp_live_runner
