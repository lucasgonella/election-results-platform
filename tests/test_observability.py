from datetime import (
    datetime,
    timezone,
)

import collector.src.observability as cli
import collector.src.observability_repository as repository


NOW = datetime(
    2026,
    10,
    3,
    12,
    0,
    tzinfo=timezone.utc,
)


class FakeCursor:
    def __init__(
        self,
        *,
        fetchall_rows=None,
        fetchone_rows=None,
    ):
        self.fetchall_rows = (
            fetchall_rows
            or []
        )

        self.fetchone_rows = list(
            fetchone_rows
            or []
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

    def fetchall(self):
        return self.fetchall_rows

    def fetchone(self):
        if not self.fetchone_rows:
            return None

        return self.fetchone_rows.pop(
            0
        )


class FakeConnection:
    def __init__(
        self,
        *,
        fetchall_rows=None,
        fetchone_rows=None,
    ):
        self.cursor_object = FakeCursor(
            fetchall_rows=(
                fetchall_rows
            ),
            fetchone_rows=(
                fetchone_rows
            ),
        )

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


def batch_row(
    *,
    batch_id=1,
    election_code=21272,
    status="pending",
    total=108,
    completed=1,
    pending=107,
    success=0,
    not_modified=1,
    errors=0,
):
    return (
        batch_id,
        election_code,
        1,
        status,
        177052630,
        total,
        completed,
        pending,
        success,
        not_modified,
        errors,
        NOW,
    )


def run_row(
    *,
    status="not_modified",
):
    return (
        5,
        status,
        21272,
        "go",
        3,
        304,
        176481215,
        0,
        NOW,
        NOW,
        None,
    )


def status_object(
    *,
    errors=0,
    run_status="success",
):
    batch = (
        repository
        .BatchObservability(
            batch_id=1,
            election_code=21272,
            round_number=1,
            status="pending",
            ea14_tse_idg=177052630,
            total_targets=108,
            completed_targets=1,
            pending_items=(
                107
                if errors == 0
                else 106
            ),
            success_items=0,
            not_modified_items=1,
            error_items=errors,
            updated_at=NOW,
        )
    )

    run = (
        repository
        .CollectorRunObservability(
            id=5,
            status=run_status,
            election_code=21272,
            scope_code="go",
            office_code=3,
            http_status=200,
            tse_idg=176481215,
            candidates_processed=12,
            started_at=NOW,
            finished_at=NOW,
            error_message=None,
        )
    )

    return (
        repository
        .CollectorObservability(
            environment="simulado2026",
            cycle="ele2026",
            batches=(batch,),
            ea14_states=0,
            last_run=run,
        )
    )


def test_repository_reads_status(
    monkeypatch,
):
    connection = FakeConnection(
        fetchall_rows=[
            batch_row(),
        ],
        fetchone_rows=[
            (0,),
            run_row(),
        ],
    )

    monkeypatch.setattr(
        repository,
        "get_connection",
        lambda: connection,
    )

    status = (
        repository.get_observability(
            environment="simulado2026",
            cycle="ele2026",
        )
    )

    assert status.active_batches == 1
    assert status.pending_items == 107
    assert status.completed_items == 1
    assert status.error_items == 0
    assert status.ea14_states == 0

    assert (
        status.last_run.status
        == "not_modified"
    )


def test_health_is_ok_without_errors():
    status = status_object()

    assert status.health == "ok"


def test_health_is_degraded_with_item_error():
    status = status_object(
        errors=1
    )

    assert (
        status.health
        == "degraded"
    )


def test_health_is_degraded_when_last_run_failed():
    status = status_object(
        run_status="error"
    )

    assert (
        status.health
        == "degraded"
    )


def test_progress_percentage():
    status = status_object()

    assert (
        status.batches[0]
        .progress_percentage
        == 0.93
    )


def test_metric_health_code():
    assert (
        cli._metric_value(
            status_object(),
            "health_code",
        )
        == 1
    )

    assert (
        cli._metric_value(
            status_object(
                errors=1
            ),
            "health_code",
        )
        == 0
    )


def test_metric_pending_items():
    assert (
        cli._metric_value(
            status_object(),
            "pending_items",
        )
        == 107
    )


def test_json_output_contains_operational_data():
    output = cli._build_output(
        status_object()
    )

    assert output["health"] == "ok"
    assert output["active_batches"] == 1
    assert output["pending_items"] == 107

    assert (
        output["batches"][0]
        ["election_code"]
        == 21272
    )

    assert (
        output["last_run"]
        ["scope_code"]
        == "go"
    )
