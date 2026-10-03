from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from typing import Any

from .discovery import (
    ElectionTarget,
    generate_targets,
)
from .runtime import (
    RuntimeSettings,
    build_config_url,
    load_settings,
    select_supported_elections,
)
from .tse_client import TseClient


@dataclass(frozen=True, slots=True)
class ElectionCollectionPlan:
    election_code: int
    election_type: int | None
    cycle: str

    ea14_url: str
    ea14_idg: str | None

    targets: tuple[
        ElectionTarget,
        ...
    ]


def build_ea14_url(
    *,
    settings: RuntimeSettings,
    election_code: int,
    cycle: str | None = None,
) -> str:
    election_file = (
        f"{election_code:06d}"
    )

    selected_cycle = (
        cycle
        or settings.cycle
    )

    return (
        f"{settings.base_url}/"
        f"{settings.environment}/"
        f"{selected_cycle}/"
        f"{election_code}/"
        "dados/br/"
        f"br-e{election_file}-ab.json"
    )


def build_collection_plan(
    *,
    config_payload: dict[str, Any],
    ea14_payloads: dict[
        int,
        dict[str, Any],
    ],
    settings: RuntimeSettings,
) -> tuple[
    ElectionCollectionPlan,
    ...
]:
    elections = (
        select_supported_elections(
            config_payload,
            settings,
        )
    )

    plans: list[
        ElectionCollectionPlan
    ] = []

    for election in elections:
        ea14_payload = (
            ea14_payloads.get(
                election.election_code
            )
        )

        if ea14_payload is None:
            raise ValueError(
                "Missing EA14 payload for "
                f"election "
                f"{election.election_code}."
            )

        targets = generate_targets(
            config_payload=config_payload,
            ea14_payload=ea14_payload,
            base_url=settings.base_url,
            environment=(
                settings.environment
            ),
            election_codes=frozenset({
                election.election_code,
            }),
        )

        raw_idg = ea14_payload.get(
            "idg"
        )

        ea14_idg = (
            str(raw_idg)
            if raw_idg is not None
            else None
        )

        plans.append(
            ElectionCollectionPlan(
                election_code=(
                    election.election_code
                ),
                election_type=(
                    election.election_type
                ),
                cycle=election.cycle,
                ea14_url=build_ea14_url(
                    settings=settings,
                    election_code=(
                        election.election_code
                    ),
                    cycle=election.cycle,
                ),
                ea14_idg=ea14_idg,
                targets=targets,
            )
        )

    return tuple(plans)


def fetch_collection_plan(
    *,
    settings: (
        RuntimeSettings
        | None
    ) = None,
    client: TseClient | None = None,
) -> tuple[
    ElectionCollectionPlan,
    ...
]:
    selected_settings = (
        settings
        or load_settings()
    )

    selected_client = (
        client
        or TseClient()
    )

    config_response = (
        selected_client.fetch_json(
            build_config_url(
                selected_settings
            )
        )
    )

    if config_response.payload is None:
        raise RuntimeError(
            "TSE configuration "
            "returned no payload."
        )

    elections = (
        select_supported_elections(
            config_response.payload,
            selected_settings,
        )
    )

    ea14_payloads: dict[
        int,
        dict[str, Any],
    ] = {}

    for election in elections:
        ea14_url = build_ea14_url(
            settings=selected_settings,
            election_code=(
                election.election_code
            ),
            cycle=election.cycle,
        )

        response = (
            selected_client.fetch_json(
                ea14_url
            )
        )

        if response.payload is None:
            raise RuntimeError(
                "EA14 returned no payload "
                "for election "
                f"{election.election_code}."
            )

        ea14_payloads[
            election.election_code
        ] = response.payload

    return build_collection_plan(
        config_payload=(
            config_response.payload
        ),
        ea14_payloads=ea14_payloads,
        settings=selected_settings,
    )


def main() -> None:
    settings = load_settings()

    plans = fetch_collection_plan(
        settings=settings
    )

    total_targets = sum(
        len(plan.targets)
        for plan in plans
    )

    output = {
        "runtime": {
            "base_url":
                settings.base_url,
            "environment":
                settings.environment,
            "cycle":
                settings.cycle,
            "round":
                settings.round_number,
        },
        "elections": [],
        "total_targets":
            total_targets,
    }

    for plan in plans:
        counts = Counter(
            target.office_code
            for target
            in plan.targets
        )

        scopes = {
            target.scope_code
            for target
            in plan.targets
        }

        output[
            "elections"
        ].append(
            {
                "election_code":
                    plan.election_code,
                "election_type":
                    plan.election_type,
                "ea14_url":
                    plan.ea14_url,
                "ea14_idg":
                    plan.ea14_idg,
                "scope_count":
                    len(scopes),
                "target_count":
                    len(plan.targets),
                "office_counts": {
                    str(code): count
                    for code, count
                    in sorted(
                        counts.items()
                    )
                },
            }
        )

    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
