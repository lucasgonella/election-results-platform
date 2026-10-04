from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import json
from typing import Any
from zoneinfo import ZoneInfo

from .tse_client import TseClient


BRAZIL_TZ = ZoneInfo("America/Sao_Paulo")


def as_int(value: Any) -> int | None:
    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    return int(value)


def as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    return Decimal(value.replace(",", "."))


def as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value

    if value is None:
        return None

    normalized = str(value).strip().lower()

    if normalized == "s":
        return True

    if normalized == "n":
        return False

    return None


def as_date(value: Any) -> date | None:
    if not value:
        return None

    return datetime.strptime(
        str(value),
        "%d/%m/%Y",
    ).date()


def as_datetime(
    date_value: Any,
    time_value: Any,
) -> datetime | None:
    if not date_value or not time_value:
        return None

    parsed = datetime.strptime(
        f"{date_value} {time_value}",
        "%d/%m/%Y %H:%M:%S",
    )

    return parsed.replace(tzinfo=BRAZIL_TZ)


@dataclass(frozen=True, slots=True)
class CandidateResult:
    tse_candidate_seq: int
    display_order: int | None

    ballot_number: int | None

    name: str
    ballot_name: str | None

    birth_date: date | None

    party_number: int | None
    party_acronym: str | None
    party_name: str | None

    alliance_name: str | None

    candidate_status: str | None
    result_status: str | None
    elected: bool | None

    votes: int
    vote_percentage: Decimal | None

    running_mates: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class SeatAllocation:
    number: int | None
    name: str
    kind: str | None
    composition: str | None
    seats: int | None
    parties: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class OfficeResult:
    code: int
    name: str
    seats: int | None
    electoral_quotient: int | None
    seat_allocations: tuple[
        SeatAllocation,
        ...
    ]
    candidates: tuple[CandidateResult, ...]


@dataclass(frozen=True, slots=True)
class ScopeStats:
    sections_total: int | None
    sections_totalized: int | None
    sections_percentage: Decimal | None

    electorate_total: int | None
    electorate_totalized: int | None

    turnout: int | None
    turnout_percentage: Decimal | None

    abstentions: int | None
    abstention_percentage: Decimal | None

    votes_total: int | None
    candidate_valid_votes: int | None
    valid_votes: int | None

    blank_votes: int | None
    null_votes: int | None


@dataclass(frozen=True, slots=True)
class ParsedResult:
    election_code: int
    round_number: int

    scope_type: str
    scope_code: str

    tse_idg: int

    generated_at: datetime | None
    totalized_at: datetime | None

    stats: ScopeStats

    offices: tuple[OfficeResult, ...]

    mathematical_definition: str | None = None
    totalization_final: bool | None = None


def parse_candidate(
    candidate: dict[str, Any],
    party: dict[str, Any],
    alliance: dict[str, Any],
) -> CandidateResult:
    tse_candidate_seq = as_int(
        candidate.get("sqcand")
    )

    if tse_candidate_seq is None:
        raise ValueError(
            "Candidate without sqcand in TSE payload."
        )

    running_mates: list[dict[str, Any]] = []

    for running_mate in candidate.get("vs", []):
        running_mates.append(
            {
                "type": running_mate.get("tp"),
                "tse_candidate_seq": as_int(
                    running_mate.get("sqcand")
                ),
                "name": running_mate.get("nm"),
                "ballot_name": running_mate.get("nmu"),
                "party_acronym": running_mate.get("sgp"),
            }
        )

    return CandidateResult(
        tse_candidate_seq=tse_candidate_seq,

        display_order=as_int(
            candidate.get("seq")
        ),

        ballot_number=as_int(
            candidate.get("n")
        ),

        name=str(
            candidate.get("nm") or ""
        ),

        ballot_name=candidate.get("nmu"),

        birth_date=as_date(
            candidate.get("dt")
        ),

        party_number=as_int(
            party.get("n")
        ),

        party_acronym=party.get("sg"),

        party_name=party.get("nm"),

        alliance_name=alliance.get("nm"),

        candidate_status=candidate.get("dvt"),

        result_status=candidate.get("st"),

        elected=as_bool(
            candidate.get("e")
        ),

        votes=as_int(
            candidate.get("vap")
        ) or 0,

        vote_percentage=as_decimal(
            candidate.get("pvapn")
            or candidate.get("pvap")
        ),

        running_mates=tuple(running_mates),
    )


def parse_office(
    office: dict[str, Any],
) -> OfficeResult:
    office_code = as_int(
        office.get("cd")
    )

    if office_code is None:
        raise ValueError(
            "Office without code in TSE payload."
        )

    candidates: list[CandidateResult] = []
    seat_allocations: list[
        SeatAllocation
    ] = []

    seen_candidates: set[int] = set()

    for alliance in office.get("agr", []):
        parties = tuple(
            {
                "number": as_int(
                    party.get("n")
                ),
                "acronym": party.get("sg"),
                "name": party.get("nm"),
            }
            for party
            in alliance.get("par", [])
        )

        seat_allocations.append(
            SeatAllocation(
                number=as_int(
                    alliance.get("n")
                ),
                name=str(
                    alliance.get("nm")
                    or ""
                ),
                kind=alliance.get("tp"),
                composition=(
                    alliance.get("com")
                ),
                seats=as_int(
                    alliance.get("vag")
                ),
                parties=parties,
            )
        )

        for party in alliance.get("par", []):
            for candidate in party.get("cand", []):
                parsed = parse_candidate(
                    candidate,
                    party,
                    alliance,
                )

                if parsed.tse_candidate_seq in seen_candidates:
                    raise ValueError(
                        "Duplicate candidate sqcand "
                        f"{parsed.tse_candidate_seq} "
                        f"in office {office_code}."
                    )

                seen_candidates.add(
                    parsed.tse_candidate_seq
                )

                candidates.append(parsed)

    candidates.sort(
        key=lambda candidate: (
            candidate.display_order is None,
            candidate.display_order
            if candidate.display_order is not None
            else 999999,
            candidate.name,
        )
    )

    return OfficeResult(
        code=office_code,

        name=str(
            office.get("nmn") or ""
        ),

        seats=as_int(
            office.get("nv")
        ),

        electoral_quotient=as_int(
            office.get("qe")
        ),

        seat_allocations=tuple(
            seat_allocations
        ),

        candidates=tuple(candidates),
    )


def parse_ea20(
    payload: dict[str, Any],
) -> ParsedResult:
    election_code = as_int(
        payload.get("ele")
    )

    round_number = as_int(
        payload.get("t")
    )

    tse_idg = as_int(
        payload.get("idg")
    )

    if election_code is None:
        raise ValueError(
            "EA20 payload without election code."
        )

    if round_number is None:
        raise ValueError(
            "EA20 payload without round number."
        )

    if tse_idg is None:
        raise ValueError(
            "EA20 payload without idg."
        )

    sections = payload.get("s") or {}
    electorate = payload.get("e") or {}
    votes = payload.get("v") or {}

    stats = ScopeStats(
        sections_total=as_int(
            sections.get("ts")
        ),

        sections_totalized=as_int(
            sections.get("st")
        ),

        sections_percentage=as_decimal(
            sections.get("pstn")
            or sections.get("pst")
        ),

        electorate_total=as_int(
            electorate.get("te")
        ),

        electorate_totalized=as_int(
            electorate.get("est")
        ),

        turnout=as_int(
            electorate.get("c")
        ),

        turnout_percentage=as_decimal(
            electorate.get("pcn")
            or electorate.get("pc")
        ),

        abstentions=as_int(
            electorate.get("a")
        ),

        abstention_percentage=as_decimal(
            electorate.get("pan")
            or electorate.get("pa")
        ),

        votes_total=as_int(
            votes.get("tv")
        ),

        candidate_valid_votes=as_int(
            votes.get("vvc")
        ),

        valid_votes=as_int(
            votes.get("vv")
        ),

        blank_votes=as_int(
            votes.get("vb")
        ),

        null_votes=as_int(
            votes.get("tvn")
        ),
    )

    offices = tuple(
        parse_office(office)
        for office in payload.get("carg", [])
    )

    return ParsedResult(
        election_code=election_code,
        round_number=round_number,

        scope_type=str(
            payload.get("tpabr") or ""
        ),

        scope_code=str(
            payload.get("cdabr") or ""
        ),

        tse_idg=tse_idg,

        generated_at=as_datetime(
            payload.get("dg"),
            payload.get("hg"),
        ),

        totalized_at=as_datetime(
            payload.get("dt"),
            payload.get("ht"),
        ),

        stats=stats,

        offices=offices,

        mathematical_definition=(
            str(
                payload.get("md")
                or ""
            )
            .strip()
            .lower()
            or None
        ),

        totalization_final=as_bool(
            payload.get("tf")
        ),
    )


def main() -> None:
    url = (
        "https://resultados-sim.tse.jus.br/"
        "simulado/simulado2026/"
        "ele2026/21272/dados/ac/"
        "ac-c0003-e021272-u.json"
    )

    client = TseClient()

    response = client.fetch_json(url)

    if response.payload is None:
        raise RuntimeError(
            "TSE returned no payload."
        )

    result = parse_ea20(
        response.payload
    )

    output: dict[str, Any] = {
        "election": result.election_code,
        "round": result.round_number,
        "scope_type": result.scope_type,
        "scope": result.scope_code,
        "idg": result.tse_idg,

        "generated_at": (
            result.generated_at.isoformat()
            if result.generated_at
            else None
        ),

        "sections": {
            "total": result.stats.sections_total,
            "totalized": result.stats.sections_totalized,
            "percentage": (
                str(result.stats.sections_percentage)
                if result.stats.sections_percentage
                is not None
                else None
            ),
        },

        "offices": [],
    }

    for office in result.offices:
        output["offices"].append(
            {
                "code": office.code,
                "name": office.name,
                "seats": office.seats,
                "candidate_count": len(
                    office.candidates
                ),
                "candidates": [
                    {
                        "order": candidate.display_order,
                        "number": candidate.ballot_number,
                        "name": candidate.name,
                        "party": candidate.party_acronym,
                        "votes": candidate.votes,
                        "percentage": (
                            str(
                                candidate.vote_percentage
                            )
                            if candidate.vote_percentage
                            is not None
                            else None
                        ),
                        "status": candidate.result_status,
                    }
                    for candidate
                    in office.candidates[:5]
                ],
            }
        )

    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
