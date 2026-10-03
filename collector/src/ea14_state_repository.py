from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from .repository import get_connection
from .tse_client import TseFetchResult


@dataclass(frozen=True, slots=True)
class StoredEA14State:
    id: int

    environment: str
    cycle: str

    election_code: int
    round_number: int

    tse_idg: int | None

    source_url: str

    etag: str | None
    last_modified: str | None
    payload_sha256: str | None

    payload: dict[str, Any]

    captured_at: datetime


def _as_int(
    value: Any,
) -> int | None:
    if value is None:
        return None

    normalized = str(value).strip()

    if not normalized:
        return None

    return int(normalized)


def _row_to_state(
    row: tuple[Any, ...],
) -> StoredEA14State:
    return StoredEA14State(
        id=row[0],
        environment=row[1],
        cycle=row[2],
        election_code=row[3],
        round_number=row[4],
        tse_idg=row[5],
        source_url=row[6],
        etag=row[7],
        last_modified=row[8],
        payload_sha256=row[9],
        payload=row[10],
        captured_at=row[11],
    )


def get_ea14_state(
    *,
    environment: str,
    cycle: str,
    election_code: int,
    round_number: int,
) -> StoredEA14State | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    environment,
                    cycle,
                    election_code,
                    round_number,
                    tse_idg,
                    source_url,
                    etag,
                    last_modified,
                    payload_sha256,
                    payload,
                    captured_at
                FROM ea14_state
                WHERE environment = %s
                  AND cycle = %s
                  AND election_code = %s
                  AND round_number = %s
                """,
                (
                    environment,
                    cycle,
                    election_code,
                    round_number,
                ),
            )

            row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_state(
        row
    )


def save_ea14_state(
    *,
    environment: str,
    cycle: str,
    election_code: int,
    round_number: int,
    fetch_result: TseFetchResult,
    payload: dict[str, Any],
) -> StoredEA14State:
    payload_election_code = _as_int(
        payload.get("ele")
    )

    if (
        payload_election_code
        is not None
        and payload_election_code
        != election_code
    ):
        raise ValueError(
            "EA14 election mismatch: "
            f"expected={election_code}, "
            f"payload={payload_election_code}."
        )

    payload_round = _as_int(
        payload.get("t")
    )

    if (
        payload_round is not None
        and payload_round
        != round_number
    ):
        raise ValueError(
            "EA14 round mismatch: "
            f"expected={round_number}, "
            f"payload={payload_round}."
        )

    tse_idg = _as_int(
        payload.get("idg")
    )

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO ea14_state (
                    environment,
                    cycle,
                    election_code,
                    round_number,

                    tse_idg,

                    source_url,

                    etag,
                    last_modified,
                    payload_sha256,

                    payload,

                    captured_at
                )
                VALUES (
                    %s, %s, %s, %s,
                    %s,
                    %s,
                    %s, %s, %s,
                    %s,
                    NOW()
                )
                ON CONFLICT (
                    environment,
                    cycle,
                    election_code,
                    round_number
                )
                DO UPDATE SET
                    tse_idg =
                        EXCLUDED.tse_idg,

                    source_url =
                        EXCLUDED.source_url,

                    etag =
                        EXCLUDED.etag,

                    last_modified =
                        EXCLUDED.last_modified,

                    payload_sha256 =
                        EXCLUDED.payload_sha256,

                    payload =
                        EXCLUDED.payload,

                    captured_at =
                        NOW()

                RETURNING
                    id,
                    environment,
                    cycle,
                    election_code,
                    round_number,
                    tse_idg,
                    source_url,
                    etag,
                    last_modified,
                    payload_sha256,
                    payload,
                    captured_at
                """,
                (
                    environment,
                    cycle,
                    election_code,
                    round_number,

                    tse_idg,

                    fetch_result.url,

                    fetch_result.etag,
                    fetch_result.last_modified,
                    fetch_result.sha256,

                    Jsonb(payload),
                ),
            )

            row = cursor.fetchone()

            if row is None:
                raise RuntimeError(
                    "Could not save EA14 state."
                )

        connection.commit()

    return _row_to_state(
        row
    )
