from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import os
import threading

from .discovery import ElectionTarget
from .ingest import (
    FetchedTarget,
    TargetIngestResult,
    _looks_official,
    _persist_fetched_target,
    _validate_target_payload,
)
from .parser import parse_ea20
from .planner import fetch_collection_plan
from .repository import get_connection
from .runtime import (
    RuntimeSettings,
    load_settings,
)
from .tse_client import TseClient


DEFAULT_BATCH_SIZE = 25
DEFAULT_WORKERS = 1


@dataclass(frozen=True, slots=True)
class BootstrapMissingResult:
    execute: bool
    batch_size: int
    workers: int

    planned_targets: int
    existing_targets: int
    missing_before: int

    selected_targets: int
    processed_targets: int
    failed_targets: int

    remaining_after: int

    results: tuple[
        TargetIngestResult,
        ...
    ]

    errors: tuple[
        str,
        ...
    ]


def _target_key(
    target: ElectionTarget,
) -> tuple[int, str, int]:
    return (
        target.election_code,
        target.scope_code.lower(),
        target.office_code,
    )


def list_existing_target_keys(
    *,
    environment: str,
) -> set[
    tuple[int, str, int]
]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT
                    e.tse_election_code,
                    LOWER(s.code),
                    o.tse_code

                FROM scope_snapshots ss

                JOIN elections e
                    ON e.id = ss.election_id

                JOIN scopes s
                    ON s.id = ss.scope_id

                JOIN offices o
                    ON o.id = ss.office_id

                WHERE e.environment = %s
                """,
                (environment,),
            )

            rows = cursor.fetchall()

    return {
        (
            int(row[0]),
            str(row[1]).lower(),
            int(row[2]),
        )
        for row in rows
    }


def _worker_client(
    *,
    base_client: TseClient,
    local_state: threading.local,
):
    if not isinstance(
        base_client,
        TseClient,
    ):
        return base_client

    worker = getattr(
        local_state,
        "client",
        None,
    )

    if worker is None:
        worker = TseClient(
            timeout=(
                base_client.timeout
            )
        )

        local_state.client = worker

    return worker


def _fetch_target_unconditional(
    *,
    target: ElectionTarget,
    client: TseClient,
) -> FetchedTarget:
    response = client.fetch_json(
        target.url
    )

    if response.status_code == 304:
        raise RuntimeError(
            "Unexpected HTTP 304 during "
            "missing-target bootstrap."
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
        cached_state=None,
        parsed=parsed,
    )


def run_bootstrap_missing(
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
    batch_size: int = (
        DEFAULT_BATCH_SIZE
    ),
    workers: int = (
        DEFAULT_WORKERS
    ),
    allow_official: bool = False,
) -> BootstrapMissingResult:
    selected_settings = (
        settings
        or load_settings()
    )

    if batch_size < 1:
        raise ValueError(
            "batch_size must be "
            "greater than zero."
        )

    if workers < 1:
        raise ValueError(
            "workers must be "
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
            "Missing-target bootstrap "
            "against the official TSE "
            "environment is blocked."
        )

    selected_client = (
        client
        or TseClient()
    )

    plans = fetch_collection_plan(
        settings=selected_settings,
        client=selected_client,
    )

    planned = tuple(
        target
        for plan in plans
        for target in plan.targets
    )

    existing_keys = (
        list_existing_target_keys(
            environment=(
                selected_settings
                .environment
            )
        )
    )

    existing_in_plan = sum(
        1
        for target in planned
        if _target_key(target)
        in existing_keys
    )

    missing = tuple(
        target
        for target in planned
        if _target_key(target)
        not in existing_keys
    )

    selected = missing[
        :batch_size
    ]

    if not execute:
        return BootstrapMissingResult(
            execute=False,
            batch_size=batch_size,
            workers=workers,
            planned_targets=len(
                planned
            ),
            existing_targets=(
                existing_in_plan
            ),
            missing_before=len(
                missing
            ),
            selected_targets=len(
                selected
            ),
            processed_targets=0,
            failed_targets=0,
            remaining_after=len(
                missing
            ),
            results=(),
            errors=(),
        )

    fetched_by_index: dict[
        int,
        FetchedTarget,
    ] = {}

    errors_by_index: dict[
        int,
        str,
    ] = {}

    if workers == 1:
        for index, target in enumerate(
            selected
        ):
            try:
                fetched_by_index[
                    index
                ] = (
                    _fetch_target_unconditional(
                        target=target,
                        client=selected_client,
                    )
                )

            except Exception as exc:
                errors_by_index[
                    index
                ] = (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

    elif selected:
        local_state = (
            threading.local()
        )

        def fetch_job(
            target: ElectionTarget,
        ) -> FetchedTarget:
            worker_client = (
                _worker_client(
                    base_client=(
                        selected_client
                    ),
                    local_state=(
                        local_state
                    ),
                )
            )

            return (
                _fetch_target_unconditional(
                    target=target,
                    client=worker_client,
                )
            )

        max_workers = min(
            workers,
            len(selected),
        )

        with ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=(
                "bootstrap-ea20"
            ),
        ) as executor:
            futures = [
                executor.submit(
                    fetch_job,
                    target,
                )
                for target
                in selected
            ]

            for index, future in enumerate(
                futures
            ):
                try:
                    fetched_by_index[
                        index
                    ] = future.result()

                except Exception as exc:
                    errors_by_index[
                        index
                    ] = (
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    )

    results: list[
        TargetIngestResult
    ] = []

    errors: list[str] = []

    for index, target in enumerate(
        selected
    ):
        fetch_error = (
            errors_by_index.get(
                index
            )
        )

        if fetch_error is not None:
            errors.append(
                f"{target.url} -> "
                f"{fetch_error}"
            )

            continue

        fetched = (
            fetched_by_index[
                index
            ]
        )

        try:
            result = (
                _persist_fetched_target(
                    fetched=fetched,
                    settings=(
                        selected_settings
                    ),
                )
            )

        except Exception as exc:
            errors.append(
                f"{target.url} -> "
                f"{type(exc).__name__}: "
                f"{exc}"
            )

            continue

        results.append(
            result
        )

    processed = len(
        results
    )

    failed = len(
        errors
    )

    remaining_after = (
        len(missing)
        - processed
    )

    return BootstrapMissingResult(
        execute=True,
        batch_size=batch_size,
        workers=workers,
        planned_targets=len(
            planned
        ),
        existing_targets=(
            existing_in_plan
        ),
        missing_before=len(
            missing
        ),
        selected_targets=len(
            selected
        ),
        processed_targets=processed,
        failed_targets=failed,
        remaining_after=(
            remaining_after
        ),
        results=tuple(
            results
        ),
        errors=tuple(
            errors
        ),
    )


def _build_output(
    result: BootstrapMissingResult,
    settings: RuntimeSettings,
) -> dict:
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
        "batch_size":
            result.batch_size,
        "workers":
            result.workers,
        "planned_targets":
            result.planned_targets,
        "existing_targets":
            result.existing_targets,
        "missing_before":
            result.missing_before,
        "selected_targets":
            result.selected_targets,
        "processed_targets":
            result.processed_targets,
        "failed_targets":
            result.failed_targets,
        "remaining_after":
            result.remaining_after,
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
                "tse_idg":
                    item.tse_idg,
                "candidates_processed":
                    item.candidates_processed,
            }
            for item
            in result.results
        ],
        "errors":
            list(
                result.errors
            ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Collect supported EA20 targets "
            "that do not yet have a persisted "
            "scope snapshot."
        )
    )

    parser.add_argument(
        "--execute",
        action="store_true",
    )

    parser.add_argument(
        "--until-complete",
        action="store_true",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(
            os.getenv(
                "COLLECTOR_BATCH_SIZE",
                str(
                    DEFAULT_BATCH_SIZE
                ),
            )
        ),
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=int(
            os.getenv(
                "COLLECTOR_WORKERS",
                str(
                    DEFAULT_WORKERS
                ),
            )
        ),
    )

    parser.add_argument(
        "--allow-official",
        action="store_true",
    )

    args = parser.parse_args()

    settings = load_settings()

    cycles = []

    while True:
        result = run_bootstrap_missing(
            settings=settings,
            execute=args.execute,
            batch_size=(
                args.batch_size
            ),
            workers=(
                args.workers
            ),
            allow_official=(
                args.allow_official
            ),
        )

        cycles.append(
            _build_output(
                result,
                settings,
            )
        )

        if (
            not args.execute
            or not args.until_complete
            or result.remaining_after == 0
            or result.failed_targets > 0
            or result.processed_targets == 0
        ):
            break

    output = {
        "cycles": cycles,
        "cycle_count": len(
            cycles
        ),
        "completed": (
            cycles[-1][
                "remaining_after"
            ]
            == 0
        ),
        "failed_targets": (
            sum(
                cycle[
                    "failed_targets"
                ]
                for cycle
                in cycles
            )
        ),
        "remaining_after": (
            cycles[-1][
                "remaining_after"
            ]
        ),
    }

    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
    )

    if (
        output["failed_targets"] > 0
        or (
            args.execute
            and args.until_complete
            and not output[
                "completed"
            ]
        )
    ):
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
