"""Read-only discovery gate for official 2026 second-round elections.

Does not write FTP, change TSE_ROUND, create candidate results, or enable collection.
Produces a machine-readable readiness report for operational release planning.
"""
from __future__ import annotations

import json

from .runtime import RuntimeSettings, build_config_url, select_supported_elections
from .tse_client import TseClient


SETTINGS = RuntimeSettings(
    base_url="https://resultados.tse.jus.br",
    environment="oficial",
    cycle="ele2026",
    round_number=2,
)


def evaluate(configuration):
    elections = select_supported_elections(configuration, SETTINGS)
    result = []
    for election in elections:
        offices = [{"code": office.code, "name": office.name}
                   for office in election.offices]
        # The second round is limited to majority offices.
        if any(office["code"] not in {1, 3} for office in offices):
            raise ValueError("second_round_unexpected_office")
        result.append({"code": election.election_code, "round": election.round_number,
                       "type": election.election_type, "name": election.name,
                       "offices": offices})
    return {"status": "official_round_two_detected" if result else "awaiting_official_round_two_configuration",
            "publication_enabled": False, "official_config_url": build_config_url(SETTINGS),
            "elections": result}


def main():
    response = TseClient().fetch_json(build_config_url(SETTINGS))
    if response.payload is None:
        raise RuntimeError("official_second_round_config_unavailable")
    print(json.dumps(evaluate(response.payload), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
