from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json

from .change_detection import (
    detect_plan_changes,
)
from .discovery import (
    ElectionTarget,
    generate_targets,
)
from .ea14_state_repository import (
    get_ea14_state,
    save_ea14_state,
)
from .planner import (
    ElectionCollectionPlan,
    build_ea14_url,
)
from .runtime import (
    RuntimeSettings,
    build_config_url,
    load_settings,
    select_supported_elections,
)
from .tse_client import (
    TseClient,
)


@dataclass(frozen=True, slots=True)
class EA14StateUpdate:
    environment: str
    cycle: str

    election_code: int
    round_number: int

    fetch_result: object
    payload: dict


@dataclass(frozen=True, slots=True)
class StatefulElectionResult:
    election_code: int
    election_type: int | None

    ea14_url: str
    http_status: int

    status: str

    changed_scopes: tuple[str, ...]

    targets: tuple[
        ElectionTarget,
        ...
    ]

    state_update: (
        EA14StateUpdate
        | None
    )


@dataclass(frozen=True, slots=True)
class StatefulPlannerResult:
    config_url: str

    elections: tuple[
        StatefulElectionResult,
        ...
    ]

    @property
    def targets(
        self,
    ) -> tuple[
        ElectionTarget,
        ...
    ]:
        return tuple(
            target
            for election
            in self.elections
            for target
            in election.targets
        )


def _build_plan(
    *,
    config_payload,
    ea14_payload,
    settings,
    election,
) -> ElectionCollectionPlan:
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

    return ElectionCollectionPlan(
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


def run_stateful_planner(
    *,
    settings: (
        RuntimeSettings
        | None
    ) = None,
    client: (
        TseClient
        | None
    ) = None,
    persist_state: bool = True,
) -> StatefulPlannerResult:
    selected_settings = (
        settings
        or load_settings()
    )

    selected_client = (
        client
        or TseClient()
    )

    config_url = build_config_url(
        selected_settings
    )

    config_response = (
        selected_client.fetch_json(
            config_url
        )
    )

    if config_response.payload is None:
        raise RuntimeError(
            "TSE configuration "
            "returned no payload."
        )

    config_payload = (
        config_response.payload
    )

    elections = (
        select_supported_elections(
            config_payload,
            selected_settings,
        )
    )

    results: list[
        StatefulElectionResult
    ] = []

    for election in elections:
        ea14_url = build_ea14_url(
            settings=selected_settings,
            election_code=(
                election.election_code
            ),
            cycle=election.cycle,
        )

        stored = get_ea14_state(
            environment=(
                selected_settings
                .environment
            ),
            cycle=election.cycle,
            election_code=(
                election.election_code
            ),
            round_number=(
                election.round_number
            ),
        )

        response = (
            selected_client.fetch_json(
                ea14_url,
                etag=(
                    stored.etag
                    if stored
                    else None
                ),
                last_modified=(
                    stored.last_modified
                    if stored
                    else None
                ),
            )
        )

        if response.status_code == 304:
            if stored is None:
                raise RuntimeError(
                    "Received HTTP 304 "
                    "without stored EA14 state."
                )

            results.append(
                StatefulElectionResult(
                    election_code=(
                        election.election_code
                    ),
                    election_type=(
                        election.election_type
                    ),
                    ea14_url=ea14_url,
                    http_status=304,
                    status="not_modified",
                    changed_scopes=(),
                    targets=(),
                    state_update=None,
                )
            )

            continue

        if response.payload is None:
            raise RuntimeError(
                "EA14 returned no payload "
                "for election "
                f"{election.election_code}."
            )

        plan = _build_plan(
            config_payload=(
                config_payload
            ),
            ea14_payload=(
                response.payload
            ),
            settings=(
                selected_settings
            ),
            election=election,
        )

        previous_payload = (
            stored.payload
            if stored
            else None
        )

        detection = (
            detect_plan_changes(
                plan=plan,
                previous_payload=(
                    previous_payload
                ),
                current_payload=(
                    response.payload
                ),
            )
        )

        state_update = EA14StateUpdate(
            environment=(
                selected_settings
                .environment
            ),
            cycle=election.cycle,
            election_code=(
                election.election_code
            ),
            round_number=(
                election.round_number
            ),
            fetch_result=response,
            payload=response.payload,
        )

        if persist_state:
            save_ea14_state(
                environment=(
                    state_update
                    .environment
                ),
                cycle=(
                    state_update
                    .cycle
                ),
                election_code=(
                    state_update
                    .election_code
                ),
                round_number=(
                    state_update
                    .round_number
                ),
                fetch_result=(
                    state_update
                    .fetch_result
                ),
                payload=(
                    state_update
                    .payload
                ),
            )

        if stored is None:
            status = "initialized"

        elif detection.changes:
            status = "changed"

        else:
            status = "unchanged"

        results.append(
            StatefulElectionResult(
                election_code=(
                    election.election_code
                ),
                election_type=(
                    election.election_type
                ),
                ea14_url=ea14_url,
                http_status=(
                    response.status_code
                ),
                status=status,
                changed_scopes=tuple(
                    change.scope_code
                    for change
                    in detection.changes
                ),
                targets=(
                    detection.targets
                ),
                state_update=(
                    state_update
                ),
            )
        )

    return StatefulPlannerResult(
        config_url=config_url,
        elections=tuple(results),
    )


def main() -> None:
    settings = load_settings()

    result = run_stateful_planner(
        settings=settings
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
        "config_url":
            result.config_url,
        "elections": [],
        "total_targets":
            len(result.targets),
    }

    for election in result.elections:
        office_counts = Counter(
            target.office_code
            for target
            in election.targets
        )

        output[
            "elections"
        ].append(
            {
                "election_code":
                    election.election_code,

                "election_type":
                    election.election_type,

                "http_status":
                    election.http_status,

                "status":
                    election.status,

                "changed_scopes":
                    list(
                        election.changed_scopes
                    ),

                "changed_scope_count":
                    len(
                        election.changed_scopes
                    ),

                "target_count":
                    len(
                        election.targets
                    ),

                "office_counts": {
                    str(code): count
                    for code, count
                    in sorted(
                        office_counts.items()
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
