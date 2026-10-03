from types import SimpleNamespace

import pytest

import collector.src.collector_runner as module

from collector.src.runtime import (
    RuntimeSettings,
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


def status(
    *,
    pending=136,
    completed=1,
    errors=0,
    health="ok",
    active=2,
    ea14_states=0,
):
    return SimpleNamespace(
        pending_items=pending,
        completed_items=completed,
        error_items=errors,
        health=health,
        active_batches=active,
        ea14_states=ea14_states,
    )


def batch_result(
    *,
    processed=10,
    failed=0,
    committed=0,
    planned=137,
    selected=137,
    errors=(),
):
    return SimpleNamespace(
        processed_targets=processed,
        failed_targets=failed,
        state_updates_committed=(
            committed
        ),
        planned_targets=planned,
        selected_targets=selected,
        errors=errors,
    )


def test_dry_run_does_not_execute(
    monkeypatch,
):
    before = status()

    monkeypatch.setattr(
        module,
        "_get_status",
        lambda settings:
            before,
    )

    received = []

    monkeypatch.setattr(
        module,
        "run_batched_ingest",
        lambda **kwargs: (
            received.append(kwargs)
            or batch_result(
                processed=0
            )
        ),
    )

    result = module.run_collector(
        settings=settings(),
        client=SimpleNamespace(),
    )

    assert not result.execute
    assert result.completed_cycles == 0
    assert result.stop_reason == "dry_run"

    assert (
        received[0]["execute"]
        is False
    )


def test_one_cycle_processes_batch(
    monkeypatch,
):
    states = iter(
        (
            status(
                pending=136,
                completed=1,
            ),
            status(
                pending=126,
                completed=11,
            ),
        )
    )

    monkeypatch.setattr(
        module,
        "_get_status",
        lambda settings:
            next(states),
    )

    monkeypatch.setattr(
        module,
        "run_batched_ingest",
        lambda **kwargs:
            batch_result(
                processed=10
            ),
    )

    result = module.run_collector(
        settings=settings(),
        client=SimpleNamespace(),
        execute=True,
        batch_size=10,
        cycles=1,
    )

    assert result.completed_cycles == 1
    assert result.processed_targets == 10
    assert result.failed_targets == 0

    assert (
        result.cycles[0]
        .pending_before
        == 136
    )

    assert (
        result.cycles[0]
        .pending_after
        == 126
    )

    assert (
        result.stop_reason
        == "cycle_limit"
    )


def test_runner_stops_on_error(
    monkeypatch,
):
    states = iter(
        (
            status(),
            status(
                pending=135,
                completed=1,
                errors=1,
                health="degraded",
            ),
        )
    )

    monkeypatch.setattr(
        module,
        "_get_status",
        lambda settings:
            next(states),
    )

    calls = []

    monkeypatch.setattr(
        module,
        "run_batched_ingest",
        lambda **kwargs: (
            calls.append(kwargs)
            or batch_result(
                processed=0,
                failed=1,
                errors=(
                    "temporary failure",
                ),
            )
        ),
    )

    result = module.run_collector(
        settings=settings(),
        client=SimpleNamespace(),
        execute=True,
        batch_size=10,
        cycles=5,
    )

    assert result.completed_cycles == 1
    assert result.failed_targets == 1
    assert result.stop_reason == "error"
    assert len(calls) == 1


def test_runner_stops_when_idle(
    monkeypatch,
):
    states = iter(
        (
            status(),
            status(),
        )
    )

    monkeypatch.setattr(
        module,
        "_get_status",
        lambda settings:
            next(states),
    )

    monkeypatch.setattr(
        module,
        "run_batched_ingest",
        lambda **kwargs:
            batch_result(
                processed=0,
                committed=0,
            ),
    )

    result = module.run_collector(
        settings=settings(),
        client=SimpleNamespace(),
        execute=True,
        cycles=5,
    )

    assert result.completed_cycles == 1
    assert result.stop_reason == "idle"


def test_cycles_must_be_positive():
    with pytest.raises(
        ValueError,
        match="cycles must be",
    ):
        module.run_collector(
            settings=settings(),
            client=SimpleNamespace(),
            cycles=0,
        )


def test_output_contains_before_after():
    before = status(
        pending=136,
        completed=1,
    )

    after = status(
        pending=126,
        completed=11,
    )

    result = (
        module.CollectorRunnerResult(
            execute=True,
            batch_size=10,
            workers=1,
            requested_cycles=1,
            completed_cycles=1,
            stop_reason="cycle_limit",
            planned_targets=137,
            selected_targets=137,
            processed_targets=10,
            failed_targets=0,
            state_updates_committed=0,
            before=before,
            after=after,
            cycles=(
                module.RunnerCycleSummary(
                    cycle_number=1,
                    processed_targets=10,
                    failed_targets=0,
                    state_updates_committed=0,
                    pending_before=136,
                    pending_after=126,
                    completed_after=11,
                    error_after=0,
                    health_after="ok",
                    errors=(),
                ),
            ),
        )
    )

    output = module._build_output(
        result,
        settings(),
        election_code=None,
        scope_code=None,
        office_code=None,
    )

    assert (
        output["before"]
        ["pending_items"]
        == 136
    )

    assert (
        output["after"]
        ["pending_items"]
        == 126
    )

    assert (
        output["cycles"][0]
        ["processed_targets"]
        == 10
    )

def test_exit_code_is_zero_on_success():
    result = SimpleNamespace(
        failed_targets=0,
        stop_reason="idle",
    )

    assert (
        module._exit_code(result)
        == 0
    )


def test_exit_code_is_nonzero_on_failure():
    failed = SimpleNamespace(
        failed_targets=1,
        stop_reason="error",
    )

    assert (
        module._exit_code(failed)
        == 1
    )

    stopped = SimpleNamespace(
        failed_targets=0,
        stop_reason="error",
    )

    assert (
        module._exit_code(stopped)
        == 1
    )


def test_workers_are_forwarded_to_batch_ingest(
    monkeypatch,
):
    states = iter(
        (
            status(),
            status(
                pending=131,
                completed=6,
            ),
        )
    )

    monkeypatch.setattr(
        module,
        "_get_status",
        lambda settings:
            next(states),
    )

    received = []

    monkeypatch.setattr(
        module,
        "run_batched_ingest",
        lambda **kwargs: (
            received.append(kwargs)
            or batch_result(
                processed=5
            )
        ),
    )

    result = module.run_collector(
        settings=settings(),
        client=SimpleNamespace(),
        execute=True,
        batch_size=10,
        workers=5,
        cycles=1,
    )

    assert result.workers == 5
    assert received[0]["workers"] == 5


def test_workers_must_be_positive():
    with pytest.raises(
        ValueError,
        match="workers must be",
    ):
        module.run_collector(
            settings=settings(),
            client=SimpleNamespace(),
            workers=0,
        )
