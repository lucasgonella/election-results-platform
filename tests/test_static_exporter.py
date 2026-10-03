from datetime import datetime, timezone
from decimal import Decimal
import json

from collector.src.static_exporter import (
    load_latest_result,
    write_json_atomic,
)


NOW = datetime(
    2026,
    10,
    3,
    14,
    0,
    tzinfo=timezone.utc,
)


class FakeCursor:
    def __init__(self):
        self.executions = []
        self.step = 0

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        return False

    def execute(
        self,
        query,
        params=None,
    ):
        self.executions.append(
            (
                query,
                params,
            )
        )

    def fetchone(self):
        self.step += 1

        if self.step != 1:
            return None

        return (
            101,                    # snapshot id
            21272,                  # election code
            1,                      # round
            "go",                   # scope code
            "uf",                   # scope type
            "GO",                   # uf
            7,                      # office code
            "Deputado Estadual",    # office name
            41,                     # seats
            176304493,              # tse idg
            NOW,                    # generated_at
            NOW,                    # totalized_at
            1000,                   # sections_total
            500,                    # sections_totalized
            Decimal("50.0"),        # sections_percentage
            5000000,                # electorate_total
            2500000,                # electorate_totalized
            2000000,                # turnout
            Decimal("80.0"),        # turnout_percentage
            500000,                 # abstentions
            Decimal("20.0"),        # abstention_percentage
            1900000,                # votes_total
            1800000,                # candidate_valid_votes
            1800000,                # valid_votes
            50000,                  # blank_votes
            50000,                  # null_votes
            NOW,                    # captured_at
        )

    def fetchall(self):
        return [
            (
                123456,
                1,
                12345,
                "Candidato Teste",
                "TESTE",
                99,
                "ABC",
                "Partido ABC",
                "Coligação Teste",
                123456,
                Decimal("6.858666667"),
                "apto",
                "não eleito",
                False,
                [],
            )
        ]


class FakeConnection:
    def __init__(self):
        self.cursor_object = FakeCursor()

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        return False

    def cursor(self):
        return self.cursor_object


def test_load_latest_result_builds_payload():
    connection = FakeConnection()

    payload = load_latest_result(
        environment="simulado2026",
        scope_code="go",
        office_code=7,
        connection_factory=lambda: connection,
    )

    assert payload["environment"] == "simulado2026"

    assert payload["election"] == {
        "code": 21272,
        "round": 1,
    }

    assert payload["scope"]["code"] == "go"

    assert payload["office"]["code"] == 7

    assert payload["candidate_count"] == 1

    assert (
        payload["candidates"][0]["votes"]
        == 123456
    )

    assert (
        payload["candidates"][0]
        ["vote_percentage"]
        == 6.858666667
    )

    assert (
        payload["snapshot"]
        ["sections"]["percentage"]
        == 50.0
    )

    assert len(
        connection.cursor_object.executions
    ) == 2


def test_write_json_atomic(tmp_path):
    destination = (
        tmp_path
        / "go"
        / "state-deputy.json"
    )

    payload = {
        "status": "ok",
        "candidate_count": 943,
    }

    write_json_atomic(
        payload,
        destination,
    )

    assert destination.is_file()

    temporary = destination.with_suffix(
        ".json.tmp"
    )

    assert not temporary.exists()

    result = json.loads(
        destination.read_text(
            encoding="utf-8"
        )
    )

    assert result == payload
