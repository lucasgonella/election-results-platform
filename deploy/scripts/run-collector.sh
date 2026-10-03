#!/usr/bin/env bash

set -Eeuo pipefail

APP_DIR="${ELECTION_APP_DIR:-/opt/election-results-platform}"
VENV_DIR="${ELECTION_VENV_DIR:-${APP_DIR}/.venv}"

PYTHON_BIN="${VENV_DIR}/bin/python"

BATCH_SIZE="${COLLECTOR_BATCH_SIZE:-10}"
CYCLES="${COLLECTOR_CYCLES:-1}"

if [[ ! -d "${APP_DIR}" ]]; then
    echo "Application directory does not exist: ${APP_DIR}" >&2
    exit 2
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "Python virtual environment not found: ${PYTHON_BIN}" >&2
    exit 2
fi

if [[ ! "${BATCH_SIZE}" =~ ^[1-9][0-9]*$ ]]; then
    echo "Invalid COLLECTOR_BATCH_SIZE: ${BATCH_SIZE}" >&2
    exit 2
fi

if [[ ! "${CYCLES}" =~ ^[1-9][0-9]*$ ]]; then
    echo "Invalid COLLECTOR_CYCLES: ${CYCLES}" >&2
    exit 2
fi

cd "${APP_DIR}"

ARGS=(
    -m
    collector.src.collector_runner
    --execute
    --batch-size
    "${BATCH_SIZE}"
    --cycles
    "${CYCLES}"
)

case "${COLLECTOR_ALLOW_OFFICIAL:-false}" in
    1|true|TRUE|yes|YES)
        ARGS+=(--allow-official)
        ;;
esac

exec "${PYTHON_BIN}" "${ARGS[@]}"
