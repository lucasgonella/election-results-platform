#!/usr/bin/env bash

set -Eeuo pipefail

APP_DIR="${ELECTION_APP_DIR:-/opt/election-results-platform}"
VENV_DIR="${ELECTION_VENV_DIR:-${APP_DIR}/.venv}"

PYTHON_BIN="${VENV_DIR}/bin/python"

BATCH_SIZE="${COLLECTOR_BATCH_SIZE:-10}"
WORKERS="${COLLECTOR_WORKERS:-1}"
CYCLES="${COLLECTOR_CYCLES:-1}"

PUBLISH_AFTER_COLLECT="${PUBLISH_AFTER_COLLECT:-false}"

PUBLISH_SCRIPT="${PUBLISH_SCRIPT:-${APP_DIR}/deploy/scripts/publish-results.sh}"

PUBLISH_STATE_DIR="${PUBLISH_STATE_DIR:-/var/lib/election-results-platform}"

PUBLISH_PENDING_FILE="${PUBLISH_PENDING_FILE:-${PUBLISH_STATE_DIR}/runtime/publish.pending}"


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

if [[ ! "${WORKERS}" =~ ^[1-9][0-9]*$ ]]; then
    echo "Invalid COLLECTOR_WORKERS: ${WORKERS}" >&2
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
    --workers
    "${WORKERS}"
    --cycles
    "${CYCLES}"
)


case "${COLLECTOR_ALLOW_OFFICIAL:-false}" in
    1|true|TRUE|yes|YES)
        ARGS+=(--allow-official)
        ;;
esac


RESULT_FILE="$(mktemp)"

cleanup() {
    rm -f "${RESULT_FILE}"
}

trap cleanup EXIT


set +e

"${PYTHON_BIN}" \
    "${ARGS[@]}" \
    > "${RESULT_FILE}"

COLLECTOR_EXIT=$?

set -e


cat "${RESULT_FILE}"


if [[ "${COLLECTOR_EXIT}" -ne 0 ]]; then
    echo >&2
    echo "Collector failed. Publish skipped." >&2
    exit "${COLLECTOR_EXIT}"
fi


DECISION="$(
    "${PYTHON_BIN}" \
        - \
        "${RESULT_FILE}" <<'PY'
import json
import sys
from pathlib import Path


path = Path(sys.argv[1])

result = json.loads(
    path.read_text(
        encoding="utf-8"
    )
)

after = result["after"]

safe = (
    after["pending_items"] == 0
    and after["error_items"] == 0
    and after["health"] == "ok"
)

data_update_completed = (
    result.get(
        "data_updates_committed",
        0,
    )
    > 0
)

publish_ready = (
    safe
    and data_update_completed
)

print(
    int(publish_ready),
    int(safe),
)
PY
)"


read -r \
    PUBLISH_READY \
    PUBLISH_SAFE \
    <<< "${DECISION}"


case "${PUBLISH_AFTER_COLLECT}" in

    1|true|TRUE|yes|YES)

        mkdir -p \
            "$(dirname "${PUBLISH_PENDING_FILE}")"

        if [[ "${PUBLISH_READY}" == "1" ]]; then

            {
                echo "queued_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
                echo "reason=collector_checkpoint_completed"
            } > "${PUBLISH_PENDING_FILE}"

            echo
            echo "Publish marker: QUEUED"
        fi


        if [[ -f "${PUBLISH_PENDING_FILE}" ]]; then

            if [[ "${PUBLISH_SAFE}" != "1" ]]; then
                echo
                echo "Publish deferred: collector still has pending/error work."
                exit 0
            fi


            if [[ ! -x "${PUBLISH_SCRIPT}" ]]; then
                echo \
                    "Publisher is not executable: ${PUBLISH_SCRIPT}" \
                    >&2

                exit 2
            fi


            echo
            echo "=== PUBLISH STATIC RESULTS ==="


            if "${PUBLISH_SCRIPT}"; then

                rm -f \
                    "${PUBLISH_PENDING_FILE}"

                echo
                echo "Publish marker: CLEARED"

            else

                echo >&2
                echo \
                    "Static publish failed. Retry marker retained." \
                    >&2

                exit 1
            fi

        else

            echo
            echo "Static publish: no pending changes."

        fi
        ;;


    *)

        echo
        echo "Automatic static publish: disabled."
        ;;

esac