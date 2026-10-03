from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any

from .discovery import (
    ElectionDefinition,
    SUPPORTED_ELECTION_TYPES,
    parse_election_config,
)
from .tse_client import TseClient


DEFAULT_BASE_URL = (
    "https://resultados-sim.tse.jus.br/simulado"
)

DEFAULT_ENVIRONMENT = "simulado2026"
DEFAULT_CYCLE = "ele2026"
DEFAULT_ROUND = 1


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    base_url: str
    environment: str
    cycle: str
    round_number: int


def load_settings() -> RuntimeSettings:
    return RuntimeSettings(
        base_url=os.getenv(
            "TSE_BASE_URL",
            DEFAULT_BASE_URL,
        ).rstrip("/"),
        environment=os.getenv(
            "TSE_ENVIRONMENT",
            DEFAULT_ENVIRONMENT,
        ),
        cycle=os.getenv(
            "TSE_CYCLE",
            DEFAULT_CYCLE,
        ),
        round_number=int(
            os.getenv(
                "TSE_ROUND",
                str(DEFAULT_ROUND),
            )
        ),
    )


def build_config_url(
    settings: RuntimeSettings,
) -> str:
    return (
        f"{settings.base_url}/"
        f"{settings.environment}/"
        "comum/config/ele-c.json"
    )


def select_supported_elections(
    payload: dict[str, Any],
    settings: RuntimeSettings,
) -> tuple[ElectionDefinition, ...]:
    elections = parse_election_config(
        payload
    )

    selected = tuple(
        election
        for election in elections
        if (
            election.cycle == settings.cycle
            and election.round_number
            == settings.round_number
            and election.election_type
            in SUPPORTED_ELECTION_TYPES
        )
    )

    return selected


def main() -> None:
    settings = load_settings()

    client = TseClient()

    url = build_config_url(
        settings
    )

    response = client.fetch_json(
        url
    )

    if response.payload is None:
        raise RuntimeError(
            "TSE configuration returned no payload."
        )

    elections = select_supported_elections(
        response.payload,
        settings,
    )

    output = {
        "runtime": {
            "base_url": settings.base_url,
            "environment": settings.environment,
            "cycle": settings.cycle,
            "round": settings.round_number,
        },
        "config_url": url,
        "http_status": response.status_code,
        "config_idg": response.payload.get(
            "idg"
        ),
        "supported_elections": [
            {
                "code": election.election_code,
                "type": election.election_type,
                "round": election.round_number,
                "name": election.name,
                "offices": [
                    {
                        "code": office.code,
                        "name": office.name,
                    }
                    for office
                    in election.offices
                ],
            }
            for election in elections
        ],
    }

    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
