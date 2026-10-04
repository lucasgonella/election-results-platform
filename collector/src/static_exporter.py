from __future__ import annotations

import argparse
from contextlib import nullcontext
from datetime import date, datetime
from decimal import Decimal
import json
import os
from pathlib import Path
from typing import Any, Callable

from .repository import get_connection


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    return value


def load_latest_result(
    *,
    environment: str,
    scope_code: str,
    office_code: int,
    connection_factory: Callable = get_connection,
    connection=None,
) -> dict[str, Any]:

    connection_context = (
        nullcontext(connection)
        if connection is not None
        else connection_factory()
    )

    with connection_context as database:
        with database.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    ss.id,
                    e.tse_election_code,
                    e.round_number,

                    s.code,
                    s.scope_type,
                    s.uf,

                    o.tse_code,
                    o.name,
                    o.seats,

                    ss.tse_idg,
                    ss.generated_at,
                    ss.totalized_at,

                    ss.sections_total,
                    ss.sections_totalized,
                    ss.sections_percentage,

                    ss.electorate_total,
                    ss.electorate_totalized,

                    ss.turnout,
                    ss.turnout_percentage,

                    ss.abstentions,
                    ss.abstention_percentage,

                    ss.votes_total,
                    ss.candidate_valid_votes,
                    ss.valid_votes,

                    ss.blank_votes,
                    ss.null_votes,

                    ss.captured_at

                FROM scope_snapshots ss

                JOIN elections e
                    ON e.id = ss.election_id

                JOIN scopes s
                    ON s.id = ss.scope_id

                JOIN offices o
                    ON o.id = ss.office_id

                WHERE e.environment = %s
                  AND s.code = %s
                  AND o.tse_code = %s

                ORDER BY
                    ss.captured_at DESC,
                    ss.id DESC

                LIMIT 1
                """,
                (
                    environment,
                    scope_code,
                    office_code,
                ),
            )

            snapshot = cursor.fetchone()

            if snapshot is None:
                raise RuntimeError(
                    "No result snapshot found for "
                    f"{environment}/"
                    f"{scope_code}/"
                    f"{office_code}."
                )

            snapshot_id = snapshot[0]

            cursor.execute(
                """
                SELECT
                    c.tse_candidate_seq,
                    c.display_order,
                    c.ballot_number,

                    c.name,
                    c.ballot_name,

                    c.party_number,
                    c.party_acronym,
                    c.party_name,

                    c.alliance_name,

                    crs.votes,
                    crs.vote_percentage,

                    crs.candidate_status,
                    crs.result_status,
                    crs.elected,

                    c.running_mates

                FROM candidate_result_snapshots crs

                JOIN candidates c
                    ON c.id = crs.candidate_id

                WHERE crs.scope_snapshot_id = %s

                ORDER BY
                    c.display_order NULLS LAST,
                    c.ballot_number NULLS LAST,
                    c.id
                """,
                (snapshot_id,),
            )

            candidate_rows = cursor.fetchall()

    candidates = [
        {
            "tse_candidate_seq": row[0],
            "display_order": row[1],
            "ballot_number": row[2],
            "name": row[3],
            "ballot_name": row[4],
            "party_number": row[5],
            "party_acronym": row[6],
            "party_name": row[7],
            "alliance_name": row[8],
            "votes": row[9],
            "vote_percentage": _json_value(
                row[10]
            ),
            "candidate_status": row[11],
            "result_status": row[12],
            "elected": row[13],
            "running_mates": row[14],
        }
        for row in candidate_rows
    ]

    return {
        "schema_version": 1,
        "environment": environment,

        "election": {
            "code": snapshot[1],
            "round": snapshot[2],
        },

        "scope": {
            "code": snapshot[3],
            "type": snapshot[4],
            "uf": snapshot[5],
        },

        "office": {
            "code": snapshot[6],
            "name": snapshot[7],
            "seats": snapshot[8],
        },

        "snapshot": {
            "tse_idg": snapshot[9],
            "generated_at": _json_value(
                snapshot[10]
            ),
            "totalized_at": _json_value(
                snapshot[11]
            ),
            "captured_at": _json_value(
                snapshot[26]
            ),

            "sections": {
                "total": snapshot[12],
                "totalized": snapshot[13],
                "percentage": _json_value(
                    snapshot[14]
                ),
            },

            "electorate": {
                "total": snapshot[15],
                "totalized": snapshot[16],
            },

            "turnout": {
                "total": snapshot[17],
                "percentage": _json_value(
                    snapshot[18]
                ),
            },

            "abstentions": {
                "total": snapshot[19],
                "percentage": _json_value(
                    snapshot[20]
                ),
            },

            "votes": {
                "total": snapshot[21],
                "candidate_valid": snapshot[22],
                "valid": snapshot[23],
                "blank": snapshot[24],
                "null": snapshot[25],
            },
        },

        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def write_json_atomic(
    payload: dict[str, Any],
    output_path: Path,
) -> None:

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = output_path.with_suffix(
        output_path.suffix + ".tmp"
    )

    temporary_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    temporary_path.replace(
        output_path
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Export the latest persisted "
            "election result to static JSON."
        )
    )

    parser.add_argument(
        "--environment",
        default=os.getenv(
            "TSE_ENVIRONMENT",
            "simulado2026",
        ),
    )

    parser.add_argument(
        "--scope",
        required=True,
    )

    parser.add_argument(
        "--office",
        required=True,
        type=int,
    )

    parser.add_argument(
        "--output",
        required=True,
        type=Path,
    )

    args = parser.parse_args()

    payload = load_latest_result(
        environment=args.environment,
        scope_code=args.scope.lower(),
        office_code=args.office,
    )

    write_json_atomic(
        payload,
        args.output,
    )

    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(
                    args.output
                ),
                "environment":
                    args.environment,
                "scope":
                    args.scope.lower(),
                "office":
                    args.office,
                "candidate_count":
                    payload[
                        "candidate_count"
                    ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())