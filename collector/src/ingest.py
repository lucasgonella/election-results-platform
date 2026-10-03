from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json

from .discovery import ElectionTarget
from .ea14_state_repository import (
    save_ea14_state,
)
from .parser import (
    ParsedResult,
    parse_ea20,
)
from .repository import (
    CachedFetchState,
    get_last_fetch_state,
    persist_result,
    record_not_modified,
)
from .runtime import (
    RuntimeSettings,
    load_settings,
)
from .stateful_planner import (
    StatefulPlannerResult,
    run_stateful_planner,
)
from .tse_client import (
    TseClient,
    TseFetchResult,
)


DEFAULT_MAX_TARGETS = 10


@dataclass(frozen=True, slots=True)
class TargetIngestResult:
    election_code: int
    scope_code: str
    office_code: int

    status: str
    http_status: int

    collector_run_id: int | None
    tse_idg: int | None

    snapshots_created: int
    candidates_processed: int


@dataclass(frozen=True, slots=True)
class FetchedTarget:
    target: ElectionTarget
    response: TseFetchResult

    cached_state: (
        CachedFetchState
        | None
    )

    parsed: (
        ParsedResult
        | None
    )


@dataclass(frozen=True, slots=True)
class SelectiveIngestResult:
    execute: bool

    planned_targets: int
    selected_targets: int
    processed_targets: int

    state_updates_committed: int

    planner: StatefulPlannerResult

    results: tuple[
        TargetIngestResult,
        ...
    ]


def _looks_official(
    settings: RuntimeSettings,
) -> bool:
    if (
        settings.environment
        .strip()
        .lower()
        == "oficial"
    ):
        return True

    normalized_base = (
        settings.base_url
        .strip()
        .rstrip("/")
        .lower()
    )

    return (
        normalized_base
        == "https://resultados.tse.jus.br"
    )


def _target_matches(
    target: ElectionTarget,
    *,
    election_code: int | None,
    scope_code: str | None,
    office_code: int | None,
) -> bool:
    if (
        election_code is not None
        and target.election_code
        != election_code
    ):
        return False

    if (
        scope_code is not None
        and target.scope_code.lower()
        != scope_code.lower()
    ):
        return False

    if (
        office_code is not None
        and target.office_code
        != office_code
    ):
        return False

    return True


def _validate_target_payload(
    *,
    target: ElectionTarget,
    parsed: ParsedResult,
) -> None:
    if (
        parsed.election_code
        != target.election_code
    ):
        raise ValueError(
            "EA20 election mismatch: "
            f"target={target.election_code}, "
            f"payload={parsed.election_code}."
        )

    if (
        parsed.round_number
        != target.round_number
    ):
        raise ValueError(
            "EA20 round mismatch: "
            f"target={target.round_number}, "
            f"payload={parsed.round_number}."
        )

    if (
        parsed.scope_code.lower()
        != target.scope_code.lower()
    ):
        raise ValueError(
            "EA20 scope mismatch: "
            f"target={target.scope_code}, "
            f"payload={parsed.scope_code}."
        )

    office_codes = tuple(
        office.code
        for office in parsed.offices
    )

    if office_codes != (
        target.office_code,
    ):
        raise ValueError(
            "EA20 office mismatch: "
            f"target={target.office_code}, "
            f"payload={office_codes}."
        )


def _fetch_target(
    *,
    target: ElectionTarget,
    client: TseClient,
) -> FetchedTarget:
    cached_state = (
        get_last_fetch_state(
            target.url
        )
    )

    response = client.fetch_json(
        target.url,
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
                "Received EA20 HTTP 304 "
                "without cached state."
            )

        return FetchedTarget(
            target=target,
            response=response,
            cached_state=(
                cached_state
            ),
            parsed=None,
        )

    if response.payload is None:
        raise RuntimeError(
            "EA20 returned no payload "
            f"for {target.url}."
        )

    parsed = parse_ea20(
        response.payload
    )

    _validate_target_payload(
        target=target,
        parsed=parsed,
    )

    return FetchedTarget(
        target=target,
        response=response,
        cached_state=(
            cached_state
        ),
        parsed=parsed,
    )


def _persist_fetched_target(
    *,
    fetched: FetchedTarget,
    settings: RuntimeSettings,
) -> TargetIngestResult:
    target = fetched.target
    response = fetched.response

    if response.status_code == 304:
        cached_state = (
            fetched.cached_state
        )

        if cached_state is None:
            raise RuntimeError(
                "Received EA20 HTTP 304 "
                "without cached state."
            )

        collector_run_id = (
            record_not_modified(
                response,
                cached_state,
            )
        )

        return TargetIngestResult(
            election_code=(
                target.election_code
            ),
            scope_code=(
                target.scope_code
            ),
            office_code=(
                target.office_code
            ),
            status="not_modified",
            http_status=304,
            collector_run_id=(
                collector_run_id
            ),
            tse_idg=(
                cached_state.tse_idg
            ),
            snapshots_created=0,
            candidates_processed=0,
        )

    parsed = fetched.parsed

    if parsed is None:
        raise RuntimeError(
            "EA20 parsed payload is missing "
            f"for {target.url}."
        )

    persisted = persist_result(
        response,
        parsed,
        environment=(
            settings.environment
        ),
    )

    return TargetIngestResult(
        election_code=(
            target.election_code
        ),
        scope_code=(
            target.scope_code
        ),
        office_code=(
            target.office_code
        ),
        status="success",
        http_status=(
            response.status_code
        ),
        collector_run_id=(
            persisted.collector_run_id
        ),
        tse_idg=(
            parsed.tse_idg
        ),
        snapshots_created=(
            persisted.snapshots_created
        ),
        candidates_processed=(
            persisted.candidates_processed
        ),
    )


def _ingest_target(
    *,
    target: ElectionTarget,
    settings: RuntimeSettings,
    client: TseClient,
) -> TargetIngestResult:
    fetched = _fetch_target(
        target=target,
        client=client,
    )

    return _persist_fetched_target(
        fetched=fetched,
        settings=settings,
    )

def _commit_ea14_state(
    election,
) -> None:
    update = election.state_update

    if update is None:
        return

    save_ea14_state(
        environment=(
            update.environment
        ),
        cycle=(
            update.cycle
        ),
        election_code=(
            update.election_code
        ),
        round_number=(
            update.round_number
        ),
        fetch_result=(
            update.fetch_result
        ),
        payload=(
            update.payload
        ),
    )


def run_selective_ingest(
    *,
    settings: (
        RuntimeSettings
        | None
    ) = None,
    client: (
        TseClient
        | None
    ) = None,
    execute: bool = False,
    max_targets: int = (
        DEFAULT_MAX_TARGETS
    ),
    allow_official: bool = False,
    election_code: int | None = None,
    scope_code: str | None = None,
    office_code: int | None = None,
) -> SelectiveIngestResult:
    selected_settings = (
        settings
        or load_settings()
    )

    if max_targets < 1:
        raise ValueError(
            "max_targets must be "
            "greater than zero."
        )

    if (
        execute
        and _looks_official(
            selected_settings
        )
        and not allow_official
    ):
        raise RuntimeError(
            "EA20 ingestion against the "
            "official TSE environment is "
            "blocked. Use --allow-official "
            "only after explicit validation."
        )

    selected_client = (
        client
        or TseClient()
    )

    planner = (
        run_stateful_planner(
            settings=(
                selected_settings
            ),
            client=(
                selected_client
            ),
            persist_state=False,
        )
    )

    planned_targets = len(
        planner.targets
    )

    selected = tuple(
        target
        for target in planner.targets
        if _target_matches(
            target,
            election_code=(
                election_code
            ),
            scope_code=(
                scope_code
            ),
            office_code=(
                office_code
            ),
        )
    )

    selected_target_count = len(
        selected
    )

    if not execute:
        return SelectiveIngestResult(
            execute=False,
            planned_targets=(
                planned_targets
            ),
            selected_targets=(
                selected_target_count
            ),
            processed_targets=0,
            state_updates_committed=0,
            planner=planner,
            results=(),
        )

    if (
        selected_target_count
        > max_targets
    ):
        raise RuntimeError(
            "Selection produced "
            f"{selected_target_count} "
            "EA20 targets, which exceeds "
            "max_targets="
            f"{max_targets}. "
            "No EA20 request was executed "
            "and EA14 state was not committed."
        )

    selected_urls = {
        target.url
        for target in selected
    }

    results: list[
        TargetIngestResult
    ] = []

    committed = 0

    for election in planner.elections:
        election_selected = tuple(
            target
            for target
            in election.targets
            if target.url
            in selected_urls
        )

        for target in (
            election_selected
        ):
            result = _ingest_target(
                target=target,
                settings=(
                    selected_settings
                ),
                client=(
                    selected_client
                ),
            )

            results.append(
                result
            )

        full_election_processed = (
            len(election_selected)
            == len(election.targets)
        )

        if (
            election.state_update
            is not None
            and full_election_processed
        ):
            _commit_ea14_state(
                election
            )

            committed += 1

    return SelectiveIngestResult(
        execute=True,
        planned_targets=(
            planned_targets
        ),
        selected_targets=(
            selected_target_count
        ),
        processed_targets=(
            len(results)
        ),
        state_updates_committed=(
            committed
        ),
        planner=planner,
        results=tuple(results),
    )


def _build_output(
    result: SelectiveIngestResult,
    settings: RuntimeSettings,
    max_targets: int,
    *,
    election_code: int | None,
    scope_code: str | None,
    office_code: int | None,
) -> dict:
    planned_by_election = {}

    for election in (
        result.planner.elections
    ):
        office_counts = Counter(
            target.office_code
            for target
            in election.targets
        )

        planned_by_election[
            str(
                election.election_code
            )
        ] = {
            "status":
                election.status,

            "changed_scopes":
                list(
                    election
                    .changed_scopes
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

    return {
        "mode": (
            "execute"
            if result.execute
            else "dry-run"
        ),

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

        "filters": {
            "election_code":
                election_code,
            "scope_code":
                scope_code,
            "office_code":
                office_code,
        },

        "safety": {
            "max_targets":
                max_targets,
            "official_environment":
                _looks_official(
                    settings
                ),
        },

        "planned_targets":
            result.planned_targets,

        "selected_targets":
            result.selected_targets,

        "processed_targets":
            result.processed_targets,

        "state_updates_committed":
            result
            .state_updates_committed,

        "elections":
            planned_by_election,

        "results": [
            {
                "election_code":
                    item.election_code,

                "scope_code":
                    item.scope_code,

                "office_code":
                    item.office_code,

                "status":
                    item.status,

                "http_status":
                    item.http_status,

                "collector_run_id":
                    item.collector_run_id,

                "tse_idg":
                    item.tse_idg,

                "snapshots_created":
                    item
                    .snapshots_created,

                "candidates_processed":
                    item
                    .candidates_processed,
            }
            for item in result.results
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Selective TSE EA20 "
            "collector."
        )
    )

    mode = (
        parser
        .add_mutually_exclusive_group()
    )

    mode.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Plan EA20 work without "
            "executing EA20 requests. "
            "This is the default."
        ),
    )

    mode.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Execute the planned "
            "EA20 ingestion."
        ),
    )

    parser.add_argument(
        "--max-targets",
        type=int,
        default=(
            DEFAULT_MAX_TARGETS
        ),
    )

    parser.add_argument(
        "--election",
        type=int,
        dest="election_code",
    )

    parser.add_argument(
        "--scope",
        dest="scope_code",
    )

    parser.add_argument(
        "--office",
        type=int,
        dest="office_code",
    )

    parser.add_argument(
        "--allow-official",
        action="store_true",
    )

    args = parser.parse_args()

    settings = load_settings()

    result = run_selective_ingest(
        settings=settings,
        execute=args.execute,
        max_targets=(
            args.max_targets
        ),
        allow_official=(
            args.allow_official
        ),
        election_code=(
            args.election_code
        ),
        scope_code=(
            args.scope_code
        ),
        office_code=(
            args.office_code
        ),
    )

    print(
        json.dumps(
            _build_output(
                result,
                settings,
                args.max_targets,
                election_code=(
                    args.election_code
                ),
                scope_code=(
                    args.scope_code
                ),
                office_code=(
                    args.office_code
                ),
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()