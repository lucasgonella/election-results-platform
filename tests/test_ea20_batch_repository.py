from datetime import (
    datetime,
    timezone,
)

import pytest

import collector.src.ea20_batch_repository as repository

from collector.src.discovery import (
    ElectionTarget,
)


NOW = datetime(
    2026,
    10,
    3,
    12,
    0,
    tzinfo=timezone.utc,
)


def batch_row(
    *,
    status="pending",
    total=2,
    completed=0,
):
    return (
        10,
        "simulado2026",
        "ele2026",
        21272,
        1,
        177052630,
        "a" * 64,
        "https://example.invalid/ea14.json",
        status,
        total,
        completed,
        NOW,
        NOW,
        (
            NOW
            if status == "completed"
            else None
        ),
    )


def item_row(
    *,
    item_id=100,
    status="pending",
    attempts=0,
    collector_run_id=None,
    last_error=None,
):
    return (
        item_id,
        10,
        "go",
        3,
        "Governador",
        "https://example.invalid/go.json",
        status,
        attempts,
        collector_run_id,
        last_error,
    )


class FakeCursor:
    def __init__(
        self,
        *,
        fetchone_rows=None,
        fetchall_rows=None,
    ):
        self.fetchone_rows = list(
            fetchone_rows or []
        )

        self.fetchall_rows = (
            fetchall_rows or []
        )

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
        params=None,
    ):
        self.executions.append(
            (
                query,
                params,
            )
        )

    def fetchone(self):
        if not self.fetchone_rows:
            return None

        return self.fetchone_rows.pop(
            0
        )

    def fetchall(self):
        return self.fetchall_rows


class FakeConnection:
    def __init__(
        self,
        *,
        fetchone_rows=None,
        fetchall_rows=None,
    ):
        self.cursor_object = FakeCursor(
            fetchone_rows=fetchone_rows,
            fetchall_rows=fetchall_rows,
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


def target(
    scope,
    office,
):
    return ElectionTarget(
        election_code=21272,
        cycle="ele2026",
        round_number=1,
        scope_code=scope,
        office_code=office,
        office_name="Teste",
        url=(
            "https://example.invalid/"
            f"{scope}-{office}.json"
        ),
    )


def test_prepare_batch_seeds_targets(
    monkeypatch,
):
    connection = FakeConnection(
        fetchone_rows=[
            batch_row(
                total=0,
            ),
            batch_row(
                total=2,
            ),
        ]
    )

    monkeypatch.setattr(
        repository,
        "get_connection",
        lambda: connection,
    )

    batch = repository.prepare_batch(
        environment="simulado2026",
        cycle="ele2026",
        election_code=21272,
        round_number=1,
        ea14_tse_idg=177052630,
        ea14_payload_sha256="a" * 64,
        ea14_source_url=(
            "https://example.invalid/"
            "ea14.json"
        ),
        targets=(
            target("go", 3),
            target("go", 5),
        ),
    )

    assert batch.id == 10
    assert batch.total_targets == 2
    assert batch.completed_targets == 0

    assert connection.committed

    queries = [
        query
        for query, _
        in connection
        .cursor_object
        .executions
    ]

    assert any(
        "superseded"
        in query
        for query in queries
    )

    item_inserts = [
        query
        for query in queries
        if (
            "INSERT INTO ea20_batch_items"
            in query
        )
    ]

    assert len(
        item_inserts
    ) == 2


def test_get_pending_items(
    monkeypatch,
):
    connection = FakeConnection(
        fetchall_rows=[
            item_row(
                item_id=100,
            ),
            item_row(
                item_id=101,
            ),
        ]
    )

    monkeypatch.setattr(
        repository,
        "get_connection",
        lambda: connection,
    )

    items = (
        repository.get_pending_items(
            batch_id=10,
            limit=2,
        )
    )

    assert len(items) == 2
    assert items[0].id == 100
    assert items[1].id == 101


def test_get_pending_items_rejects_bad_limit():
    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        repository.get_pending_items(
            batch_id=10,
            limit=0,
        )


def test_mark_item_completed(
    monkeypatch,
):
    connection = FakeConnection(
        fetchone_rows=[
            item_row(
                status="success",
                attempts=1,
                collector_run_id=44,
            )
        ]
    )

    monkeypatch.setattr(
        repository,
        "get_connection",
        lambda: connection,
    )

    item = (
        repository.mark_item_completed(
            item_id=100,
            status="success",
            collector_run_id=44,
        )
    )

    assert item.status == "success"
    assert item.attempts == 1
    assert item.collector_run_id == 44
    assert connection.committed


def test_mark_item_completed_rejects_status():
    with pytest.raises(
        ValueError,
        match="success or not_modified",
    ):
        repository.mark_item_completed(
            item_id=100,
            status="error",
            collector_run_id=None,
        )


def test_mark_item_error(
    monkeypatch,
):
    connection = FakeConnection(
        fetchone_rows=[
            item_row(
                status="error",
                attempts=1,
                last_error="boom",
            )
        ]
    )

    monkeypatch.setattr(
        repository,
        "get_connection",
        lambda: connection,
    )

    item = (
        repository.mark_item_error(
            item_id=100,
            error_message="boom",
        )
    )

    assert item.status == "error"
    assert item.attempts == 1
    assert item.last_error == "boom"


def test_refresh_batch_becomes_ready(
    monkeypatch,
):
    connection = FakeConnection(
        fetchone_rows=[
            batch_row(
                status="ready",
                total=2,
                completed=2,
            )
        ]
    )

    monkeypatch.setattr(
        repository,
        "get_connection",
        lambda: connection,
    )

    batch = (
        repository
        .refresh_batch_progress(
            batch_id=10
        )
    )

    assert batch.status == "ready"
    assert batch.completed_targets == 2


def test_mark_batch_completed(
    monkeypatch,
):
    connection = FakeConnection(
        fetchone_rows=[
            batch_row(
                status="completed",
                total=2,
                completed=2,
            )
        ]
    )

    monkeypatch.setattr(
        repository,
        "get_connection",
        lambda: connection,
    )

    batch = (
        repository
        .mark_batch_completed(
            batch_id=10
        )
    )

    assert batch.status == "completed"
    assert batch.completed_at == NOW
