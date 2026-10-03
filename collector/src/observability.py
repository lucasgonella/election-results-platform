from __future__ import annotations

import argparse
import json

from .observability_repository import (
    CollectorObservability,
    get_observability,
)
from .runtime import load_settings


METRICS = {
    "health_code",
    "active_batches",
    "pending_items",
    "completed_items",
    "error_items",
    "ea14_states",
    "last_run_status",
}


def _metric_value(
    status: CollectorObservability,
    metric: str,
):
    if metric == "health_code":
        return (
            1
            if status.health == "ok"
            else 0
        )

    if metric == "active_batches":
        return status.active_batches

    if metric == "pending_items":
        return status.pending_items

    if metric == "completed_items":
        return status.completed_items

    if metric == "error_items":
        return status.error_items

    if metric == "ea14_states":
        return status.ea14_states

    if metric == "last_run_status":
        if status.last_run is None:
            return "none"

        return status.last_run.status

    raise ValueError(
        f"Unknown metric: {metric}"
    )


def _build_output(
    status: CollectorObservability,
) -> dict:
    return {
        "health":
            status.health,

        "health_code": (
            1
            if status.health == "ok"
            else 0
        ),

        "environment":
            status.environment,

        "cycle":
            status.cycle,

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

        "batches": [
            {
                "batch_id":
                    batch.batch_id,

                "election_code":
                    batch.election_code,

                "round_number":
                    batch.round_number,

                "status":
                    batch.status,

                "ea14_tse_idg":
                    batch.ea14_tse_idg,

                "total_targets":
                    batch.total_targets,

                "completed_targets":
                    batch
                    .completed_targets,

                "pending_items":
                    batch.pending_items,

                "success_items":
                    batch.success_items,

                "not_modified_items":
                    batch
                    .not_modified_items,

                "error_items":
                    batch.error_items,

                "progress_percentage":
                    batch
                    .progress_percentage,

                "updated_at":
                    batch.updated_at
                    .isoformat(),
            }
            for batch in status.batches
        ],

        "last_run": (
            {
                "id":
                    status.last_run.id,

                "status":
                    status.last_run.status,

                "election_code":
                    status.last_run
                    .election_code,

                "scope_code":
                    status.last_run
                    .scope_code,

                "office_code":
                    status.last_run
                    .office_code,

                "http_status":
                    status.last_run
                    .http_status,

                "tse_idg":
                    status.last_run
                    .tse_idg,

                "candidates_processed":
                    status.last_run
                    .candidates_processed,

                "started_at":
                    status.last_run
                    .started_at
                    .isoformat(),

                "finished_at": (
                    status.last_run
                    .finished_at
                    .isoformat()

                    if status.last_run
                    .finished_at
                    is not None

                    else None
                ),

                "error_message":
                    status.last_run
                    .error_message,
            }
            if status.last_run
            is not None
            else None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Collector operational "
            "observability."
        )
    )

    parser.add_argument(
        "--metric",
        choices=sorted(
            METRICS
        ),
    )

    args = parser.parse_args()

    settings = load_settings()

    status = get_observability(
        environment=(
            settings.environment
        ),
        cycle=(
            settings.cycle
        ),
    )

    if args.metric:
        print(
            _metric_value(
                status,
                args.metric,
            )
        )

        return

    print(
        json.dumps(
            _build_output(
                status
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
