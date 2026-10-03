from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .repository import get_connection


@dataclass(frozen=True, slots=True)
class BatchObservability:
    batch_id: int
    election_code: int
    round_number: int

    status: str
    ea14_tse_idg: int | None

    total_targets: int
    completed_targets: int

    pending_items: int
    success_items: int
    not_modified_items: int
    error_items: int

    updated_at: datetime

    @property
    def processed_items(
        self,
    ) -> int:
        return (
            self.success_items
            + self.not_modified_items
        )

    @property
    def progress_percentage(
        self,
    ) -> float:
        if self.total_targets == 0:
            return 100.0

        return round(
            (
                self.completed_targets
                / self.total_targets
            )
            * 100,
            2,
        )


@dataclass(frozen=True, slots=True)
class CollectorRunObservability:
    id: int
    status: str

    election_code: int | None
    scope_code: str | None
    office_code: int | None

    http_status: int | None
    tse_idg: int | None

    candidates_processed: int

    started_at: datetime
    finished_at: datetime | None

    error_message: str | None


@dataclass(frozen=True, slots=True)
class CollectorObservability:
    environment: str
    cycle: str

    batches: tuple[
        BatchObservability,
        ...
    ]

    ea14_states: int

    last_run: (
        CollectorRunObservability
        | None
    )

    @property
    def active_batches(
        self,
    ) -> int:
        return sum(
            1
            for batch in self.batches
            if batch.status in {
                "pending",
                "ready",
            }
        )

    @property
    def pending_items(
        self,
    ) -> int:
        return sum(
            batch.pending_items
            for batch in self.batches
        )

    @property
    def completed_items(
        self,
    ) -> int:
        return sum(
            batch.processed_items
            for batch in self.batches
        )

    @property
    def error_items(
        self,
    ) -> int:
        return sum(
            batch.error_items
            for batch in self.batches
        )

    @property
    def health(
        self,
    ) -> str:
        if self.error_items > 0:
            return "degraded"

        if (
            self.last_run is not None
            and self.last_run.status
            == "error"
        ):
            return "degraded"

        return "ok"


def _row_to_batch(
    row,
) -> BatchObservability:
    return BatchObservability(
        batch_id=row[0],
        election_code=row[1],
        round_number=row[2],
        status=row[3],
        ea14_tse_idg=row[4],
        total_targets=row[5],
        completed_targets=row[6],
        pending_items=row[7],
        success_items=row[8],
        not_modified_items=row[9],
        error_items=row[10],
        updated_at=row[11],
    )


def _row_to_run(
    row,
) -> CollectorRunObservability:
    return CollectorRunObservability(
        id=row[0],
        status=row[1],
        election_code=row[2],
        scope_code=row[3],
        office_code=row[4],
        http_status=row[5],
        tse_idg=row[6],
        candidates_processed=row[7],
        started_at=row[8],
        finished_at=row[9],
        error_message=row[10],
    )


def get_observability(
    *,
    environment: str,
    cycle: str,
) -> CollectorObservability:
    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                WITH latest_batches AS (
                    SELECT DISTINCT ON (
                        environment,
                        cycle,
                        election_code,
                        round_number
                    )
                        id,
                        election_code,
                        round_number,
                        status,
                        ea14_tse_idg,
                        total_targets,
                        completed_targets,
                        updated_at

                    FROM ea20_batches

                    WHERE environment = %s
                      AND cycle = %s
                      AND total_targets > 0

                    ORDER BY
                        environment,
                        cycle,
                        election_code,
                        round_number,
                        created_at DESC,
                        id DESC
                )

                SELECT
                    batch.id,
                    batch.election_code,
                    batch.round_number,
                    batch.status,
                    batch.ea14_tse_idg,
                    batch.total_targets,
                    batch.completed_targets,

                    COUNT(item.id) FILTER (
                        WHERE item.status = 'pending'
                    )::INTEGER
                        AS pending_items,

                    COUNT(item.id) FILTER (
                        WHERE item.status = 'success'
                    )::INTEGER
                        AS success_items,

                    COUNT(item.id) FILTER (
                        WHERE item.status = 'not_modified'
                    )::INTEGER
                        AS not_modified_items,

                    COUNT(item.id) FILTER (
                        WHERE item.status = 'error'
                    )::INTEGER
                        AS error_items,

                    batch.updated_at

                FROM latest_batches AS batch

                LEFT JOIN ea20_batch_items AS item
                    ON item.batch_id = batch.id

                GROUP BY
                    batch.id,
                    batch.election_code,
                    batch.round_number,
                    batch.status,
                    batch.ea14_tse_idg,
                    batch.total_targets,
                    batch.completed_targets,
                    batch.updated_at

                ORDER BY
                    batch.election_code
                """,
                (
                    environment,
                    cycle,
                ),
            )

            batch_rows = (
                cursor.fetchall()
            )

            cursor.execute(
                """
                SELECT COUNT(*)::INTEGER
                FROM ea14_state
                WHERE environment = %s
                  AND cycle = %s
                """,
                (
                    environment,
                    cycle,
                ),
            )

            ea14_row = cursor.fetchone()

            if ea14_row is None:
                raise RuntimeError(
                    "Could not read "
                    "EA14 state count."
                )

            ea14_states = ea14_row[0]

            cursor.execute(
                """
                SELECT
                    id,
                    status,
                    election_code,
                    scope_code,
                    office_code,
                    http_status,
                    tse_idg,
                    candidates_processed,
                    started_at,
                    finished_at,
                    error_message
                FROM collector_runs
                ORDER BY id DESC
                LIMIT 1
                """
            )

            last_run_row = (
                cursor.fetchone()
            )

    batches = tuple(
        _row_to_batch(row)
        for row in batch_rows
    )

    last_run = (
        _row_to_run(
            last_run_row
        )
        if last_run_row
        is not None
        else None
    )

    return CollectorObservability(
        environment=environment,
        cycle=cycle,
        batches=batches,
        ea14_states=ea14_states,
        last_run=last_run,
    )