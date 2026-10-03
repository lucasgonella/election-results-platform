from __future__ import annotations

from dataclasses import dataclass
from typing import Any


EXTERIOR_SCOPE = "zz"
BRAZIL_SCOPE = "br"
DF_SCOPE = "df"

PRESIDENT_OFFICE = 1
STATE_DEPUTY_OFFICE = 7
DISTRICT_DEPUTY_OFFICE = 8

SUPPORTED_ELECTION_TYPES = frozenset({
    1,
    8,
})


@dataclass(frozen=True, slots=True)
class Scope:
    scope_type: str
    code: str
    update_date: str | None
    update_time: str | None

    @property
    def is_brazil(self) -> bool:
        return self.code == BRAZIL_SCOPE

    @property
    def is_exterior(self) -> bool:
        return self.code == EXTERIOR_SCOPE

    @property
    def is_federative_unit(self) -> bool:
        return (
            self.scope_type == "uf"
            and not self.is_exterior
        )


@dataclass(frozen=True, slots=True)
class Office:
    code: int
    name: str


@dataclass(frozen=True, slots=True)
class ElectionDefinition:
    election_code: int
    cycle: str
    round_number: int
    election_type: int | None
    name: str
    offices: tuple[Office, ...]


@dataclass(frozen=True, slots=True)
class ElectionTarget:
    election_code: int
    cycle: str
    round_number: int

    scope_code: str

    office_code: int
    office_name: str

    url: str


def _as_int(value: Any) -> int | None:
    if value is None:
        return None

    normalized = str(value).strip()

    if not normalized:
        return None

    return int(normalized)


def parse_ea14_scopes(
    payload: dict[str, Any],
) -> tuple[Scope, ...]:
    scopes: list[Scope] = []

    for item in payload.get("abr", []):
        scope_type = str(
            item.get("tpabr") or ""
        ).lower()

        code = str(
            item.get("cdabr") or ""
        ).lower()

        if not code:
            continue

        scopes.append(
            Scope(
                scope_type=scope_type,
                code=code,
                update_date=item.get("dt"),
                update_time=item.get("ht"),
            )
        )

    return tuple(scopes)


def parse_election_config(
    payload: dict[str, Any],
) -> tuple[ElectionDefinition, ...]:
    definitions: list[ElectionDefinition] = []

    for election_group in payload.get("pl", []):
        cycle = str(
            election_group.get("c") or ""
        )

        for election in election_group.get("e", []):
            election_code = _as_int(
                election.get("cd")
            )

            round_number = _as_int(
                election.get("t")
            )

            if election_code is None:
                continue

            if round_number is None:
                continue

            offices_by_code: dict[int, Office] = {}

            for coverage in election.get("abr", []):
                for office_data in coverage.get(
                    "cp",
                    [],
                ):
                    office_code = _as_int(
                        office_data.get("cd")
                    )

                    if office_code is None:
                        continue

                    office_name = str(
                        office_data.get("ds")
                        or office_data.get("nm")
                        or ""
                    )

                    offices_by_code[office_code] = Office(
                        code=office_code,
                        name=office_name,
                    )

            definitions.append(
                ElectionDefinition(
                    election_code=election_code,
                    cycle=cycle,
                    round_number=round_number,
                    election_type=_as_int(
                        election.get("tp")
                    ),
                    name=str(
                        election.get("nm") or ""
                    ),
                    offices=tuple(
                        sorted(
                            offices_by_code.values(),
                            key=lambda office:
                                office.code,
                        )
                    ),
                )
            )

    return tuple(definitions)


def build_ea20_url(
    *,
    base_url: str,
    environment: str,
    cycle: str,
    election_code: int,
    scope_code: str,
    office_code: int,
) -> str:
    election = f"{election_code:06d}"
    office = f"{office_code:04d}"

    return (
        f"{base_url.rstrip('/')}/"
        f"{environment}/"
        f"{cycle}/"
        f"{election_code}/"
        f"dados/"
        f"{scope_code}/"
        f"{scope_code}-"
        f"c{office}-"
        f"e{election}-u.json"
    )


def office_applies_to_scope(
    office_code: int,
    scope_code: str,
) -> bool:
    if (
        office_code == DISTRICT_DEPUTY_OFFICE
        and scope_code != DF_SCOPE
    ):
        return False

    if (
        office_code == STATE_DEPUTY_OFFICE
        and scope_code == DF_SCOPE
    ):
        return False

    return True


def generate_targets(
    *,
    config_payload: dict[str, Any],
    ea14_payload: dict[str, Any],
    base_url: str,
    environment: str,
    election_codes: (
        set[int]
        | frozenset[int]
        | None
    ) = None,
) -> tuple[ElectionTarget, ...]:
    elections = parse_election_config(
        config_payload
    )

    scopes = parse_ea14_scopes(
        ea14_payload
    )

    federative_units = tuple(
        scope
        for scope in scopes
        if scope.is_federative_unit
    )

    exterior = next(
        (
            scope
            for scope in scopes
            if scope.is_exterior
        ),
        None,
    )

    targets: list[ElectionTarget] = []

    for election in elections:
        if (
            election.election_type
            not in SUPPORTED_ELECTION_TYPES
        ):
            continue

        if (
            election_codes is not None
            and election.election_code
            not in election_codes
        ):
            continue

        for office in election.offices:

            if office.code == PRESIDENT_OFFICE:
                presidential_scopes = [
                    BRAZIL_SCOPE,
                    *(
                        scope.code
                        for scope in federative_units
                    ),
                ]

                if exterior is not None:
                    presidential_scopes.append(
                        EXTERIOR_SCOPE
                    )

                for scope_code in presidential_scopes:
                    targets.append(
                        ElectionTarget(
                            election_code=(
                                election.election_code
                            ),
                            cycle=election.cycle,
                            round_number=(
                                election.round_number
                            ),
                            scope_code=scope_code,
                            office_code=office.code,
                            office_name=office.name,
                            url=build_ea20_url(
                                base_url=base_url,
                                environment=environment,
                                cycle=election.cycle,
                                election_code=(
                                    election.election_code
                                ),
                                scope_code=scope_code,
                                office_code=office.code,
                            ),
                        )
                    )

                continue

            for scope in federative_units:
                if not office_applies_to_scope(
                    office.code,
                    scope.code,
                ):
                    continue

                targets.append(
                    ElectionTarget(
                        election_code=(
                            election.election_code
                        ),
                        cycle=election.cycle,
                        round_number=(
                            election.round_number
                        ),
                        scope_code=scope.code,
                        office_code=office.code,
                        office_name=office.name,
                        url=build_ea20_url(
                            base_url=base_url,
                            environment=environment,
                            cycle=election.cycle,
                            election_code=(
                                election.election_code
                            ),
                            scope_code=scope.code,
                            office_code=office.code,
                        ),
                    )
                )

    return tuple(targets)

