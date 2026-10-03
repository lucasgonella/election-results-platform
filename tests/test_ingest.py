from types import SimpleNamespace

import pytest

import collector.src.ingest as module

from collector.src.discovery import (
    ElectionTarget,
)
from collector.src.repository import (
    CachedFetchState,
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
    *,
    scope_code="go",
    office_code=3,
    election_code=21272,
):
    return ElectionTarget(
        election_code=(
            election_code
        ),
        cycle="ele2026",
        round_number=1,
        scope_code=scope_code,
        office_code=office_code,
        office_name="Teste",
        url=(
            "https://example.invalid/"
            f"{election_code}/"
            f"{scope_code}/"
            f"{office_code}.json"
        ),
    )


def state_update(
    election_code=21272,
):
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
            "ele": str(
                election_code
            ),
            "t": "1",
            "abr": [],
        },
    )

    return EA14StateUpdate(
        environment="simulado2026",
        cycle="ele2026",
        election_code=(
            election_code
        ),
        round_number=1,
        fetch_result=fetch,
        payload=fetch.payload,
    )


def election_result(
    *,
    targets=(),
    update=None,
    election_code=21272,
):
    return StatefulElectionResult(
        election_code=(
            election_code
        ),
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
        state_update=update,
    )


def planner_result(
    *elections,
):
    return StatefulPlannerResult(
        config_url=(
            "https://example.invalid/"
            "ele-c.json"
        ),
        elections=tuple(
            elections
        ),
    )


class FakeClient:
    def __init__(
        self,
        responses=None,
    ):
        self.responses = (
            responses
            or {}
        )

        self.calls = []

    def fetch_json(
        self,
        url,
        *,
        etag=None,
        last_modified=None,
    ):
        self.calls.append(
            {
                "url": url,
                "etag": etag,
                "last_modified":
                    last_modified,
            }
        )

        return self.responses[
            url
        ]


def test_dry_run_does_not_ingest_or_commit(
    monkeypatch,
):
    planned = target()

    planner = planner_result(
        election_result(
            targets=(planned,),
            update=state_update(),
        )
    )

    received = {}

    def fake_planner(**kwargs):
        received.update(
            kwargs
        )

        return planner

    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        fake_planner,
    )

    saved = []

    monkeypatch.setattr(
        module,
        "save_ea14_state",
        lambda **kwargs:
            saved.append(kwargs),
    )

    result = (
        module.run_selective_ingest(
            settings=settings(),
            client=FakeClient(),
        )
    )

    assert not result.execute
    assert result.planned_targets == 1
    assert result.processed_targets == 0
    assert (
        result
        .state_updates_committed
        == 0
    )

    assert saved == []

    assert (
        received["persist_state"]
        is False
    )


def test_max_targets_blocks_before_ea20(
    monkeypatch,
):
    targets = tuple(
        target(
            scope_code=f"x{index}",
        )
        for index in range(11)
    )

    planner = planner_result(
        election_result(
            targets=targets,
            update=state_update(),
        )
    )

    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        lambda **kwargs:
            planner,
    )

    client = FakeClient()

    saved = []

    monkeypatch.setattr(
        module,
        "save_ea14_state",
        lambda **kwargs:
            saved.append(kwargs),
    )

    with pytest.raises(
        RuntimeError,
        match="exceeds max_targets",
    ):
        module.run_selective_ingest(
            settings=settings(),
            client=client,
            execute=True,
            max_targets=10,
        )

    assert client.calls == []
    assert saved == []


def test_official_execute_is_blocked_before_planner(
    monkeypatch,
):
    called = []

    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        lambda **kwargs:
            called.append(kwargs),
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "official TSE environment"
        ),
    ):
        module.run_selective_ingest(
            settings=settings(
                environment="oficial",
                base_url=(
                    "https://"
                    "resultados.tse.jus.br"
                ),
            ),
            execute=True,
        )

    assert called == []


def test_successful_ea20_is_persisted_then_ea14_committed(
    monkeypatch,
):
    planned = target()

    planner = planner_result(
        election_result(
            targets=(planned,),
            update=state_update(),
        )
    )

    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        lambda **kwargs:
            planner,
    )

    response = TseFetchResult(
        url=planned.url,
        status_code=200,
        etag='"ea20"',
        last_modified="last",
        sha256="b" * 64,
        payload={
            "fake": "payload",
        },
    )

    client = FakeClient(
        {
            planned.url:
                response,
        }
    )

    monkeypatch.setattr(
        module,
        "get_last_fetch_state",
        lambda url: None,
    )

    parsed = SimpleNamespace(
        election_code=21272,
        round_number=1,
        scope_code="go",
        tse_idg=12345,
        offices=(
            SimpleNamespace(
                code=3
            ),
        ),
    )

    monkeypatch.setattr(
        module,
        "parse_ea20",
        lambda payload:
            parsed,
    )

    monkeypatch.setattr(
        module,
        "persist_result",
        lambda *args, **kwargs:
            SimpleNamespace(
                collector_run_id=10,
                snapshots_created=1,
                candidates_processed=8,
            ),
    )

    saved = []

    monkeypatch.setattr(
        module,
        "save_ea14_state",
        lambda **kwargs:
            saved.append(kwargs),
    )

    result = (
        module.run_selective_ingest(
            settings=settings(),
            client=client,
            execute=True,
            max_targets=1,
        )
    )

    assert (
        result.processed_targets
        == 1
    )

    assert (
        result
        .state_updates_committed
        == 1
    )

    assert (
        result.results[0].status
        == "success"
    )

    assert len(saved) == 1


def test_ea20_304_uses_cached_state(
    monkeypatch,
):
    planned = target()

    planner = planner_result(
        election_result(
            targets=(planned,),
            update=state_update(),
        )
    )

    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        lambda **kwargs:
            planner,
    )

    cached = CachedFetchState(
        etag='"old"',
        last_modified="old-last",
        tse_idg=9988,
        election_code=21272,
        scope_code="go",
        office_code=3,
    )

    monkeypatch.setattr(
        module,
        "get_last_fetch_state",
        lambda url:
            cached,
    )

    response = TseFetchResult(
        url=planned.url,
        status_code=304,
        etag='"old"',
        last_modified="old-last",
        sha256=None,
        payload=None,
    )

    client = FakeClient(
        {
            planned.url:
                response,
        }
    )

    monkeypatch.setattr(
        module,
        "record_not_modified",
        lambda *args:
            77,
    )

    saved = []

    monkeypatch.setattr(
        module,
        "save_ea14_state",
        lambda **kwargs:
            saved.append(kwargs),
    )

    result = (
        module.run_selective_ingest(
            settings=settings(),
            client=client,
            execute=True,
            max_targets=1,
        )
    )

    assert (
        result.results[0].status
        == "not_modified"
    )

    assert (
        result.results[0]
        .collector_run_id
        == 77
    )

    assert (
        client.calls[0]["etag"]
        == '"old"'
    )

    assert (
        client.calls[0]
        ["last_modified"]
        == "old-last"
    )

    assert len(saved) == 1


def test_invalid_ea20_does_not_commit_ea14(
    monkeypatch,
):
    planned = target()

    planner = planner_result(
        election_result(
            targets=(planned,),
            update=state_update(),
        )
    )

    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        lambda **kwargs:
            planner,
    )

    response = TseFetchResult(
        url=planned.url,
        status_code=200,
        etag=None,
        last_modified=None,
        sha256="c" * 64,
        payload={
            "fake": "payload",
        },
    )

    client = FakeClient(
        {
            planned.url:
                response,
        }
    )

    monkeypatch.setattr(
        module,
        "get_last_fetch_state",
        lambda url: None,
    )

    monkeypatch.setattr(
        module,
        "parse_ea20",
        lambda payload:
            SimpleNamespace(
                election_code=21272,
                round_number=1,
                scope_code="ac",
                tse_idg=1,
                offices=(
                    SimpleNamespace(
                        code=3
                    ),
                ),
            ),
    )

    saved = []

    monkeypatch.setattr(
        module,
        "save_ea14_state",
        lambda **kwargs:
            saved.append(kwargs),
    )

    with pytest.raises(
        ValueError,
        match="EA20 scope mismatch",
    ):
        module.run_selective_ingest(
            settings=settings(),
            client=client,
            execute=True,
            max_targets=1,
        )

    assert saved == []


def test_zero_target_state_update_is_committed_on_execute(
    monkeypatch,
):
    planner = planner_result(
        election_result(
            targets=(),
            update=state_update(),
        )
    )

    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        lambda **kwargs:
            planner,
    )

    saved = []

    monkeypatch.setattr(
        module,
        "save_ea14_state",
        lambda **kwargs:
            saved.append(kwargs),
    )

    result = (
        module.run_selective_ingest(
            settings=settings(),
            client=FakeClient(),
            execute=True,
            max_targets=1,
        )
    )

    assert result.planned_targets == 0
    assert result.processed_targets == 0

    assert (
        result
        .state_updates_committed
        == 1
    )

    assert len(saved) == 1


def test_filter_allows_one_target_from_large_plan(
    monkeypatch,
):
    go = target(
        scope_code="go",
        office_code=3,
    )

    ac = target(
        scope_code="ac",
        office_code=3,
    )

    planner = planner_result(
        election_result(
            targets=(go, ac),
            update=state_update(),
        )
    )

    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        lambda **kwargs:
            planner,
    )

    response = TseFetchResult(
        url=go.url,
        status_code=200,
        etag='"go"',
        last_modified="last",
        sha256="d" * 64,
        payload={"fake": "go"},
    )

    client = FakeClient(
        {
            go.url:
                response,
        }
    )

    monkeypatch.setattr(
        module,
        "get_last_fetch_state",
        lambda url: None,
    )

    monkeypatch.setattr(
        module,
        "parse_ea20",
        lambda payload:
            SimpleNamespace(
                election_code=21272,
                round_number=1,
                scope_code="go",
                tse_idg=123,
                offices=(
                    SimpleNamespace(
                        code=3
                    ),
                ),
            ),
    )

    monkeypatch.setattr(
        module,
        "persist_result",
        lambda *args, **kwargs:
            SimpleNamespace(
                collector_run_id=1,
                snapshots_created=1,
                candidates_processed=9,
            ),
    )

    saved = []

    monkeypatch.setattr(
        module,
        "save_ea14_state",
        lambda **kwargs:
            saved.append(kwargs),
    )

    result = (
        module.run_selective_ingest(
            settings=settings(),
            client=client,
            execute=True,
            max_targets=1,
            scope_code="go",
            office_code=3,
        )
    )

    assert result.planned_targets == 2
    assert result.selected_targets == 1
    assert result.processed_targets == 1

    assert (
        result.results[0].scope_code
        == "go"
    )

    assert saved == []

    assert (
        result
        .state_updates_committed
        == 0
    )


def test_filter_matching_entire_election_can_commit(
    monkeypatch,
):
    go = target(
        scope_code="go",
        office_code=3,
    )

    planner = planner_result(
        election_result(
            targets=(go,),
            update=state_update(),
        )
    )

    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        lambda **kwargs:
            planner,
    )

    response = TseFetchResult(
        url=go.url,
        status_code=200,
        etag='"go"',
        last_modified="last",
        sha256="e" * 64,
        payload={"fake": "go"},
    )

    client = FakeClient(
        {
            go.url:
                response,
        }
    )

    monkeypatch.setattr(
        module,
        "get_last_fetch_state",
        lambda url: None,
    )

    monkeypatch.setattr(
        module,
        "parse_ea20",
        lambda payload:
            SimpleNamespace(
                election_code=21272,
                round_number=1,
                scope_code="go",
                tse_idg=123,
                offices=(
                    SimpleNamespace(
                        code=3
                    ),
                ),
            ),
    )

    monkeypatch.setattr(
        module,
        "persist_result",
        lambda *args, **kwargs:
            SimpleNamespace(
                collector_run_id=1,
                snapshots_created=1,
                candidates_processed=9,
            ),
    )

    saved = []

    monkeypatch.setattr(
        module,
        "save_ea14_state",
        lambda **kwargs:
            saved.append(kwargs),
    )

    result = (
        module.run_selective_ingest(
            settings=settings(),
            client=client,
            execute=True,
            max_targets=1,
            scope_code="go",
            office_code=3,
        )
    )

    assert (
        result
        .state_updates_committed
        == 1
    )

    assert len(saved) == 1


def test_filter_is_case_insensitive():
    planned = target(
        scope_code="go",
        office_code=3,
    )

    assert module._target_matches(
        planned,
        election_code=21272,
        scope_code="GO",
        office_code=3,
    )


def test_filter_with_no_match_commits_nothing(
    monkeypatch,
):
    go = target(
        scope_code="go",
        office_code=3,
    )

    planner = planner_result(
        election_result(
            targets=(go,),
            update=state_update(),
        )
    )

    monkeypatch.setattr(
        module,
        "run_stateful_planner",
        lambda **kwargs:
            planner,
    )

    saved = []

    monkeypatch.setattr(
        module,
        "save_ea14_state",
        lambda **kwargs:
            saved.append(kwargs),
    )

    result = (
        module.run_selective_ingest(
            settings=settings(),
            client=FakeClient(),
            execute=True,
            max_targets=1,
            scope_code="xx",
        )
    )

    assert result.selected_targets == 0
    assert result.processed_targets == 0
    assert saved == []
