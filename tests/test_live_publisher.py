from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from collector.src.live_static import (
    elected_alerts,
    manifest_item,
    static_payload,
)


def parsed_result():
    candidate = SimpleNamespace(
        tse_candidate_seq=123,
        display_order=1,
        ballot_number=42,
        name="Pessoa Teste",
        ballot_name="TESTE",
        party_number=99,
        party_acronym="ABC",
        party_name="Partido ABC",
        alliance_name="Aliança Teste",
        votes=12345,
        vote_percentage=Decimal("12.34"),
        candidate_status="apto",
        result_status="não eleito",
        elected=False,
        running_mates=(),
    )

    office = SimpleNamespace(
        code=7,
        name="Deputado Estadual",
        seats=41,
        candidates=(candidate,),
    )

    stats = SimpleNamespace(
        sections_total=1000,
        sections_totalized=100,
        sections_percentage=Decimal("10.0"),
        electorate_total=5000000,
        electorate_totalized=500000,
        turnout=400000,
        turnout_percentage=Decimal("80.0"),
        abstentions=100000,
        abstention_percentage=Decimal("20.0"),
        votes_total=390000,
        candidate_valid_votes=380000,
        valid_votes=380000,
        blank_votes=5000,
        null_votes=5000,
    )

    return SimpleNamespace(
        election_code=6259,
        round_number=1,
        scope_type="uf",
        scope_code="go",
        tse_idg=123456,
        generated_at=datetime(
            2026,
            10,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        totalized_at=datetime(
            2026,
            10,
            4,
            21,
            0,
            tzinfo=timezone.utc,
        ),
        stats=stats,
        offices=(office,),
    )


def test_static_payload(
    monkeypatch,
):
    monkeypatch.setenv(
        "TSE_ENVIRONMENT",
        "oficial",
    )

    captured_at = datetime(
        2026,
        10,
        4,
        21,
        0,
        5,
        tzinfo=timezone.utc,
    )

    payload = (
        static_payload(
            parsed_result(),
            environment="oficial",
            captured_at=captured_at,
        )
    )

    assert payload["environment"] == "oficial"
    assert payload["scope"]["code"] == "go"
    assert payload["scope"]["uf"] == "GO"
    assert payload["office"]["code"] == 7

    assert (
        payload["snapshot"]
        ["sections"]["percentage"]
        == 10.0
    )

    assert (
        payload["snapshot"]
        ["captured_at"]
        == captured_at.isoformat()
    )

    assert payload["candidate_count"] == 1

    assert (
        payload["candidates"][0]
        ["vote_percentage"]
        == 12.34
    )


def test_manifest_item_uses_live_snapshot():
    payload = static_payload(
        parsed_result(),
        environment="oficial",
        captured_at=datetime(
            2026,
            10,
            4,
            21,
            0,
            5,
            tzinfo=timezone.utc,
        ),
    )

    from pathlib import Path

    item = manifest_item(
        payload,
        Path(
            "go/state-deputy.json"
        ),
    )

    assert item["scope"] == "go"
    assert item["office"] == 7
    assert item["tse_idg"] == 123456
    assert (
        item["path"]
        == "go/state-deputy.json"
    )


def test_governor_elected_alert_is_derived():
    result = parsed_result()

    candidate = (
        result.offices[0]
        .candidates[0]
    )

    candidate.elected = True
    candidate.result_status = "Eleito"

    result.offices = (
        SimpleNamespace(
            code=3,
            name="Governador",
            seats=1,
            candidates=(candidate,),
        ),
    )

    payload = static_payload(
        result,
        environment="oficial",
        captured_at=datetime(
            2026,
            10,
            4,
            21,
            10,
            tzinfo=timezone.utc,
        ),
    )

    alerts = elected_alerts(
        payload
    )

    assert len(alerts) == 1
    assert alerts[0]["scope"] == "go"
    assert alerts[0]["office"] == 3
    assert (
        alerts[0]["candidate_name"]
        == "TESTE"
    )
    assert (
        alerts[0]["party_acronym"]
        == "ABC"
    )


def test_deputy_does_not_generate_elected_alert():
    result = parsed_result()

    candidate = (
        result.offices[0]
        .candidates[0]
    )

    candidate.elected = True

    payload = static_payload(
        result,
        environment="oficial",
        captured_at=datetime(
            2026,
            10,
            4,
            21,
            10,
            tzinfo=timezone.utc,
        ),
    )

    assert elected_alerts(
        payload
    ) == []



def test_static_payload_exposes_seat_allocations():
    result = parsed_result()
    office = result.offices[0]

    office.electoral_quotient = 100000
    office.seat_allocations = (
        SimpleNamespace(
            number=10,
            name="Federação Teste",
            kind="f",
            composition="ABC / XYZ",
            seats=4,
            parties=(
                {
                    "number": 99,
                    "acronym": "ABC",
                    "name": "Partido ABC",
                },
                {
                    "number": 98,
                    "acronym": "XYZ",
                    "name": "Partido XYZ",
                },
            ),
        ),
    )

    payload = static_payload(
        result,
        environment="oficial",
        captured_at=datetime(
            2026,
            10,
            4,
            21,
            20,
            tzinfo=timezone.utc,
        ),
    )

    assert (
        payload["office"]
        ["electoral_quotient"]
        == 100000
    )

    allocations = (
        payload["office"]
        ["seat_allocations"]
    )

    assert len(allocations) == 1
    assert allocations[0]["seats"] == 4
    assert (
        allocations[0]["type"]
        == "f"
    )
    assert (
        allocations[0]["parties"][0]
        ["acronym"]
        == "ABC"
    )



def test_governor_second_round_alert_is_derived():
    result = parsed_result()

    candidate = (
        result.offices[0]
        .candidates[0]
    )

    candidate.elected = False
    candidate.result_status = "2º turno"

    result.offices = (
        SimpleNamespace(
            code=3,
            name="Governador",
            seats=1,
            candidates=(candidate,),
        ),
    )

    payload = static_payload(
        result,
        environment="oficial",
        captured_at=datetime(
            2026,
            10,
            4,
            23,
            20,
            tzinfo=timezone.utc,
        ),
    )

    alerts = elected_alerts(
        payload
    )

    assert len(alerts) == 1
    assert (
        alerts[0]["kind"]
        == "second_round"
    )
    assert (
        alerts[0]["result_status"]
        == "2º turno"
    )


def test_second_round_status_wins_over_elected_flag():
    result = parsed_result()

    candidate = (
        result.offices[0]
        .candidates[0]
    )

    candidate.elected = True
    candidate.result_status = "2º turno"

    result.offices = (
        SimpleNamespace(
            code=3,
            name="Governador",
            seats=1,
            candidates=(candidate,),
        ),
    )

    payload = static_payload(
        result,
        environment="oficial",
        captured_at=datetime(
            2026,
            10,
            4,
            23,
            20,
            tzinfo=timezone.utc,
        ),
    )

    alerts = elected_alerts(
        payload
    )

    assert len(alerts) == 1
    assert (
        alerts[0]["kind"]
        == "second_round"
    )



def test_mathematically_elected_alert_without_candidate_flag():
    result = parsed_result()
    candidate = (
        result.offices[0]
        .candidates[0]
    )

    candidate.elected = False
    candidate.result_status = None

    result.offices = (
        SimpleNamespace(
            code=3,
            name="Governador",
            seats=1,
            candidates=(candidate,),
        ),
    )
    result.mathematical_definition = "e"
    result.totalization_final = False

    payload = static_payload(
        result,
        environment="oficial",
        captured_at=datetime(
            2026,
            10,
            4,
            23,
            30,
            tzinfo=timezone.utc,
        ),
    )

    alerts = elected_alerts(
        payload
    )

    assert len(alerts) == 1
    assert (
        alerts[0]["kind"]
        == "mathematically_elected"
    )
    assert (
        alerts[0][
            "mathematical_definition"
        ]
        == "e"
    )
    assert (
        alerts[0]["candidate_name"]
        is None
    )


def test_mathematical_second_round_uses_md_flag():
    result = parsed_result()
    candidate = (
        result.offices[0]
        .candidates[0]
    )

    candidate.elected = False
    candidate.result_status = None

    result.offices = (
        SimpleNamespace(
            code=3,
            name="Governador",
            seats=1,
            candidates=(candidate,),
        ),
    )
    result.mathematical_definition = "s"
    result.totalization_final = False

    payload = static_payload(
        result,
        environment="oficial",
        captured_at=datetime(
            2026,
            10,
            4,
            23,
            30,
            tzinfo=timezone.utc,
        ),
    )

    alerts = elected_alerts(
        payload
    )

    assert len(alerts) == 1
    assert (
        alerts[0]["kind"]
        == "second_round"
    )
    assert (
        alerts[0][
            "mathematical_definition"
        ]
        == "s"
    )
