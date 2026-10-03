from datetime import datetime, timezone

import pytest

import collector.src.ea14_state_repository as repository

from collector.src.tse_client import TseFetchResult


class FakeCursor:
    def __init__(
        self,
        row=None,
    ):
        self.row = row
        self.executions = []

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
        params,
    ):
        self.executions.append(
            (
                query,
                params,
            )
        )

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(
        self,
        row=None,
    ):
        self.cursor_object = FakeCursor(
            row
        )

        self.committed = False

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

    def commit(self):
        self.committed = True


def build_payload(
    *,
    election_code=21270,
    round_number=1,
):
    return {
        "ele": str(
            election_code
        ),
        "t": str(
            round_number
        ),
        "idg": "175720042",
        "abr": [],
    }


def build_fetch_result():
    return TseFetchResult(
        url=(
            "https://example.invalid/"
            "br-e021270-ab.json"
        ),
        status_code=200,
        etag='"abc123"',
        last_modified=(
            "Tue, 29 Sep 2026 "
            "19:20:00 GMT"
        ),
        sha256="a" * 64,
        payload=build_payload(),
    )


def build_database_row():
    return (
        10,
        "simulado2026",
        "ele2026",
        21270,
        1,
        175720042,
        (
            "https://example.invalid/"
            "br-e021270-ab.json"
        ),
        '"abc123"',
        (
            "Tue, 29 Sep 2026 "
            "19:20:00 GMT"
        ),
        "a" * 64,
        build_payload(),
        datetime(
            2026,
            9,
            29,
            19,
            20,
            tzinfo=timezone.utc,
        ),
    )


def test_get_ea14_state_returns_none(
    monkeypatch,
):
    connection = FakeConnection(
        row=None
    )

    monkeypatch.setattr(
        repository,
        "get_connection",
        lambda: connection,
    )

    state = (
        repository.get_ea14_state(
            environment="simulado2026",
            cycle="ele2026",
            election_code=21270,
            round_number=1,
        )
    )

    assert state is None

    assert len(
        connection
        .cursor_object
        .executions
    ) == 1


def test_get_ea14_state_maps_row(
    monkeypatch,
):
    connection = FakeConnection(
        row=build_database_row()
    )

    monkeypatch.setattr(
        repository,
        "get_connection",
        lambda: connection,
    )

    state = (
        repository.get_ea14_state(
            environment="simulado2026",
            cycle="ele2026",
            election_code=21270,
            round_number=1,
        )
    )

    assert state is not None

    assert state.id == 10

    assert (
        state.election_code
        == 21270
    )

    assert (
        state.round_number
        == 1
    )

    assert (
        state.tse_idg
        == 175720042
    )

    assert (
        state.payload["ele"]
        == "21270"
    )


def test_save_ea14_state(
    monkeypatch,
):
    connection = FakeConnection(
        row=build_database_row()
    )

    monkeypatch.setattr(
        repository,
        "get_connection",
        lambda: connection,
    )

    state = (
        repository.save_ea14_state(
            environment="simulado2026",
            cycle="ele2026",
            election_code=21270,
            round_number=1,
            fetch_result=(
                build_fetch_result()
            ),
            payload=build_payload(),
        )
    )

    assert connection.committed

    assert (
        state.election_code
        == 21270
    )

    assert (
        state.tse_idg
        == 175720042
    )

    query, params = (
        connection
        .cursor_object
        .executions[0]
    )

    assert (
        "ON CONFLICT"
        in query
    )

    assert (
        params[0]
        == "simulado2026"
    )

    assert (
        params[1]
        == "ele2026"
    )

    assert params[2] == 21270
    assert params[3] == 1
    assert params[4] == 175720042


def test_save_rejects_election_mismatch():
    with pytest.raises(
        ValueError,
        match="EA14 election mismatch",
    ):
        repository.save_ea14_state(
            environment="simulado2026",
            cycle="ele2026",
            election_code=21270,
            round_number=1,
            fetch_result=(
                build_fetch_result()
            ),
            payload=build_payload(
                election_code=99999
            ),
        )


def test_save_rejects_round_mismatch():
    with pytest.raises(
        ValueError,
        match="EA14 round mismatch",
    ):
        repository.save_ea14_state(
            environment="simulado2026",
            cycle="ele2026",
            election_code=21270,
            round_number=1,
            fetch_result=(
                build_fetch_result()
            ),
            payload=build_payload(
                round_number=2
            ),
        )
