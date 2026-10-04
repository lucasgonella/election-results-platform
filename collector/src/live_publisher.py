from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil
import threading
from typing import Any

from .discovery import ElectionTarget
from .parser import ParsedResult, parse_ea20
from .planner import (
    build_collection_plan,
    build_ea14_url,
)
from .runtime import (
    RuntimeSettings,
    build_config_url,
    load_settings,
    select_supported_elections,
)
from .static_exporter import (
    write_json_atomic,
)
from .static_site_builder import (
    StaticExportTarget,
    result_relative_path,
)
from .tse_client import TseClient


DEFAULT_STATE_DIR = (
    "/var/lib/election-results-platform/live"
)
DEFAULT_WORKERS = 16
DEFAULT_EXPECTED_TARGETS = 137


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    return value


def static_payload_from_parsed(
    parsed: ParsedResult,
    *,
    captured_at: datetime,
) -> dict[str, Any]:
    if len(parsed.offices) != 1:
        raise ValueError(
            "Live result must contain exactly one office."
        )

    office = parsed.offices[0]

    candidates = [
        {
            "tse_candidate_seq":
                candidate.tse_candidate_seq,
            "display_order":
                candidate.display_order,
            "ballot_number":
                candidate.ballot_number,
            "name":
                candidate.name,
            "ballot_name":
                candidate.ballot_name,
            "party_number":
                candidate.party_number,
            "party_acronym":
                candidate.party_acronym,
            "party_name":
                candidate.party_name,
            "alliance_name":
                candidate.alliance_name,
            "votes":
                candidate.votes,
            "vote_percentage":
                _json_value(
                    candidate.vote_percentage
                ),
            "candidate_status":
                candidate.candidate_status,
            "result_status":
                candidate.result_status,
            "elected":
                candidate.elected,
            "running_mates":
                list(
                    candidate.running_mates
                ),
        }
        for candidate in office.candidates
    ]

    stats = parsed.stats

    return {
        "schema_version": 1,
        "environment": os.getenv(
            "TSE_ENVIRONMENT",
            "simulado2026",
        ),

        "election": {
            "code": parsed.election_code,
            "round": parsed.round_number,
        },

        "scope": {
            "code": parsed.scope_code,
            "type": parsed.scope_type,
            "uf": (
                parsed.scope_code.upper()
                if (
                    parsed.scope_type == "uf"
                    and len(parsed.scope_code) == 2
                )
                else None
            ),
        },

        "office": {
            "code": office.code,
            "name": office.name,
            "seats": office.seats,
        },

        "snapshot": {
            "tse_idg": parsed.tse_idg,
            "generated_at":
                _json_value(
                    parsed.generated_at
                ),
            "totalized_at":
                _json_value(
                    parsed.totalized_at
                ),
            "captured_at":
                captured_at.isoformat(),

            "sections": {
                "total":
                    stats.sections_total,
                "totalized":
                    stats.sections_totalized,
                "percentage":
                    _json_value(
                        stats.sections_percentage
                    ),
            },

            "electorate": {
                "total":
                    stats.electorate_total,
                "totalized":
                    stats.electorate_totalized,
            },

            "turnout": {
                "total":
                    stats.turnout,
                "percentage":
                    _json_value(
                        stats.turnout_percentage
                    ),
            },

            "abstentions": {
                "total":
                    stats.abstentions,
                "percentage":
                    _json_value(
                        stats.abstention_percentage
                    ),
            },

            "votes": {
                "total":
                    stats.votes_total,
                "candidate_valid":
                    stats.candidate_valid_votes,
                "valid":
                    stats.valid_votes,
                "blank":
                    stats.blank_votes,
                "null":
                    stats.null_votes,
            },
        },

        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def _validate_target(
    *,
    target: ElectionTarget,
    parsed: ParsedResult,
) -> None:
    if parsed.election_code != target.election_code:
        raise ValueError(
            "Live EA20 election mismatch."
        )

    if parsed.round_number != target.round_number:
        raise ValueError(
            "Live EA20 round mismatch."
        )

    if (
        parsed.scope_code.lower()
        != target.scope_code.lower()
    ):
        raise ValueError(
            "Live EA20 scope mismatch."
        )

    office_codes = tuple(
        office.code
        for office in parsed.offices
    )

    if office_codes != (
        target.office_code,
    ):
        raise ValueError(
            "Live EA20 office mismatch."
        )


def _manifest_item(
    *,
    payload: dict[str, Any],
    relative_path: Path,
) -> dict[str, Any]:
    return {
        "scope":
            payload["scope"]["code"],
        "scope_type":
            payload["scope"]["type"],
        "uf":
            payload["scope"]["uf"],
        "office":
            payload["office"]["code"],
        "office_name":
            payload["office"]["name"],
        "election_code":
            payload["election"]["code"],
        "round":
            payload["election"]["round"],
        "candidate_count":
            payload["candidate_count"],
        "tse_idg":
            payload["snapshot"]["tse_idg"],
        "captured_at":
            payload["snapshot"]["captured_at"],
        "path":
            relative_path.as_posix(),
    }


def _load_json(
    path: Path,
    default,
):
    if not path.is_file():
        return default

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def _write_json(
    path: Path,
    payload,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = (
        path.with_suffix(
            path.suffix + ".tmp"
        )
    )

    temporary.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    temporary.replace(path)


def _state_paths() -> tuple[
    Path,
    Path,
    Path,
]:
    root = Path(
        os.getenv(
            "LIVE_PUBLISH_STATE_DIR",
            DEFAULT_STATE_DIR,
        )
    )

    return (
        root / "state",
        root / "pending",
        root / "stage",
    )


def _fetch_targets(
    *,
    targets: tuple[
        ElectionTarget,
        ...
    ],
    target_state: dict[str, Any],
    workers: int,
) -> tuple[
    list[
        tuple[
            ElectionTarget,
            object,
            ParsedResult | None,
        ]
    ],
    list[str],
]:
    local_state = threading.local()

    def client() -> TseClient:
        selected = getattr(
            local_state,
            "client",
            None,
        )

        if selected is None:
            selected = TseClient()
            local_state.client = selected

        return selected

    def job(target: ElectionTarget):
        cached = target_state.get(
            target.url,
            {},
        )

        response = client().fetch_json(
            target.url,
            etag=cached.get("etag"),
            last_modified=(
                cached.get(
                    "last_modified"
                )
            ),
        )

        if response.status_code == 304:
            return (
                target,
                response,
                None,
            )

        if response.payload is None:
            raise RuntimeError(
                "Live EA20 returned no payload."
            )

        parsed = parse_ea20(
            response.payload
        )

        _validate_target(
            target=target,
            parsed=parsed,