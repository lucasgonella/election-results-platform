from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import threading
import time

from .discovery import ElectionTarget
from .ea20_batch_repository import (
    EA20Batch,
    get_pending_items,
    mark_batch_completed,
    mark_item_completed,
    mark_item_error,
    prepare_batch,
    refresh_batch_progress,
)
from .ingest import (
    TargetIngestResult,
    _commit_ea14_state,
    _fetch_target,
    _ingest_target,
    _looks_official,
    _persist_fetched_target,
    _target_matches,
)
from .runtime import (
    RuntimeSettings,
    load_settings,
)
from .stateful_planner import (
    StatefulPlannerResult,
    run_stateful_planner,
)
from .tse_client import TseClient


DEFAULT_BATCH_SIZE = 10
DEFAULT_WORKERS = 1


def _elapsed_ms(
    started_ns: int,
) -> float:
    return round(
        (
            time.perf_counter_ns()
            - started_ns
        )
        / 1_000_000,
        3,
    )


@dataclass(frozen=True, slots=True)
class BatchElectionSummary:
    election_code: int

    batch_id: int
    batch_status: str

    total_targets: int
    completed_targets: int

    processed_this_run: int
    failed_this_run: int

    state_committed: bool


@dataclass(frozen=True, slots=True)
class BatchedIngestResult:
    execute: bool
    batch_size: int
    workers: int

    planned_targets: int
    selected_targets: int

    processed_targets: int
    failed_targets: int

    state_updates_committed: int
    data_updates_committed: int

    planner: StatefulPlannerResult

    elections: tuple[
        BatchElectionSummary,
        ...
    ]

    results: tuple[
        TargetIngestResult,
        ...
    ]

    errors: tuple[
        str,
        ...
    ]

    duration_ms: float = 0.0
    planner_duration_ms: float = 0.0
    fetch_duration_ms: float = 0.0
    persist_duration_ms: float = 0.0
    candidates_processed: int = 0


def _selected_urls(
    *,
    planner: StatefulPlannerResult,
    election_code: int | None,
    scope_code: str | None,
    office_code: int | None,
) -> set[str]:
    return {
        target.url
        for target in planner.targets
        if _target_matches(
            target,
            election_code=election_code,
            scope_code=scope_code,
            office_code=office_code,
        )
    }


def _prepare_election_batch(
    *,
    election,
) -> EA20Batch:
    update = election.state_update

    if update is None:
        raise RuntimeError(
            "Cannot prepare EA20 batch "
            "without EA14 state update."
        )

    sha256 = (
        update.fetch_result.sha256
    )

    if not sha256:
        raise RuntimeError(
            "EA14 payload has no SHA256."
        )

    raw_idg = update.payload.get(
        "idg"
    )

    tse_idg = (
        int(raw_idg)
        if raw_idg not in (
            None,
            "",
        )
        else None
    )

    return prepare_batch(
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
        ea14_tse_idg=(
            tse_idg
        ),
        ea14_payload_sha256=(
            sha256
        ),
        ea14_source_url=(
            update.fetch_result.url
        ),
        targets=(
            election.targets
        ),
    )


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


def run_batched_ingest(
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
    election_code: int | None = None,
    scope_code: str | None = None,
    office_code: int | None = None,
) -> BatchedIngestResult:
    run_started_ns = (
        time.perf_counter_ns()
    )

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
            "EA20 ingestion against the "
            "official TSE environment is "
            "blocked."
        )

    selected_client = (
        client
        or TseClient()
    )

    planner_started_ns = (
        time.perf_counter_ns()
    )

    planner = run_stateful_planner(
        settings=(
            selected_settings
        ),
        client=(
            selected_client
        ),
        persist_state=False,
    )

    planner_duration_ms = (
        _elapsed_ms(
            planner_started_ns
        )
    )

    selected_urls = _selected_urls(
        planner=planner,
        election_code=election_code,
        scope_code=scope_code,
        office_code=office_code,
    )

    planned_targets = len(
        planner.targets
    )

    selected_target_count = len(
        selected_urls
    )

    if not execute:
        return BatchedIngestResult(
            execute=False,
            batch_size=batch_size,
            workers=workers,
            planned_targets=(
                planned_targets
            ),
            selected_targets=(
                selected_target_count
            ),
            processed_targets=0,
            failed_targets=0,
            state_updates_committed=0,
            data_updates_committed=0,
            planner=planner,
            elections=(),
            results=(),
            errors=(),
            duration_ms=(
                _elapsed_ms(
                    run_started_ns
                )
            ),
            planner_duration_ms=(
                planner_duration_ms
            ),
        )

    filters_active = any(
        value is not None
        for value in (
            election_code,
            scope_code,
            office_code,
        )
    )

    if (
        filters_active
        and not selected_urls
    ):
        return BatchedIngestResult(
            execute=True,
            batch_size=batch_size,
            workers=workers,
            planned_targets=(
                planned_targets
            ),
            selected_targets=0,
            processed_targets=0,
            failed_targets=0,
            state_updates_committed=0,
            data_updates_committed=0,
            planner=planner,
            elections=(),
            results=(),
            errors=(),
            duration_ms=(
                _elapsed_ms(
                    run_started_ns
                )
            ),
            planner_duration_ms=(
                planner_duration_ms
            ),
        )

    prepared: list[
        tuple[
            object,
            EA20Batch,
        ]
    ] = []

    committed = 0
    data_committed = 0

    for election in planner.elections:
        if (
            election.state_update
            is None
        ):
            continue

        # EA14 can change without producing
        # any EA20 target. Persist the new
        # checkpoint, but do not create an
        # empty batch or trigger publishing.
        if not election.targets:
            _commit_ea14_state(
                election
            )

            committed += 1
            continue

        batch = (
            _prepare_election_batch(
                election=election
            )
        )

        prepared.append(
            (
                election,
                batch,
            )
        )

    remaining = batch_size

    results: list[
        TargetIngestResult
    ] = []

    errors: list[str] = []

    summaries: list[
        BatchElectionSummary
    ] = []

    failed = 0

    fetch_duration_ms = 0.0
    persist_duration_ms = 0.0
    candidates_processed = 0

    for election, batch in prepared:
        processed_for_election = 0
        failed_for_election = 0

        target_by_url: dict[
            str,
            ElectionTarget,
        ] = {
            target.url: target
            for target
            in election.targets
        }

        if (
            remaining > 0
            and batch.total_targets > 0
        ):
            pending = (
                get_pending_items(
                    batch_id=batch.id,
                    limit=max(
                        batch.total_targets,
                        1,
                    ),
                )
            )

            eligible = tuple(
                item
                for item in pending
                if (
                    item.source_url
                    in selected_urls
                )
            )

            selected_items = tuple(
                eligible[
                    :remaining
                ]
            )

            remaining -= len(
                selected_items
            )

            jobs = []

            for item in selected_items:
                target = (
                    target_by_url.get(
                        item.source_url
                    )
                )

                if target is None:
                    message = (
                        "Batch item does not "
                        "exist in current plan: "
                        f"{item.source_url}"
                    )

                    mark_item_error(
                        item_id=item.id,
                        error_message=message,
                    )

                    errors.append(
                        message
                    )

                    failed += 1
                    failed_for_election += 1

                    continue

                jobs.append(
                    (
                        item,
                        target,
                    )
                )

            if workers == 1:
                for item, target in jobs:
                    try:
                        result = (
                            _ingest_target(
                                target=target,
                                settings=(
                                    selected_settings
                                ),
                                client=(
                                    selected_client
                                ),
                            )
                        )

                    except Exception as exc:
                        message = (
                            f"{type(exc).__name__}: "
                            f"{exc}"
                        )

                        mark_item_error(
                            item_id=item.id,
                            error_message=message,
                        )

                        errors.append(
                            (
                                f"{target.url} -> "
                                f"{message}"
                            )
                        )

                        failed += 1
                        failed_for_election += 1

                        continue

                    item_status_started_ns = (
                        time.perf_counter_ns()
                    )

                    mark_item_completed(
                        item_id=item.id,
                        status=result.status,
                        collector_run_id=(
                            result
                            .collector_run_id
                        ),
                    )

                    fetch_duration_ms += (
                        getattr(
                            result,
                            "fetch_duration_ms",
                            0.0,
                        )
                    )

                    persist_duration_ms += (
                        getattr(
                            result,
                            "persist_duration_ms",
                            0.0,
                        )
                        + _elapsed_ms(
                            item_status_started_ns
                        )
                    )

                    results.append(
                        result
                    )

                    candidates_processed += (
                        result
                        .candidates_processed
                    )

                    processed_for_election += 1

            elif jobs:
                fetch_outcomes = []

                fetch_started_ns = (
                    time.perf_counter_ns()
                )

                local_state = (
                    threading.local()
                )

                def fetch_job(
                    target,
                ):
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

                    return _fetch_target(
                        target=target,
                        client=worker_client,
                    )

                max_workers = min(
                    workers,
                    len(jobs),
                )

                with ThreadPoolExecutor(
                    max_workers=(
                        max_workers
                    ),
                    thread_name_prefix=(
                        "ea20"
                    ),
                ) as executor:
                    futures = [
                        executor.submit(
                            fetch_job,
                            target,
                        )
                        for _, target
                        in jobs
                    ]

                    for (
                        (
                            item,
                            target,
                        ),
                        future,
                    ) in zip(
                        jobs,
                        futures,
                        strict=True,
                    ):
                        try:
                            fetched = (
                                future.result()
                            )

                            fetch_outcomes.append(
                                (
                                    item,
                                    target,
                                    fetched,
                                    None,
                                )
                            )

                        except Exception as exc:
                            fetch_outcomes.append(
                                (
                                    item,
                                    target,
                                    None,
                                    exc,
                                )
                            )

                fetch_duration_ms += (
                    _elapsed_ms(
                        fetch_started_ns
                    )
                )

                persist_jobs = [
                    (
                        item,
                        target,
                        fetched,
                    )
                    for (
                        item,
                        target,
                        fetched,
                        fetch_error,
                    )
                    in fetch_outcomes
                    if (
                        fetch_error
                        is None
                    )
                ]

                for (
                    item,
                    target,
                    _,
                    fetch_error,
                ) in fetch_outcomes:
                    if fetch_error is None:
                        continue

                    message = (
                        f"{type(fetch_error).__name__}: "
                        f"{fetch_error}"
                    )

                    mark_item_error(
                        item_id=item.id,
                        error_message=message,
                    )

                    errors.append(
                        (
                            f"{target.url} -> "
                            f"{message}"
                        )
                    )

                    failed += 1
                    failed_for_election += 1

                def persist_job(
                    item,
                    fetched,
                ):
                    result = (
                        _persist_fetched_target(
                            fetched=fetched,
                            settings=(
                                selected_settings
                            ),
                        )
                    )

                    mark_item_completed(
                        item_id=item.id,
                        status=result.status,
                        collector_run_id=(
                            result
                            .collector_run_id
                        ),
                    )

                    return result

                if persist_jobs:
                    persist_started_ns = (
                        time.perf_counter_ns()
                    )

                    with ThreadPoolExecutor(
                        max_workers=min(
                            workers,
                            len(
                                persist_jobs
                            ),
                        ),
                        thread_name_prefix=(
                            "ea20-db"
                        ),
                    ) as executor:
                        persist_futures = [
                            executor.submit(
                                persist_job,
                                item,
                                fetched,
                            )
                            for (
                                item,
                                _,
                                fetched,
                            )
                            in persist_jobs
                        ]

                        for (
                            (
                                item,
                                target,
                                _,
                            ),
                            future,
                        ) in zip(
                            persist_jobs,
                            persist_futures,
                            strict=True,
                        ):
                            try:
                                result = (
                                    future.result()
                                )

                            except Exception as exc:
                                message = (
                                    f"{type(exc).__name__}: "
                                    f"{exc}"
                                )

                                mark_item_error(
                                    item_id=item.id,
                                    error_message=message,
                                )

                                errors.append(
                                    (
                                        f"{target.url} -> "
                                        f"{message}"
                                    )
                                )

                                failed += 1
                                failed_for_election += 1

                                continue

                            results.append(
                                result
                            )

                            candidates_processed += (
                                result
                                .candidates_processed
                            )

                            processed_for_election += 1

                    persist_duration_ms += (
                        _elapsed_ms(
                            persist_started_ns
                        )
                    )

        refreshed = (
            refresh_batch_progress(
                batch_id=batch.id
            )
        )

        state_committed = False

        if refreshed.status in {
            "ready",
            "completed",
        }:
            if (
                refreshed.status
                == "ready"
            ):
                refreshed = (
                    mark_batch_completed(
                        batch_id=batch.id
                    )
                )

            # Important:
            # batch is marked completed
            # before EA14 checkpoint.
            #
            # If checkpoint persistence
            # fails, next execution can
            # recover and try again.
            _commit_ea14_state(
                election
            )

            committed += 1
            data_committed += 1
            state_committed = True

        summaries.append(
            BatchElectionSummary(
                election_code=(
                    election
                    .election_code
                ),
                batch_id=(
                    refreshed.id
                ),
                batch_status=(
                    refreshed.status
                ),
                total_targets=(
                    refreshed
                    .total_targets
                ),
                completed_targets=(
                    refreshed
                    .completed_targets
                ),
                processed_this_run=(
                    processed_for_election
                ),
                failed_this_run=(
                    failed_for_election
                ),
                state_committed=(
                    state_committed
                ),
            )
        )

    return BatchedIngestResult(
        execute=True,
        batch_size=batch_size,
        workers=workers,
        planned_targets=(
            planned_targets
        ),
        selected_targets=(
            selected_target_count
        ),
        processed_targets=(
            len(results)
        ),
        failed_targets=failed,
        state_updates_committed=(
            committed
        ),
        data_updates_committed=(
            data_committed
        ),
        planner=planner,
        elections=tuple(
            summaries
        ),
        results=tuple(
            results
        ),
        errors=tuple(
            errors
        ),
        duration_ms=(
            _elapsed_ms(
                run_started_ns
            )
        ),
        planner_duration_ms=(
            planner_duration_ms
        ),
        fetch_duration_ms=(
            round(
                fetch_duration_ms,
                3,
            )
        ),
        persist_duration_ms=(
            round(
                persist_duration_ms,
                3,
            )
        ),
        candidates_processed=(
            candidates_processed
        ),
    )


def _build_output(
    result: BatchedIngestResult,
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

        "planned_targets":
            result.planned_targets,

        "selected_targets":
            result.selected_targets,

        "processed_targets":
            result.processed_targets,

        "failed_targets":
            result.failed_targets,

        "state_updates_committed":
            result
            .state_updates_committed,

        "data_updates_committed":
            result
            .data_updates_committed,

        "timings": {
            "duration_ms":
                result.duration_ms,

            "planner_duration_ms":
                result
                .planner_duration_ms,

            "fetch_duration_ms":
                result
                .fetch_duration_ms,

            "persist_duration_ms":
                result
                .persist_duration_ms,

            "candidates_processed":
                result
                .candidates_processed,
        },

        "batches": [
            {
                "election_code":
                    item.election_code,

                "batch_id":
                    item.batch_id,

                "status":
                    item.batch_status,

                "total_targets":
                    item.total_targets,

                "completed_targets":
                    item.completed_targets,

                "processed_this_run":
                    item
                    .processed_this_run,

                "failed_this_run":
                    item
                    .failed_this_run,

                "state_committed":
                    item
                    .state_committed,
            }
            for item in (
                result.elections
            )
        ],

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
                    item
                    .collector_run_id,

                "tse_idg":
                    item.tse_idg,

                "snapshots_created":
                    item
                    .snapshots_created,

                "candidates_processed":
                    item
                    .candidates_processed,

                "timings": {
                    "cache_lookup_duration_ms":
                        item
                        .cache_lookup_duration_ms,

                    "http_duration_ms":
                        item
                        .http_duration_ms,

                    "parse_duration_ms":
                        item
                        .parse_duration_ms,

                    "fetch_duration_ms":
                        item
                        .fetch_duration_ms,

                    "persist_duration_ms":
                        item
                        .persist_duration_ms,

                    "target_duration_ms":
                        item
                        .target_duration_ms,
                },
            }
            for item in result.results
        ],

        "errors":
            list(
                result.errors
            ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Persistent batched "
            "TSE EA20 collector."
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

    result = run_batched_ingest(
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


if __name__ == "__main__":
    main()