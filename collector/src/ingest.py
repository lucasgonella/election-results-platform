from __future__ import annotations

import json

from .parser import parse_ea20
from .repository import (
    get_last_fetch_state,
    persist_result,
    record_not_modified,
)
from .tse_client import TseClient


SIMULATOR_URL = (
    "https://resultados-sim.tse.jus.br/"
    "simulado/simulado2026/"
    "ele2026/21272/dados/ac/"
    "ac-c0003-e021272-u.json"
)


def main() -> None:
    client = TseClient()

    cached_state = get_last_fetch_state(
        SIMULATOR_URL
    )

    response = client.fetch_json(
        SIMULATOR_URL,
        etag=(
            cached_state.etag
            if cached_state
            else None
        ),
        last_modified=(
            cached_state.last_modified
            if cached_state
            else None
        ),
    )

    if response.status_code == 304:

        if cached_state is None:
            raise RuntimeError(
                "Received HTTP 304 without cached state."
            )

        collector_run_id = record_not_modified(
            response,
            cached_state,
        )

        print(
            json.dumps(
                {
                    "status": "not_modified",
                    "http_status": 304,
                    "collector_run_id":
                        collector_run_id,
                    "tse_idg":
                        cached_state.tse_idg,
                },
                indent=2,
            )
        )

        return

    if response.payload is None:
        raise RuntimeError(
            "TSE returned no payload."
        )

    parsed = parse_ea20(
        response.payload
    )

    persisted = persist_result(
        response,
        parsed,
        environment="simulado",
    )

    print(
        json.dumps(
            {
                "status": "success",
                "http_status":
                    response.status_code,
                "tse_idg":
                    parsed.tse_idg,
                "collector_run_id":
                    persisted.collector_run_id,
                "election_id":
                    persisted.election_id,
                "scope_id":
                    persisted.scope_id,
                "snapshots_created":
                    persisted.snapshots_created,
                "candidates_processed":
                    persisted.candidates_processed,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
