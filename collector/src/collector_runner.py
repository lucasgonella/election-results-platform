from __future__ import annotations

import argparse
from dataclasses import dataclass
import json

from .batch_ingest import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_WORKERS,
    run_batched_ingest,
)
from .observability_repository import (
    CollectorObservability,
    get_observability,
)
from .runtime import (
    RuntimeSettings,
    load_settings,
)
from .tse_client import TseClient


DEFAULT_CYCLES = 1


@dataclass(frozen=True, slots=True)
class RunnerCycleSummary:
    cycle_number: int

    processed_targets: int
    failed_targets: int

    state_updates_committed: int
    data_updates_committed: int

    pending_before: int
    pending_after: int

    completed_after: int
    error_after: int

    health_after: str

    errors: tuple[
        str,
        ...
    ]


@dataclass(frozen=True, slots=True)
class CollectorRunnerResult:
    execute: bool

    batch_size: int
    workers: int
    requested_cycles: int
    completed_cycles: int

    stop_reason: str

    planned_targets: int
    selected_targets: int

    processed_targets: int
    failed_targets: int

    state_updates_committed: int
    data_updates_committed: int

    before: CollectorObservability
    after: CollectorObservability

    cycles: tuple[
        RunnerCycleSummary,
        ...
    ]


def _get_status(
    settings: RuntimeSettings,
) -> CollectorObservability:
    return get_observability(
        environment=(
            settings.environment
        ),
        cycle=(
            settings.cycle
        ),
    )


def run_collector(
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
    cycles: int = (
        DEFAULT_CYCLES
    ),
    allow_official: bool = False,
    election_code: int | None = None,
    scope_code: str | None = None,
    office_code: int | None = None,
) -> CollectorRunnerResult:
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
            "workers must be greater "
            "than zero."
        )

    if cycles < 1:
        raise ValueError(
            "cycles must be greater "
            "than zero."
        )

    selected_client = (
        client
        or TseClient()
    )

    before = _get_status(
        selected_settings
    )

    if not execute:
        dry_run = run_batched_ingest(
            settings=(
                selected_settings
            ),
            client=(
                selected_client
            ),
            execute=False,
            batch_size=batch_size,
            workers=workers,
            allow_official=(
                allow_official
            ),
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

        return CollectorRunnerResult(
            execute=False,
            batch_size=batch_size,
            workers=workers,
            requested_cycles=cycles,
            completed_cycles=0,
            stop_reason="dry_run",
            planned_targets=(
                dry_run
                .planned_targets
            ),
            selected_targets=(
                dry_run
                .selected_targets
            ),
            processed_targets=0,
            failed_targets=0,
            state_updates_committed=0,
            data_updates_committed=0,
            before=before,
            after=before,
            cycles=(),
        )

    current_status = before

    cycle_summaries: list[
        RunnerCycleSummary
    ] = []

    total_processed = 0
    total_failed = 0
    total_committed = 0
    total_data_committed = 0

    planned_targets = 0
    selected_targets = 0

    stop_reason = "cycle_limit"

    for cycle_number in range(
        1,
        cycles + 1,
    ):
        batch_result = (
            run_batched_ingest(
                settings=(
                    selected_settings
                ),
                client=(
                    selected_client
                ),
                execute=True,
                batch_size=(
                    batch_size
                ),
                workers=(
                    workers
                ),
                allow_official=(
                    allow_official
                ),
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

        planned_targets = (
            batch_result
            .planned_targets
        )

        selected_targets = (
            batch_result
            .selected_targets
        )

        after_cycle = _get_status(
            selected_settings
        )

        summary = RunnerCycleSummary(
            cycle_number=(
                cycle_number
            ),
            processed_targets=(
                batch_result
                .processed_targets
            ),
            failed_targets=(
                batch_result
                .failed_targets
            ),
            state_updates_committed=(
                batch_result
                .state_updates_committed
            ),
            data_updates_committed=(
                batch_result
                .data_updates_committed
            ),
            pending_before=(
                current_status
                .pending_items
            ),
            pending_after=(
                after_cycle
                .pending_items
            ),
            completed_after=(
                after_cycle
                .completed_items
            ),
            error_after=(
                after_cycle
                .error_items
            ),
            health_after=(
                after_cycle.health
            ),
            errors=tuple(
                batch_result.errors
            ),
        )

        cycle_summaries.append(
            summary
        )

        total_processed += (
            batch_result
            .processed_targets
        )

        total_failed += (
            batch_result
            .failed_targets
        )

        total_committed += (
            batch_result
            .state_updates_committed
        )

        total_data_committed += (
            batch_result
            .data_updates_committed
        )

        current_status = (
            after_cycle
        )

        if (
            batch_result
            .failed_targets
            > 0
        ):
            stop_reason = "error"
            break

        if (
            batch_result
            .processed_targets
            == 0
            and batch_result
            .state_updates_committed
            == 0
        ):
            stop_reason = "idle"
            break

        if (
            after_cycle
            .pending_items
            == 0
            and after_cycle
            .error_items
            == 0
        ):
            stop_reason = "idle"
            break

    return CollectorRunnerResult(
        execute=True,
        batch_size=batch_size,
        workers=workers,
        requested_cycles=cycles,
        completed_cycles=(
            len(
                cycle_summaries
            )
        ),
        stop_reason=(
            stop_reason
        ),
        planned_targets=(
            planned_targets
        ),
        selected_targets=(
            selected_targets
        ),
        processed_targets=(
            total_processed
        ),
        failed_targets=(
            total_failed
        ),
        state_updates_committed=(
            total_committed
        ),
        data_updates_committed=(
            total_data_committed
        ),
        before=before,
        after=current_status,
        cycles=tuple(
            cycle_summaries
        ),
    )


def _status_output(
    status: CollectorObservability,
) -> dict:
    return {
        "health":
            status.health,

        "active_batches":
            status.active_batches,

        "pending_items":
            status.pending_items,

        "completed_items":
            status.completed_items,

        "error_items":
            status.error_items,

        "ea14_states":
            status.ea14_states,
    }


def _build_output(
    result: CollectorRunnerResult,
    settings: RuntimeSettings,
    *,
    election_code: int | None,
    scope_code: str | None,
    office_code: int | None,
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

        "filters": {
            "election_code":
                election_code,
            "scope_code":
                scope_code,
            "office_code":
                office_code,
        },

        "batch_size":
            result.batch_size,

        "workers":
            result.workers,

        "requested_cycles":
            result
            .requested_cycles,

        "completed_cycles":
            result
            .completed_cycles,

        "stop_reason":
            result.stop_reason,

        "planned_targets":
            result.planned_targets,

        "selected_targets":
            result.selected_targets,

        "processed_targets":
            result
            .processed_targets,

        "failed_targets":
            result.failed_targets,

        "state_updates_committed":
            result
            .state_updates_committed,

        "data_updates_committed":
            result
            .data_updates_committed,

        "before":
            _status_output(
                result.before
            ),

        "after":
            _status_output(
                result.after
            ),

        "cycles": [
            {
                "cycle":
                    cycle.cycle_number,

                "processed_targets":
                    cycle
                    .processed_targets,

                "failed_targets":
                    cycle.failed_targets,

                "state_updates_committed":
                    cycle
                    .state_updates_committed,

                "data_updates_committed":
                    cycle
                    .data_updates_committed,

                "pending_before":
                    cycle
                    .pending_before,

                "pending_after":
                    cycle
                    .pending_after,

                "completed_after":
                    cycle
                    .completed_after,

                "error_after":
                    cycle.error_after,

                "health_after":
                    cycle.health_after,

                "errors":
                    list(
                        cycle.errors
                    ),
            }
            for cycle
            in result.cycles
        ],
    }



def _exit_code(
    result: CollectorRunnerResult,
) -> int:
    if (
        result.failed_targets > 0
        or result.stop_reason == "error"
    ):
        return 1

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Operational collector "
            "runner."
        )
    )

    mode = (
        parser
        .add_mutually_exclusive_group()
    )

    mode.add_argument(
        "--dry-run",
        action="store_true",
    )

    mode.add_argument(
        "--execute",
        action="store_true",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=(
            DEFAULT_BATCH_SIZE
        ),
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=(
            DEFAULT_WORKERS
        ),
    )

    parser.add_argument(
        "--cycles",
        type=int,
        default=(
            DEFAULT_CYCLES
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

    result = run_collector(
        settings=settings,
        execute=args.execute,
        batch_size=(
            args.batch_size
        ),
        workers=(
            args.workers
        ),
        cycles=(
            args.cycles
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

    return _exit_code(
        result
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )