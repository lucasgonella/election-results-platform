from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .discovery import ElectionTarget
from .planner import ElectionCollectionPlan


@dataclass(frozen=True, slots=True)
class EA14ScopeState:
    scope_type: str
    scope_code: str

    update_date: str | None
    update_time: str | None

    finished: str | None

    sections_total: int | None
    sections_totalized: int | None
    sections_percentage: Decimal | None

    @property
    def fingerprint(
        self,
    ) -> tuple[
        str | None,
        str | None,
        str | None,
        int | None,
        int | None,
        Decimal | None,
    ]:
        return (
            self.update_date,
            self.update_time,
            self.finished,
            self.sections_total,
            self.sections_totalized,
            self.sections_percentage,
        )


@dataclass(frozen=True, slots=True)
class EA14Change:
    scope_code: str
    change_type: str

    previous: EA14ScopeState | None
    current: EA14ScopeState


@dataclass(frozen=True, slots=True)
class ChangeDetectionResult:
    election_code: int
    changes: tuple[EA14Change, ...]
    targets: tuple[ElectionTarget, ...]


def _as_int(
    value: Any,
) -> int | None:
    if value is None:
        return None

    normalized = str(value).strip()

    if not normalized:
        return None

    return int(normalized)


def _as_decimal(
    value: Any,
) -> Decimal | None:
    if value is None:
        return None

    normalized = str(value).strip()

    if not normalized:
        return None

    return Decimal(
        normalized.replace(",", ".")
    )


def parse_ea14_scope_states(
    payload: dict[str, Any],
) -> dict[str, EA14ScopeState]:
    states: dict[
        str,
        EA14ScopeState,
    ] = {}

    for scope in payload.get(
        "abr",
        [],
    ):
        scope_code = str(
            scope.get("cdabr")
            or ""
        ).strip().lower()

        scope_type = str(
            scope.get("tpabr")
            or ""
        ).strip().lower()

        if not scope_code:
            continue

        sections = (
            scope.get("s")
            or {}
        )

        state = EA14ScopeState(
            scope_type=scope_type,
            scope_code=scope_code,

            update_date=scope.get(
                "dt"
            ),
            update_time=scope.get(
                "ht"
            ),

            finished=scope.get(
                "and"
            ),

            sections_total=_as_int(
                sections.get("ts")
            ),
            sections_totalized=_as_int(
                sections.get("st")
            ),
            sections_percentage=(
                _as_decimal(
                    sections.get("pstn")
                    or sections.get("pst")
                )
            ),
        )

        if scope_code in states:
            raise ValueError(
                "Duplicate EA14 scope "
                f"{scope_code}."
            )

        states[
            scope_code
        ] = state

    return states


def detect_ea14_changes(
    *,
    previous_payload: (
        dict[str, Any]
        | None
    ),
    current_payload: dict[str, Any],
) -> tuple[EA14Change, ...]:
    current_states = (
        parse_ea14_scope_states(
            current_payload
        )
    )

    previous_states = (
        parse_ea14_scope_states(
            previous_payload
        )
        if previous_payload
        is not None
        else {}
    )

    changes: list[
        EA14Change
    ] = []

    for scope_code in sorted(
        current_states
    ):
        current = current_states[
            scope_code
        ]

        previous = previous_states.get(
            scope_code
        )

        if previous is None:
            changes.append(
                EA14Change(
                    scope_code=(
                        scope_code
                    ),
                    change_type="new",
                    previous=None,
                    current=current,
                )
            )

            continue

        if (
            previous.fingerprint
            != current.fingerprint
        ):
            changes.append(
                EA14Change(
                    scope_code=(
                        scope_code
                    ),
                    change_type="changed",
                    previous=previous,
                    current=current,
                )
            )

    return tuple(changes)


def select_targets_for_changes(
    *,
    plan: ElectionCollectionPlan,
    changes: tuple[
        EA14Change,
        ...
    ],
) -> tuple[
    ElectionTarget,
    ...
]:
    changed_scopes = {
        change.scope_code
        for change in changes
    }

    return tuple(
        target
        for target in plan.targets
        if target.scope_code
        in changed_scopes
    )


def detect_plan_changes(
    *,
    plan: ElectionCollectionPlan,
    previous_payload: (
        dict[str, Any]
        | None
    ),
    current_payload: dict[str, Any],
) -> ChangeDetectionResult:
    raw_election_code = (
        current_payload.get("ele")
    )

    current_election_code = (
        _as_int(
            raw_election_code
        )
    )

    if (
        current_election_code
        is not None
        and current_election_code
        != plan.election_code
    ):
        raise ValueError(
            "EA14 election mismatch: "
            f"plan={plan.election_code}, "
            f"payload="
            f"{current_election_code}."
        )

    changes = detect_ea14_changes(
        previous_payload=(
            previous_payload
        ),
        current_payload=(
            current_payload
        ),
    )

    targets = (
        select_targets_for_changes(
            plan=plan,
            changes=changes,
        )
    )

    return ChangeDetectionResult(
        election_code=(
            plan.election_code
        ),
        changes=changes,
        targets=targets,
    )
