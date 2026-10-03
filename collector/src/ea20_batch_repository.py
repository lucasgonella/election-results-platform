from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .discovery import ElectionTarget
from .repository import get_connection


@dataclass(frozen=True, slots=True)
class EA20Batch:
    id: int

    environment: str
    cycle: str

    election_code: int
    round_number: int

    ea14_tse_idg: int | None
    ea14_payload_sha256: str
    ea14_source_url: str

    status: str

    total_targets: int
    completed_targets: int

    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class EA20BatchItem:
    id: int
    batch_id: int

    scope_code: str
    office_code: int
    office_name: str

    source_url: str

    status: str
    attempts: int

    collector_run_id: int | None
    last_error: str | None


def _row_to_batch(
    row,
) -> EA20Batch:
    return EA20Batch(
        id=row[0],
        environment=row[1],
        cycle=row[2],
        election_code=row[3],
        round_number=row[4],
        ea14_tse_idg=row[5],
        ea14_payload_sha256=row[6],
        ea14_source_url=row[7],
        status=row[8],
        total_targets=row[9],
        completed_targets=row[10],
        created_at=row[11],
        updated_at=row[12],
        completed_at=row[13],
    )


def _row_to_item(
    row,
) -> EA20BatchItem:
    return EA20BatchItem(
        id=row[0],
        batch_id=row[1],
        scope_code=row[2],
        office_code=row[3],
        office_name=row[4],
        source_url=row[5],
        status=row[6],
        attempts=row[7],
        collector_run_id=row[8],
        last_error=row[9],
    )


def prepare_batch(
    *,
    environment: str,
    cycle: str,
    election_code: int,
    round_number: int,
    ea14_tse_idg: int | None,
    ea14_payload_sha256: str,
    ea14_source_url: str,
    targets: Iterable[
        ElectionTarget
    ],
) -> EA20Batch:
    target_list = tuple(
        targets
    )

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                UPDATE ea20_batches
                SET
                    status = 'superseded',
                    updated_at = NOW()
                WHERE environment = %s
                  AND cycle = %s
                  AND election_code = %s
                  AND round_number = %s
                  AND status IN (
                      'pending',
                      'ready'
                  )
                  AND ea14_payload_sha256 <> %s
                """,
                (
                    environment,
                    cycle,
                    election_code,
                    round_number,
                    ea14_payload_sha256,
                ),
            )

            cursor.execute(
                """
                INSERT INTO ea20_batches (
                    environment,
                    cycle,
                    election_code,
                    round_number,

                    ea14_tse_idg,
                    ea14_payload_sha256,
                    ea14_source_url,

                    status
                )
                VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    'pending'
                )
                ON CONFLICT (
                    environment,
                    cycle,
                    election_code,
                    round_number,
                    ea14_payload_sha256
                )
                DO UPDATE SET
                    ea14_tse_idg =
                        EXCLUDED.ea14_tse_idg,

                    ea14_source_url =
                        EXCLUDED.ea14_source_url,

                    updated_at =
                        NOW()

                RETURNING
                    id,
                    environment,
                    cycle,
                    election_code,
                    round_number,
                    ea14_tse_idg,
                    ea14_payload_sha256,
                    ea14_source_url,
                    status,
                    total_targets,
                    completed_targets,
                    created_at,
                    updated_at,
                    completed_at
                """,
                (
                    environment,
                    cycle,
                    election_code,
                    round_number,
                    ea14_tse_idg,
                    ea14_payload_sha256,
                    ea14_source_url,
                ),
            )

            row = cursor.fetchone()

            if row is None:
                raise RuntimeError(
                    "Could not prepare EA20 batch."
                )

            batch_id = row[0]

            for target in target_list:
                cursor.execute(
                    """
                    INSERT INTO ea20_batch_items (
                        batch_id,

                        scope_code,
                        office_code,
                        office_name,

                        source_url
                    )
                    VALUES (
                        %s,
                        %s, %s, %s,
                        %s
                    )
                    ON CONFLICT (
                        batch_id,
                        source_url
                    )
                    DO NOTHING
                    """,
                    (
                        batch_id,
                        target.scope_code,
                        target.office_code,
                        target.office_name,
                        target.url,
                    ),
                )

            cursor.execute(
                """
                WITH item_counts AS (
                    SELECT
                        COUNT(*)::INTEGER
                            AS total_targets,

                        COUNT(*) FILTER (
                            WHERE status IN (
                                'success',
                                'not_modified'
                            )
                        )::INTEGER
                            AS completed_targets
                    FROM ea20_batch_items
                    WHERE batch_id = %s
                )
                UPDATE ea20_batches AS batch
                SET
                    total_targets =
                        item_counts.total_targets,

                    completed_targets =
                        item_counts.completed_targets,

                    status = CASE
                        WHEN batch.status IN (
                            'completed',
                            'superseded'
                        )
                            THEN batch.status

                        WHEN (
                            item_counts.total_targets
                            =
                            item_counts.completed_targets
                        )
                            THEN 'ready'

                        ELSE 'pending'
                    END,

                    updated_at = NOW()

                FROM item_counts
                WHERE batch.id = %s

                RETURNING
                    batch.id,
                    batch.environment,
                    batch.cycle,
                    batch.election_code,
                    batch.round_number,
                    batch.ea14_tse_idg,
                    batch.ea14_payload_sha256,
                    batch.ea14_source_url,
                    batch.status,
                    batch.total_targets,
                    batch.completed_targets,
                    batch.created_at,
                    batch.updated_at,
                    batch.completed_at
                """,
                (
                    batch_id,
                    batch_id,
                ),
            )

            row = cursor.fetchone()

            if row is None:
                raise RuntimeError(
                    "Could not refresh "
                    "EA20 batch."
                )

        connection.commit()

    return _row_to_batch(
        row
    )


def get_pending_items(
    *,
    batch_id: int,
    limit: int,
) -> tuple[
    EA20BatchItem,
    ...
]:
    if limit < 1:
        raise ValueError(
            "limit must be greater "
            "than zero."
        )

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    batch_id,
                    scope_code,
                    office_code,
                    office_name,
                    source_url,
                    status,
                    attempts,
                    collector_run_id,
                    last_error
                FROM ea20_batch_items
                WHERE batch_id = %s
                  AND status IN (
                      'pending',
                      'error'
                  )
                ORDER BY id
                LIMIT %s
                """,
                (
                    batch_id,
                    limit,
                ),
            )

            rows = cursor.fetchall()

    return tuple(
        _row_to_item(row)
        for row in rows
    )


def mark_item_completed(
    *,
    item_id: int,
    status: str,
    collector_run_id: int | None,
) -> EA20BatchItem:
    if status not in {
        "success",
        "not_modified",
    }:
        raise ValueError(
            "Completed item status must "
            "be success or not_modified."
        )

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE ea20_batch_items
                SET
                    status = %s,

                    attempts =
                        attempts + 1,

                    collector_run_id = %s,

                    last_error = NULL,

                    processed_at = NOW(),
                    updated_at = NOW()

                WHERE id = %s

                RETURNING
                    id,
                    batch_id,
                    scope_code,
                    office_code,
                    office_name,
                    source_url,
                    status,
                    attempts,
                    collector_run_id,
                    last_error
                """,
                (
                    status,
                    collector_run_id,
                    item_id,
                ),
            )

            row = cursor.fetchone()

            if row is None:
                raise RuntimeError(
                    "Could not complete "
                    "EA20 batch item."
                )

        connection.commit()

    return _row_to_item(
        row
    )


def mark_item_error(
    *,
    item_id: int,
    error_message: str,
) -> EA20BatchItem:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE ea20_batch_items
                SET
                    status = 'error',

                    attempts =
                        attempts + 1,

                    last_error = %s,

                    updated_at = NOW()

                WHERE id = %s

                RETURNING
                    id,
                    batch_id,
                    scope_code,
                    office_code,
                    office_name,
                    source_url,
                    status,
                    attempts,
                    collector_run_id,
                    last_error
                """,
                (
                    error_message,
                    item_id,
                ),
            )

            row = cursor.fetchone()

            if row is None:
                raise RuntimeError(
                    "Could not mark "
                    "EA20 batch item error."
                )

        connection.commit()

    return _row_to_item(
        row
    )


def refresh_batch_progress(
    *,
    batch_id: int,
) -> EA20Batch:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH item_counts AS (
                    SELECT
                        COUNT(*)::INTEGER
                            AS total_targets,

                        COUNT(*) FILTER (
                            WHERE status IN (
                                'success',
                                'not_modified'
                            )
                        )::INTEGER
                            AS completed_targets
                    FROM ea20_batch_items
                    WHERE batch_id = %s
                )
                UPDATE ea20_batches AS batch
                SET
                    total_targets =
                        item_counts.total_targets,

                    completed_targets =
                        item_counts.completed_targets,

                    status = CASE
                        WHEN batch.status IN (
                            'completed',
                            'superseded'
                        )
                            THEN batch.status

                        WHEN (
                            item_counts.total_targets
                            =
                            item_counts.completed_targets
                        )
                            THEN 'ready'

                        ELSE 'pending'
                    END,

                    updated_at = NOW()

                FROM item_counts
                WHERE batch.id = %s

                RETURNING
                    batch.id,
                    batch.environment,
                    batch.cycle,
                    batch.election_code,
                    batch.round_number,
                    batch.ea14_tse_idg,
                    batch.ea14_payload_sha256,
                    batch.ea14_source_url,
                    batch.status,
                    batch.total_targets,
                    batch.completed_targets,
                    batch.created_at,
                    batch.updated_at,
                    batch.completed_at
                """,
                (
                    batch_id,
                    batch_id,
                ),
            )

            row = cursor.fetchone()

            if row is None:
                raise RuntimeError(
                    "Could not refresh "
                    "EA20 batch progress."
                )

        connection.commit()

    return _row_to_batch(
        row
    )


def mark_batch_completed(
    *,
    batch_id: int,
) -> EA20Batch:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE ea20_batches
                SET
                    status = 'completed',
                    completed_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
                  AND status = 'ready'

                RETURNING
                    id,
                    environment,
                    cycle,
                    election_code,
                    round_number,
                    ea14_tse_idg,
                    ea14_payload_sha256,
                    ea14_source_url,
                    status,
                    total_targets,
                    completed_targets,
                    created_at,
                    updated_at,
                    completed_at
                """,
                (
                    batch_id,
                ),
            )

            row = cursor.fetchone()

            if row is None:
                raise RuntimeError(
                    "EA20 batch is not ready "
                    "to be completed."
                )

        connection.commit()

    return _row_to_batch(
        row
    )
