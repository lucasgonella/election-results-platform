from __future__ import annotations

import json

from .parser import parse_ea20
from .repository import persist_result
from .tse_client import TseClient


SIMULATOR_URL = (
    "https://resultados-sim.tse.jus.br/"
    "simulado/simulado2026/"
    "ele2026/21272/dados/ac/"
    "ac-c0003-e021272-u.json"
)


def main() -> None:
    client = TseClient()

    response = client.fetch_json(
        SIMULATOR_URL
    )

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
                "tse_idg": parsed.tse_idg,
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
