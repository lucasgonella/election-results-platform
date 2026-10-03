from datetime import (
    datetime,
    timezone,
)

import collector.src.stateful_planner as module

from collector.src.ea14_state_repository import (
    StoredEA14State,
)
from collector.src.runtime import (
    RuntimeSettings,
    build_config_url,
)
from collector.src.planner import (
    build_ea14_url,
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


def config_payload():
    return {
        "pl": [
            {
                "c": "ele2026",
                "e": [
                    {
                        "cd": "21270",
                        "t": "1",
                        "tp": "8",
                        "nm": "Federal",
                        "abr": [
                            {
                                "cd": "br",
                                "cp": [
                                    {
                                        "cd": "1",
                                        "ds": "Presidente",
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "cd": "21272",
                        "t": "1",
                        "tp": "1",
                        "nm": "Estadual",
                        "abr": [
                            {
                                "cd": "br",
                                "cp": [
                                    {
                                        "cd": "3",
                                        "ds": "Governador",
                                    },
                                    {
                                        "cd": "5",
                                        "ds": "Senador",
                                    },
                                    {
                                        "cd": "6",
                                        "ds": "Deputado Federal",
                                    },
                                    {
                                        "cd": "7",
                                        "ds": "Deputado Estadual",
                                    },
                                    {
                                        "cd": "8",
                                        "ds": "Deputado Distrital",
                                    },
                                ],
                            }
                        ],
                    },
                ],
            }
        ]
    }


def scope(
    code,
    *,
    time="16:20:00",
):
    return {
        "tpabr": (
            "br"
            if code == "br"
            else "uf"
        ),
        "cdabr": code,
        "and": "f",
        "dt": "29/09/2026",
        "ht": time,
        "s": {
            "ts": "100",
            "st": "100",
            "pstn": "100",
        },
    }


def federal_payload():
    return {
        "ele": "21270",
        "t": "1",
        "idg": "1001",
        "abr": [
            scope("br"),
            scope("ac"),
            scope("go"),
            scope("df"),
            scope("zz"),
        ],
    }


def state_payload(
    *,
    go_time="16:20:00",
):
    return {
        "ele": "21272",
        "t": "1",
        "idg": "2001",
        "abr": [
            scope(
                "go",
                time=go_time,
            ),
            scope("df"),
        ],
    }


def fetch_result(
    url,
    payload,
    *,
    status_code=200,
    etag=None,
    last_modified=None,
):
    return TseFetchResult(
        url=url,
        status_code=status_code,
        etag=etag,
        last_modified=last_modified,
        sha256=(
            "a" * 64
            if payload is not None
            else None
        ),
        payload=payload,
    )


class FakeClient:
    def __init__(
        self,
        responses,
    ):
        self.responses = responses
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

        return self.responses[url]


def stored_state(
    *,
    election_code,
    payload,
    etag='"stored-etag"',
    last_modified=(
        "Tue, 29 Sep 2026 "
        "19:20:00 GMT"
    ),
):
    return StoredEA14State(
        id=election_code,
        environment="simulado2026",
        cycle="ele2026",
        election_code=election_code,
        round_number=1,
        tse_idg=int(
            payload["idg"]
        ),
        source_url=(
            "https://example.invalid/"
            f"{election_code}.json"
        ),
        etag=etag,
        last_modified=last_modified,
        payload_sha256="b" * 64,
        payload=payload,
        captured_at=datetime(
            2026,
            9,
            29,
            19,
            20,
            tzinfo=timezone.utc,
        ),
    )


def urls():
    current = settings()

    return {
        "config":
            build_config_url(
                current
            ),

        "federal":
            build_ea14_url(
                settings=current,
                election_code=21270,
            ),

        "state":
            build_ea14_url(
                settings=current,
                election_code=21272,
            ),
    }


def test_first_run_selects_all_targets(
    monkeypatch,
):
    current_urls = urls()

    client = FakeClient(
        {
            current_urls["config"]:
                fetch_result(
                    current_urls["config"],
                    config_payload(),
                ),

            current_urls["federal"]:
                fetch_result(
                    current_urls["federal"],
                    federal_payload(),
                    etag='"federal"',
                ),

            current_urls["state"]:
                fetch_result(
                    current_urls["state"],
                    state_payload(),
                    etag='"state"',
                ),
        }
    )

    monkeypatch.setattr(
        module,
        "get_ea14_state",
        lambda **kwargs: None,
    )

    saved = []

    monkeypatch.setattr(
        module,
        "save_ea14_state",
        lambda **kwargs:
            saved.append(kwargs),
    )

    result = (
        module.run_stateful_planner(
            settings=settings(),
            client=client,
        )
    )

    assert len(
        result.targets
    ) == 13

    by_code = {
        election.election_code:
            election
        for election
        in result.elections
    }

    assert (
        by_code[21270].status
        == "initialized"
    )

    assert (
        len(
            by_code[21270].targets
        )
        == 5
    )

    assert (
        len(
            by_code[21272].targets
        )
        == 8
    )

    assert len(saved) == 2


def test_304_returns_zero_targets(
    monkeypatch,
):
    current_urls = urls()

    federal_previous = (
        federal_payload()
    )

    state_previous = (
        state_payload()
    )

    states = {
        21270:
            stored_state(
                election_code=21270,
                payload=(
                    federal_previous
                ),
                etag='"f-etag"',
            ),

        21272:
            stored_state(
                election_code=21272,
                payload=(
                    state_previous
                ),
                etag='"s-etag"',
            ),
    }

    client = FakeClient(
        {
            current_urls["config"]:
                fetch_result(
                    current_urls["config"],
                    config_payload(),
                ),

            current_urls["federal"]:
                fetch_result(
                    current_urls["federal"],
                    None,
                    status_code=304,
                    etag='"f-etag"',
                ),

            current_urls["state"]:
                fetch_result(
                    current_urls["state"],
                    None,
                    status_code=304,
                    etag='"s-etag"',
                ),
        }
    )

    monkeypatch.setattr(
        module,
        "get_ea14_state",
        lambda **kwargs:
            states[
                kwargs[
                    "election_code"
                ]
            ],
    )

    saved = []

    monkeypatch.setattr(
        module,
        "save_ea14_state",
        lambda **kwargs:
            saved.append(kwargs),
    )

    result = (
        module.run_stateful_planner(
            settings=settings(),
            client=client,
        )
    )

    assert result.targets == ()

    assert all(
        election.status
        == "not_modified"
        for election
        in result.elections
    )

    assert saved == []


def test_conditional_headers_are_used(
    monkeypatch,
):
    current_urls = urls()

    states = {
        21270:
            stored_state(
                election_code=21270,
                payload=(
                    federal_payload()
                ),
                etag='"f-etag"',
                last_modified="f-last",
            ),

        21272:
            stored_state(
                election_code=21272,
                payload=(
                    state_payload()
                ),
                etag='"s-etag"',
                last_modified="s-last",
            ),
    }

    client = FakeClient(
        {
            current_urls["config"]:
                fetch_result(
                    current_urls["config"],
                    config_payload(),
                ),

            current_urls["federal"]:
                fetch_result(
                    current_urls["federal"],
                    None,
                    status_code=304,
                ),

            current_urls["state"]:
                fetch_result(
                    current_urls["state"],
                    None,
                    status_code=304,
                ),
        }
    )

    monkeypatch.setattr(
        module,
        "get_ea14_state",
        lambda **kwargs:
            states[
                kwargs[
                    "election_code"
                ]
            ],
    )

    module.run_stateful_planner(
        settings=settings(),
        client=client,
    )

    federal_call = next(
        call
        for call in client.calls
        if call["url"]
        == current_urls["federal"]
    )

    state_call = next(
        call
        for call in client.calls
        if call["url"]
        == current_urls["state"]
    )

    assert (
        federal_call["etag"]
        == '"f-etag"'
    )

    assert (
        federal_call[
            "last_modified"
        ]
        == "f-last"
    )

    assert (
        state_call["etag"]
        == '"s-etag"'
    )

    assert (
        state_call[
            "last_modified"
        ]
        == "s-last"
    )


def test_unchanged_200_returns_zero(
    monkeypatch,
):
    current_urls = urls()

    previous = federal_payload()

    states = {
        21270:
            stored_state(
                election_code=21270,
                payload=previous,
            ),

        21272:
            stored_state(
                election_code=21272,
                payload=state_payload(),
            ),
    }

    client = FakeClient(
        {
            current_urls["config"]:
                fetch_result(
                    current_urls["config"],
                    config_payload(),
                ),

            current_urls["federal"]:
                fetch_result(
                    current_urls["federal"],
                    federal_payload(),
                    etag='"new-f"',
                ),

            current_urls["state"]:
                fetch_result(
                    current_urls["state"],
                    None,
                    status_code=304,
                ),
        }
    )

    monkeypatch.setattr(
        module,
        "get_ea14_state",
        lambda **kwargs:
            states[
                kwargs[
                    "election_code"
                ]
            ],
    )

    saved = []

    monkeypatch.setattr(
        module,
        "save_ea14_state",
        lambda **kwargs:
            saved.append(kwargs),
    )

    result = (
        module.run_stateful_planner(
            settings=settings(),
            client=client,
        )
    )

    assert result.targets == ()

    federal = next(
        election
        for election
        in result.elections
        if election.election_code
        == 21270
    )

    assert (
        federal.status
        == "unchanged"
    )

    assert len(saved) == 1


def test_only_changed_go_targets_selected(
    monkeypatch,
):
    current_urls = urls()

    states = {
        21270:
            stored_state(
                election_code=21270,
                payload=(
                    federal_payload()
                ),
            ),

        21272:
            stored_state(
                election_code=21272,
                payload=(
                    state_payload(
                        go_time="16:20:00"
                    )
                ),
            ),
    }

    client = FakeClient(
        {
            current_urls["config"]:
                fetch_result(
                    current_urls["config"],
                    config_payload(),
                ),

            current_urls["federal"]:
                fetch_result(
                    current_urls["federal"],
                    None,
                    status_code=304,
                ),

            current_urls["state"]:
                fetch_result(
                    current_urls["state"],
                    state_payload(
                        go_time="16:25:00"
                    ),
                    etag='"new-state"',
                ),
        }
    )

    monkeypatch.setattr(
        module,
        "get_ea14_state",
        lambda **kwargs:
            states[
                kwargs[
                    "election_code"
                ]
            ],
    )

    saved = []

    monkeypatch.setattr(
        module,
        "save_ea14_state",
        lambda **kwargs:
            saved.append(kwargs),
    )

    result = (
        module.run_stateful_planner(
            settings=settings(),
            client=client,
        )
    )

    assert len(
        result.targets
    ) == 4

    assert {
        target.scope_code
        for target
        in result.targets
    } == {
        "go",
    }

    assert {
        target.office_code
        for target
        in result.targets
    } == {
        3,
        5,
        6,
        7,
    }

    state = next(
        election
        for election
        in result.elections
        if election.election_code
        == 21272
    )

    assert (
        state.status
        == "changed"
    )

    assert (
        state.changed_scopes
        == ("go",)
    )

    assert len(saved) == 1
