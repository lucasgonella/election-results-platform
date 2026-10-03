from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Callable

from .repository import get_connection
from .static_exporter import (
    load_latest_result,
    write_json_atomic,
)


OFFICE_SLUGS = {
    1: "president",
    3: "governor",
    5: "senator",
    6: "federal-deputy",
    7: "state-deputy",
    8: "district-deputy",
}


@dataclass(frozen=True, slots=True)
class StaticExportTarget:
    scope_code: str
    office_code: int


def list_export_targets(
    *,
    environment: str,
    connection_factory: Callable = get_connection,
) -> tuple[StaticExportTarget, ...]:

    with connection_factory() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT
                    s.code,
                    o.tse_code

                FROM scope_snapshots ss

                JOIN elections e
                    ON e.id = ss.election_id

                JOIN scopes s
                    ON s.id = ss.scope_id

                JOIN offices o
                    ON o.id = ss.office_id

                WHERE e.environment = %s

                ORDER BY
                    o.tse_code,
                    s.code
                """,
                (environment,),
            )

            rows = cursor.fetchall()

    return tuple(
        StaticExportTarget(
            scope_code=row[0],
            office_code=row[1],
        )
        for row in rows
    )


def result_relative_path(
    target: StaticExportTarget,
) -> Path:

    try:
        office_slug = OFFICE_SLUGS[
            target.office_code
        ]
    except KeyError as exc:
        raise ValueError(
            "Unsupported office code for "
            f"static publishing: "
            f"{target.office_code}"
        ) from exc

    return (
        Path(target.scope_code.lower())
        / f"{office_slug}.json"
    )


def build_static_site(
    *,
    environment: str,
    output_dir: Path,
) -> dict:

    targets = list_export_targets(
        environment=environment,
    )

    if not targets:
        raise RuntimeError(
            "No persisted results found for "
            f"environment {environment}."
        )

    manifest_results = []
    total_candidates = 0

    for target in targets:
        payload = load_latest_result(
            environment=environment,
            scope_code=target.scope_code,
            office_code=target.office_code,
        )

        relative_path = result_relative_path(
            target
        )

        write_json_atomic(
            payload,
            output_dir / relative_path,
        )

        candidate_count = (
            payload["candidate_count"]
        )

        total_candidates += candidate_count

        manifest_results.append(
            {
                "scope": (
                    payload["scope"]["code"]
                ),
                "scope_type": (
                    payload["scope"]["type"]
                ),
                "uf": (
                    payload["scope"]["uf"]
                ),
                "office": (
                    payload["office"]["code"]
                ),
                "office_name": (
                    payload["office"]["name"]
                ),
                "election_code": (
                    payload["election"]["code"]
                ),
                "round": (
                    payload["election"]["round"]
                ),
                "candidate_count":
                    candidate_count,
                "tse_idg": (
                    payload["snapshot"][
                        "tse_idg"
                    ]
                ),
                "captured_at": (
                    payload["snapshot"][
                        "captured_at"
                    ]
                ),
                "path": (
                    relative_path
                    .as_posix()
                ),
            }
        )

    generated_at = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    manifest = {
        "schema_version": 1,
        "environment": environment,
        "generated_at": generated_at,
        "result_count": len(
            manifest_results
        ),
        "candidate_count":
            total_candidates,
        "results": manifest_results,
    }

    write_json_atomic(
        manifest,
        output_dir / "manifest.json",
    )

    version = {
        "schema_version": 1,
        "environment": environment,
        "generated_at": generated_at,
    }

    write_json_atomic(
        version,
        output_dir / "version.json",
    )

    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the complete static "
            "election results data bundle."
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
        "--output-dir",
        required=True,
        type=Path,
    )

    args = parser.parse_args()

    manifest = build_static_site(
        environment=args.environment,
        output_dir=args.output_dir,
    )

    print(
        json.dumps(
            {
                "status": "ok",
                "environment":
                    args.environment,
                "exported_targets":
                    manifest["result_count"],
                "candidate_count":
                    manifest[
                        "candidate_count"
                    ],
                "manifest": str(
                    args.output_dir
                    / "manifest.json"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())