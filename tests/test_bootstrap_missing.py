from types import SimpleNamespace

import pytest

import collector.src.bootstrap_missing as module

from collector.src.discovery import (
    ElectionTarget,
)
from collector.src.runtime import (
    RuntimeSettings,
)


def settings(
    *,
    environment="simulado2026",
    base_url=(
        "https://resultados-sim."
        "tse.jus.br/simulado"
    ),
):
    return RuntimeSettings(
        base_url=base_url,
        environment=environment,
        cycle="ele2026",
        round_number=1,
    )


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


def plan(*targets):
    return (
        SimpleNamespace(
            targets=tuple(
                targets
            )
        ),
    )


def ingest_result(
    target_item,
):
    return SimpleNamespace(
        election_code=(
            target_item
            .election_code
        ),
        scope_code=(
            target_item.scope_code
        ),
        office_code=(
            target_item.office_code
        ),
        status="success",
        http_status=200,
        tse_idg=123,
        candidates_processed=10,
    )


def test_dry_run_finds_only_missing_targets(
    monkeypatch,
):
    go = target("go", 6)
    ac = target("ac", 6)
    df = target("df", 8)

    monkeypatch.setattr(
        module,
        "fetch_collection_plan",
        lambda **kwargs:
            plan(
                go,
                ac,
                df,
            ),
    )

    monkeypatch.setattr(
        module,
        "list_existing_target_keys",
        lambda **kwargs: {
            module._target_key(go),
        },
    )

    result = (
        module.run_bootstrap_missing(
            settings=settings(),
            client=SimpleNamespace(),
            batch_size=25,
            workers=5,
        )
    )

    assert not result.execute
    assert result.planned_targets == 3
    assert result.existing_targets == 1
    assert result.missing_before == 2
    assert result.selected_targets == 2
    assert result.processed_targets == 0
    assert result.remaining_after == 2


def test_execute_persists_missing_targets(
    monkeypatch,
):
    go = target("go", 6)
    ac = target("ac", 6)
    df = target("df", 8)

    monkeypatch.setattr(
        module,
        "fetch_collection_plan",
        lambda **kwargs:
            plan(
                go,
                ac,
                df,
            ),
    )

    monkeypatch.setattr(
        module,
        "list_existing_target_keys",
        lambda **kwargs: {
            module._target_key(go),
        },
    )

    fetched = []

    monkeypatch.setattr(
        module,
        "_fetch_target_unconditional",
        lambda **kwargs: (
            fetched.append(
                kwargs["target"]
            )
            or SimpleNamespace(
                target=(
                    kwargs["target"]
                )
            )
        ),
    )

    persisted = []

    monkeypatch.setattr(
        module,
        "_persist_fetched_target",
        lambda **kwargs: (
            persisted.append(
                kwargs[
                    "fetched"
                ].target
            )
            or ingest_result(
                kwargs[
                    "fetched"
                ].target
            )
        ),
    )

    result = (
        module.run_bootstrap_missing(
            settings=settings(),
            client=SimpleNamespace(),
            execute=True,
            batch_size=25,
            workers=1,
        )
    )

    assert fetched == [
        ac,
        df,
    ]

    assert persisted == [
        ac,
        df,
    ]

    assert result.processed_targets == 2
    assert result.failed_targets == 0
    assert result.remaining_after == 0


def test_batch_size_limits_bootstrap(
    monkeypatch,
):
    targets = tuple(
        target(
            f"x{index}",
            6,
        )
        for index in range(5)
    )

    monkeypatch.setattr(
        module,
        "fetch_collection_plan",
        lambda **kwargs:
            plan(
                *targets
            ),
    )

    monkeypatch.setattr(
        module,
        "list_existing_target_keys",
        lambda **kwargs:
            set(),
    )

    selected = []

    monkeypatch.setattr(
        module,
        "_fetch_target_unconditional",
        lambda **kwargs: (
            selected.append(
                kwargs["target"]
            )
            or SimpleNamespace(
                target=(
                    kwargs["target"]
                )
            )
        ),
    )

    monkeypatch.setattr(
        module,
        "_persist_fetched_target",
        lambda **kwargs:
            ingest_result(
                kwargs[
                    "fetched"
                ].target
            ),
    )

    result = (
        module.run_bootstrap_missing(
            settings=settings(),
            client=SimpleNamespace(),
            execute=True,
            batch_size=2,
            workers=1,
        )
    )

    assert len(selected) == 2
    assert result.missing_before == 5
    assert result.processed_targets == 2
    assert result.remaining_after == 3


def test_official_bootstrap_requires_explicit_gate(
    monkeypatch,
):
    monkeypatch.setattr(
        module,
        "fetch_collection_plan",
        lambda **kwargs:
            pytest.fail(
                "planner should not run"
            ),
    )

    with pytest.raises(
        RuntimeError,
        match="official TSE",
    ):
        module.run_bootstrap_missing(
            settings=settings(
                environment="oficial",
                base_url=(
                    "https://resultados."
                    "tse.jus.br"
                ),
            ),
            client=SimpleNamespace(),
            execute=True,
        )


def test_workers_must_be_positive():
    with pytest.raises(
        ValueError,
        match="workers must be",
    ):
        module.run_bootstrap_missing(
            settings=settings(),
            client=SimpleNamespace(),
            workers=0,
        )
