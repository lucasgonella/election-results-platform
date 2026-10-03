from types import SimpleNamespace
import threading

import pytest

import collector.src.batch_ingest as module

from collector.src.discovery import (
    ElectionTarget,
)
from collector.src.runtime import (
    RuntimeSettings,
)
from collector.src.stateful_planner import (
    EA14StateUpdate,
    StatefulElectionResult,
    StatefulPlannerResult,
)
from collector.src.tse_client import (
    TseFetchResult,
)


def settings():
    return RuntimeSettings(
        base_url=(
            "https://resultados-sim."
            "tse.jus.br/simulado"
        ),
        environment="simulado2026",
        cycle="ele2026",
        round_number=1,
    )


def target(
    scope,
    office=3,
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


def update():
    fetch = TseFetchResult(
        url=(
            "https://example.invalid/"
            "ea14.json"
        ),
        status_code=200,
        etag='"ea14"',
        last_modified="last",
        sha256="a" * 64,
        payload={
            "ele": "21272",
            "t": "1",
            "idg": "177052630",
            "abr": [],
        },
    )

    return EA14StateUpdate(
        environment="simulado2026",
        cycle="ele2026",
        election_code=21272,
        round_number=1,
        fetch_result=fetch,
        payload=fetch.payload,
    )


def election(
    targets,
):
    return StatefulElectionResult(
        election_code=21272,
        election_type=1,
        ea14_url=(
            "https://example.invalid/"
            "ea14.json"
        ),
        http_status=200,
        status="changed",
        changed_scopes=tuple(
            item.scope_code
            for item in targets
        ),
        targets=tuple(targets),
        state_update=update(),
    )


def planner(
    targets,
):
    return StatefulPlannerResult(
        config_url=(
            "https://example.invalid/"
            "ele-c.json"
        ),
        elections=(
            election(targets),
        ),
    )


def batch(
    *,
    status="pending",
    total=3,
    completed=0,
):
    return SimpleNamespace(
        id=10,
        status=status,
        total_targets=total,
        completed_targets=completed,
    )


def item(
    item_id,
    target_item,
):
    return SimpleNamespace(
        id=item_id,
        source_url=(
            target_item.url
        ),
    )


def ingest_result(
    target_item,
):
    return SimpleNamespace(
        election_code=21272,
        scope_code=(
            target_item.scope_code
        ),
        office_code=(
            target_item.office_code
        ),
        status="success",
        http_status=200,
        collector_run_id=99,
        tse_idg=123,
        snapshots_created=1,
        candidates_processed=10,
    )


def test_dry_run_does_not_prepare_batches(
    monkeypatch,
):
    targets = (
        target("go"),
        target("ac"),
    )

    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        lambda **kwargs:
            planner(targets),
    )

    prepared = []

    monkeypatch.setattr(
        module,
        "prepare_batch",
        lambda **kwargs:
            prepared.append(kwargs),
    )

    result = (
        module.run_batched_ingest(
            settings=settings(),
        )
    )

    assert not result.execute
    assert result.planned_targets == 2
    assert result.selected_targets == 2
    assert result.processed_targets == 0
    assert prepared == []


def test_batch_size_limits_processing(
    monkeypatch,
):
    targets = (
        target("go"),
        target("ac"),
        target("sp"),
    )

    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        lambda **kwargs:
            planner(targets),
    )

    monkeypatch.setattr(
        module,
        "prepare_batch",
        lambda **kwargs:
            batch(
                total=3,
                completed=0,
            ),
    )

    monkeypatch.setattr(
        module,
        "get_pending_items",
        lambda **kwargs: (
            item(1, targets[0]),
            item(2, targets[1]),
            item(3, targets[2]),
        ),
    )

    processed = []

    monkeypatch.setattr(
        module,
        "_ingest_target",
        lambda **kwargs: (
            processed.append(
                kwargs["target"]
            )
            or ingest_result(
                kwargs["target"]
            )
        ),
    )

    completed_items = []

    monkeypatch.setattr(
        module,
        "mark_item_completed",
        lambda **kwargs:
            completed_items.append(
                kwargs
            ),
    )

    monkeypatch.setattr(
        module,
        "refresh_batch_progress",
        lambda **kwargs:
            batch(
                status="pending",
                total=3,
                completed=2,
            ),
    )

    committed = []

    monkeypatch.setattr(
        module,
        "_commit_ea14_state",
        lambda election:
            committed.append(
                election
            ),
    )

    result = (
        module.run_batched_ingest(
            settings=settings(),
            client=SimpleNamespace(),
            execute=True,
            batch_size=2,
        )
    )

    assert len(processed) == 2
    assert len(completed_items) == 2
    assert result.processed_targets == 2
    assert result.failed_targets == 0
    assert committed == []


def test_partial_batch_does_not_commit_ea14(
    monkeypatch,
):
    go = target("go")

    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        lambda **kwargs:
            planner((go,)),
    )

    monkeypatch.setattr(
        module,
        "prepare_batch",
        lambda **kwargs:
            batch(
                total=2,
                completed=1,
            ),
    )

    monkeypatch.setattr(
        module,
        "get_pending_items",
        lambda **kwargs: (
            item(1, go),
        ),
    )

    monkeypatch.setattr(
        module,
        "_ingest_target",
        lambda **kwargs:
            ingest_result(go),
    )

    monkeypatch.setattr(
        module,
        "mark_item_completed",
        lambda **kwargs: None,
    )

    monkeypatch.setattr(
        module,
        "refresh_batch_progress",
        lambda **kwargs:
            batch(
                status="pending",
                total=2,
                completed=1,
            ),
    )

    committed = []

    monkeypatch.setattr(
        module,
        "_commit_ea14_state",
        lambda election:
            committed.append(
                election
            ),
    )

    result = (
        module.run_batched_ingest(
            settings=settings(),
            client=SimpleNamespace(),
            execute=True,
            batch_size=1,
        )
    )

    assert (
        result
        .state_updates_committed
        == 0
    )

    assert committed == []


def test_ready_batch_commits_checkpoint(
    monkeypatch,
):
    go = target("go")

    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        lambda **kwargs:
            planner((go,)),
    )

    monkeypatch.setattr(
        module,
        "prepare_batch",
        lambda **kwargs:
            batch(
                total=1,
                completed=0,
            ),
    )

    monkeypatch.setattr(
        module,
        "get_pending_items",
        lambda **kwargs: (
            item(1, go),
        ),
    )

    monkeypatch.setattr(
        module,
        "_ingest_target",
        lambda **kwargs:
            ingest_result(go),
    )

    monkeypatch.setattr(
        module,
        "mark_item_completed",
        lambda **kwargs: None,
    )

    monkeypatch.setattr(
        module,
        "refresh_batch_progress",
        lambda **kwargs:
            batch(
                status="ready",
                total=1,
                completed=1,
            ),
    )

    monkeypatch.setattr(
        module,
        "mark_batch_completed",
        lambda **kwargs:
            batch(
                status="completed",
                total=1,
                completed=1,
            ),
    )

    committed = []

    monkeypatch.setattr(
        module,
        "_commit_ea14_state",
        lambda election:
            committed.append(
                election
            ),
    )

    result = (
        module.run_batched_ingest(
            settings=settings(),
            client=SimpleNamespace(),
            execute=True,
            batch_size=1,
        )
    )

    assert (
        result
        .state_updates_committed
        == 1
    )

    assert (
        result
        .data_updates_committed
        == 1
    )

    assert len(committed) == 1

    assert (
        result.elections[0]
        .batch_status
        == "completed"
    )


def test_completed_batch_recovers_checkpoint(
    monkeypatch,
):
    go = target("go")

    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        lambda **kwargs:
            planner((go,)),
    )

    monkeypatch.setattr(
        module,
        "prepare_batch",
        lambda **kwargs:
            batch(
                status="completed",
                total=1,
                completed=1,
            ),
    )

    monkeypatch.setattr(
        module,
        "get_pending_items",
        lambda **kwargs: (),
    )

    monkeypatch.setattr(
        module,
        "refresh_batch_progress",
        lambda **kwargs:
            batch(
                status="completed",
                total=1,
                completed=1,
            ),
    )

    committed = []

    monkeypatch.setattr(
        module,
        "_commit_ea14_state",
        lambda election:
            committed.append(
                election
            ),
    )

    result = (
        module.run_batched_ingest(
            settings=settings(),
            client=SimpleNamespace(),
            execute=True,
            batch_size=1,
        )
    )

    assert result.processed_targets == 0

    assert (
        result
        .state_updates_committed
        == 1
    )

    assert (
        result
        .data_updates_committed
        == 1
    )

    assert len(committed) == 1


def test_error_is_persisted_and_retryable(
    monkeypatch,
):
    go = target("go")

    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        lambda **kwargs:
            planner((go,)),
    )

    monkeypatch.setattr(
        module,
        "prepare_batch",
        lambda **kwargs:
            batch(
                total=1,
                completed=0,
            ),
    )

    monkeypatch.setattr(
        module,
        "get_pending_items",
        lambda **kwargs: (
            item(1, go),
        ),
    )

    monkeypatch.setattr(
        module,
        "_ingest_target",
        lambda **kwargs:
            (_ for _ in ())
            .throw(
                RuntimeError(
                    "temporary failure"
                )
            ),
    )

    marked = []

    monkeypatch.setattr(
        module,
        "mark_item_error",
        lambda **kwargs:
            marked.append(
                kwargs
            ),
    )

    monkeypatch.setattr(
        module,
        "refresh_batch_progress",
        lambda **kwargs:
            batch(
                status="pending",
                total=1,
                completed=0,
            ),
    )

    result = (
        module.run_batched_ingest(
            settings=settings(),
            client=SimpleNamespace(),
            execute=True,
            batch_size=1,
        )
    )

    assert result.processed_targets == 0
    assert result.failed_targets == 1
    assert len(marked) == 1

    assert (
        "temporary failure"
        in marked[0][
            "error_message"
        ]
    )


def test_filter_processes_only_matching_target(
    monkeypatch,
):
    go = target("go")
    ac = target("ac")

    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        lambda **kwargs:
            planner(
                (
                    go,
                    ac,
                )
            ),
    )

    monkeypatch.setattr(
        module,
        "prepare_batch",
        lambda **kwargs:
            batch(
                total=2,
                completed=0,
            ),
    )

    monkeypatch.setattr(
        module,
        "get_pending_items",
        lambda **kwargs: (
            item(1, go),
            item(2, ac),
        ),
    )

    processed = []

    monkeypatch.setattr(
        module,
        "_ingest_target",
        lambda **kwargs: (
            processed.append(
                kwargs["target"]
            )
            or ingest_result(
                kwargs["target"]
            )
        ),
    )

    monkeypatch.setattr(
        module,
        "mark_item_completed",
        lambda **kwargs: None,
    )

    monkeypatch.setattr(
        module,
        "refresh_batch_progress",
        lambda **kwargs:
            batch(
                status="pending",
                total=2,
                completed=1,
            ),
    )

    result = (
        module.run_batched_ingest(
            settings=settings(),
            client=SimpleNamespace(),
            execute=True,
            batch_size=10,
            scope_code="go",
        )
    )

    assert len(processed) == 1
    assert (
        processed[0].scope_code
        == "go"
    )

    assert result.selected_targets == 1


def test_parallel_workers_fetch_concurrently_and_persist_serially(
    monkeypatch,
):
    targets = (
        target("go"),
        target("ac"),
        target("sp"),
    )

    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        lambda **kwargs:
            planner(targets),
    )

    monkeypatch.setattr(
        module,
        "prepare_batch",
        lambda **kwargs:
            batch(
                total=3,
                completed=0,
            ),
    )

    monkeypatch.setattr(
        module,
        "get_pending_items",
        lambda **kwargs: (
            item(1, targets[0]),
            item(2, targets[1]),
            item(3, targets[2]),
        ),
    )

    barrier = threading.Barrier(3)
    fetched_scopes = []
    persisted_scopes = []

    def fake_fetch_target(
        *,
        target,
        client,
    ):
        fetched_scopes.append(
            target.scope_code
        )

        barrier.wait(
            timeout=2
        )

        return SimpleNamespace(
            target=target
        )

    def fake_persist(
        *,
        fetched,
        settings,
    ):
        persisted_scopes.append(
            fetched.target.scope_code
        )

        return ingest_result(
            fetched.target
        )

    monkeypatch.setattr(
        module,
        "_fetch_target",
        fake_fetch_target,
    )

    monkeypatch.setattr(
        module,
        "_persist_fetched_target",
        fake_persist,
    )

    completed = []

    monkeypatch.setattr(
        module,
        "mark_item_completed",
        lambda **kwargs:
            completed.append(
                kwargs
            ),
    )

    monkeypatch.setattr(
        module,
        "refresh_batch_progress",
        lambda **kwargs:
            batch(
                status="pending",
                total=3,
                completed=3,
            ),
    )

    result = (
        module.run_batched_ingest(
            settings=settings(),
            client=SimpleNamespace(),
            execute=True,
            batch_size=3,
            workers=3,
        )
    )

    assert set(fetched_scopes) == {
        "go",
        "ac",
        "sp",
    }

    assert persisted_scopes == [
        "go",
        "ac",
        "sp",
    ]

    assert len(completed) == 3
    assert result.processed_targets == 3
    assert result.failed_targets == 0
    assert result.workers == 3

    assert result.candidates_processed == 30
    assert result.duration_ms >= 0
    assert result.planner_duration_ms >= 0
    assert result.fetch_duration_ms >= 0
    assert result.persist_duration_ms >= 0


def test_workers_must_be_positive():
    with pytest.raises(
        ValueError,
        match="workers must be",
    ):
        module.run_batched_ingest(
            settings=settings(),
            client=SimpleNamespace(),
            workers=0,
        )


def test_zero_target_state_update_skips_batch_and_publish_data(
    monkeypatch,
):
    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        lambda **kwargs:
            planner(()),
    )

    prepared = []

    monkeypatch.setattr(
        module,
        "prepare_batch",
        lambda **kwargs:
            prepared.append(
                kwargs
            ),
    )

    committed = []

    monkeypatch.setattr(
        module,
        "_commit_ea14_state",
        lambda election:
            committed.append(
                election
            ),
    )

    result = (
        module.run_batched_ingest(
            settings=settings(),
            client=SimpleNamespace(),
            execute=True,
            batch_size=25,
            workers=5,
        )
    )

    assert prepared == []
    assert len(committed) == 1
    assert result.planned_targets == 0
    assert result.processed_targets == 0

    assert (
        result.state_updates_committed
        == 1
    )

    assert (
        result.data_updates_committed
        == 0
    )

    assert result.elections == ()