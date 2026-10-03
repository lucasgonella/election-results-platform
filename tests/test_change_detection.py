from collector.src.change_detection import (
    detect_ea14_changes,
    detect_plan_changes,
    parse_ea14_scope_states,
    select_targets_for_changes,
)
from collector.src.discovery import (
    ElectionTarget,
)
from collector.src.planner import (
    ElectionCollectionPlan,
)


def scope(
    code,
    *,
    time="16:20:00",
    totalized=100,
    percentage="100",
    finished="f",
):
    return {
        "tpabr": (
            "br"
            if code == "br"
            else "uf"
        ),
        "cdabr": code,
        "and": finished,
        "dt": "29/09/2026",
        "ht": time,
        "s": {
            "ts": "100",
            "st": str(
                totalized
            ),
            "pstn": str(
                percentage
            ),
        },
    }


def payload(
    election_code=21270,
    scopes=None,
):
    return {
        "ele": str(
            election_code
        ),
        "t": "1",
        "abr": scopes or [],
    }


def target(
    scope_code,
    office_code=1,
):
    return ElectionTarget(
        election_code=21270,
        cycle="ele2026",
        round_number=1,
        scope_code=scope_code,
        office_code=office_code,
        office_name="Teste",
        url=(
            "https://example.invalid/"
            f"{scope_code}/"
            f"{office_code}.json"
        ),
    )


def plan():
    return ElectionCollectionPlan(
        election_code=21270,
        election_type=8,
        cycle="ele2026",
        ea14_url=(
            "https://example.invalid/"
            "ea14.json"
        ),
        ea14_idg="100",
        targets=(
            target("br"),
            target("ac"),
            target("go"),
            target("zz"),
        ),
    )


def test_parses_scope_state():
    states = (
        parse_ea14_scope_states(
            payload(
                scopes=[
                    scope(
                        "go",
                        totalized=75,
                        percentage="75,00",
                    )
                ]
            )
        )
    )

    go = states["go"]

    assert (
        go.scope_code
        == "go"
    )

    assert (
        go.sections_total
        == 100
    )

    assert (
        go.sections_totalized
        == 75
    )

    assert str(
        go.sections_percentage
    ) == "75.00"


def test_first_run_marks_all_as_new():
    current = payload(
        scopes=[
            scope("br"),
            scope("ac"),
            scope("go"),
            scope("zz"),
        ]
    )

    changes = (
        detect_ea14_changes(
            previous_payload=None,
            current_payload=current,
        )
    )

    assert {
        change.scope_code
        for change in changes
    } == {
        "br",
        "ac",
        "go",
        "zz",
    }

    assert all(
        change.change_type
        == "new"
        for change in changes
    )


def test_unchanged_scope_is_ignored():
    previous = payload(
        scopes=[
            scope("go"),
        ]
    )

    current = payload(
        scopes=[
            scope("go"),
        ]
    )

    changes = (
        detect_ea14_changes(
            previous_payload=previous,
            current_payload=current,
        )
    )

    assert changes == ()


def test_time_change_is_detected():
    previous = payload(
        scopes=[
            scope(
                "go",
                time="16:20:00",
            ),
        ]
    )

    current = payload(
        scopes=[
            scope(
                "go",
                time="16:21:00",
            ),
        ]
    )

    changes = (
        detect_ea14_changes(
            previous_payload=previous,
            current_payload=current,
        )
    )

    assert len(changes) == 1

    assert (
        changes[0].scope_code
        == "go"
    )

    assert (
        changes[0].change_type
        == "changed"
    )


def test_section_progress_is_detected():
    previous = payload(
        scopes=[
            scope(
                "go",
                totalized=50,
                percentage="50",
            ),
        ]
    )

    current = payload(
        scopes=[
            scope(
                "go",
                totalized=75,
                percentage="75",
            ),
        ]
    )

    changes = (
        detect_ea14_changes(
            previous_payload=previous,
            current_payload=current,
        )
    )

    assert len(changes) == 1

    assert (
        changes[0]
        .current
        .sections_totalized
        == 75
    )


def test_only_changed_scope_targets_are_selected():
    collection_plan = plan()

    previous = payload(
        scopes=[
            scope("br"),
            scope("ac"),
            scope("go"),
            scope("zz"),
        ]
    )

    current = payload(
        scopes=[
            scope("br"),
            scope("ac"),
            scope(
                "go",
                time="16:22:00",
            ),
            scope("zz"),
        ]
    )

    changes = (
        detect_ea14_changes(
            previous_payload=previous,
            current_payload=current,
        )
    )

    targets = (
        select_targets_for_changes(
            plan=collection_plan,
            changes=changes,
        )
    )

    assert len(targets) == 1

    assert (
        targets[0].scope_code
        == "go"
    )


def test_new_scope_selects_its_target():
    collection_plan = plan()

    previous = payload(
        scopes=[
            scope("br"),
            scope("go"),
            scope("zz"),
        ]
    )

    current = payload(
        scopes=[
            scope("br"),
            scope("ac"),
            scope("go"),
            scope("zz"),
        ]
    )

    result = detect_plan_changes(
        plan=collection_plan,
        previous_payload=previous,
        current_payload=current,
    )

    assert len(
        result.changes
    ) == 1

    assert len(
        result.targets
    ) == 1

    assert (
        result.targets[0]
        .scope_code
        == "ac"
    )


def test_election_mismatch_is_rejected():
    collection_plan = plan()

    current = payload(
        election_code=99999,
        scopes=[
            scope("go"),
        ],
    )

    try:
        detect_plan_changes(
            plan=collection_plan,
            previous_payload=None,
            current_payload=current,
        )

    except ValueError as exc:
        assert (
            "EA14 election mismatch"
            in str(exc)
        )

    else:
        raise AssertionError(
            "Expected ValueError."
        )


def test_duplicate_scope_is_rejected():
    duplicated = payload(
        scopes=[
            scope("go"),
            scope("go"),
        ]
    )

    try:
        parse_ea14_scope_states(
            duplicated
        )

    except ValueError as exc:
        assert (
            "Duplicate EA14 scope"
            in str(exc)
        )

    else:
        raise AssertionError(
            "Expected ValueError."
        )
