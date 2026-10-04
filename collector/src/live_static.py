from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .discovery import ElectionTarget
from .parser import ParsedResult


def json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def validate_target(
    target: ElectionTarget,
    parsed: ParsedResult,
) -> None:
    if parsed.election_code != target.election_code:
        raise ValueError("Live EA20 election mismatch.")
    if parsed.round_number != target.round_number:
        raise ValueError("Live EA20 round mismatch.")
    if parsed.scope_code.lower() != target.scope_code.lower():
        raise ValueError("Live EA20 scope mismatch.")
    if tuple(o.code for o in parsed.offices) != (target.office_code,):
        raise ValueError("Live EA20 office mismatch.")


def static_payload(
    parsed: ParsedResult,
    *,
    environment: str,
    captured_at: datetime,
) -> dict[str, Any]:
    if len(parsed.offices) != 1:
        raise ValueError("Live result must contain exactly one office.")

    office = parsed.offices[0]
    stats = parsed.stats

    candidates = [
        {
            "tse_candidate_seq": c.tse_candidate_seq,
            "display_order": c.display_order,
            "ballot_number": c.ballot_number,
            "name": c.name,
            "ballot_name": c.ballot_name,
            "party_number": c.party_number,
            "party_acronym": c.party_acronym,
            "party_name": c.party_name,
            "alliance_name": c.alliance_name,
            "votes": c.votes,
            "vote_percentage": json_value(c.vote_percentage),
            "candidate_status": c.candidate_status,
            "result_status": c.result_status,
            "elected": c.elected,
            "running_mates": list(c.running_mates),
        }
        for c in office.candidates
    ]

    return {
        "schema_version": 1,
        "environment": environment,
        "election": {
            "code": parsed.election_code,
            "round": parsed.round_number,
        },
        "scope": {
            "code": parsed.scope_code,
            "type": parsed.scope_type,
            "uf": (
                parsed.scope_code.upper()
                if parsed.scope_type == "uf"
                and len(parsed.scope_code) == 2
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
            "generated_at": json_value(parsed.generated_at),
            "totalized_at": json_value(parsed.totalized_at),
            "captured_at": captured_at.isoformat(),
            "sections": {
                "total": stats.sections_total,
                "totalized": stats.sections_totalized,
                "percentage": json_value(stats.sections_percentage),
            },
            "electorate": {
                "total": stats.electorate_total,
                "totalized": stats.electorate_totalized,
            },
            "turnout": {
                "total": stats.turnout,
                "percentage": json_value(stats.turnout_percentage),
            },
            "abstentions": {
                "total": stats.abstentions,
                "percentage": json_value(stats.abstention_percentage),
            },
            "votes": {
                "total": stats.votes_total,
                "candidate_valid": stats.candidate_valid_votes,
                "valid": stats.valid_votes,
                "blank": stats.blank_votes,
                "null": stats.null_votes,
            },
        },
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def manifest_item(
    payload: dict[str, Any],
    relative_path: Path,
) -> dict[str, Any]:
    return {
        "scope": payload["scope"]["code"],
        "scope_type": payload["scope"]["type"],
        "uf": payload["scope"]["uf"],
        "office": payload["office"]["code"],
        "office_name": payload["office"]["name"],
        "election_code": payload["election"]["code"],
        "round": payload["election"]["round"],
        "candidate_count": payload["candidate_count"],
        "tse_idg": payload["snapshot"]["tse_idg"],
        "captured_at": payload["snapshot"]["captured_at"],
        "path": relative_path.as_posix(),
    }
