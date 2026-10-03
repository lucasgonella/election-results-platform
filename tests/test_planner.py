import pytest

from collector.src.planner import (
    build_collection_plan,
    build_ea14_url,
)
from collector.src.runtime import (
    RuntimeSettings,
)


def build_config_payload():
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


def build_federal_ea14():
    return {
        "ele": "21270",
        "idg": "1001",
        "t": "1",
        "abr": [
            {
                "tpabr": "br",
                "cdabr": "br",
            },
            {
                "tpabr": "uf",
                "cdabr": "ac",
            },
            {
                "tpabr": "uf",
                "cdabr": "go",
            },
            {
                "tpabr": "uf",
                "cdabr": "df",
            },
            {
                "tpabr": "uf",
                "cdabr": "zz",
            },
        ],
    }


def build_state_ea14():
    return {
        "ele": "21272",
        "idg": "2001",
        "t": "1",
        "abr": [
            {
                "tpabr": "br",
                "cdabr": "br",
            },
            {
                "tpabr": "uf",
                "cdabr": "go",
            },
            {
                "tpabr": "uf",
                "cdabr": "df",
            },
        ],
    }


def build_settings():
    return RuntimeSettings(
        base_url=(
            "https://resultados-sim."
            "tse.jus.br/simulado"
        ),
        environment="simulado2026",
        cycle="ele2026",
        round_number=1,
    )


def test_builds_ea14_urls():
    settings = build_settings()

    assert build_ea14_url(
        settings=settings,
        election_code=21272,
    ) == (
        "https://resultados-sim."
        "tse.jus.br/simulado/"
        "simulado2026/"
        "ele2026/"
        "21272/"
        "dados/br/"
        "br-e021272-ab.json"
    )

    official = RuntimeSettings(
        base_url=(
            "https://resultados."
            "tse.jus.br"
        ),
        environment="oficial",
        cycle="ele2026",
        round_number=1,
    )

    assert build_ea14_url(
        settings=official,
        election_code=6259,
    ) == (
        "https://resultados."
        "tse.jus.br/"
        "oficial/"
        "ele2026/"
        "6259/"
        "dados/br/"
        "br-e006259-ab.json"
    )


def test_builds_independent_plan_per_election():
    plans = build_collection_plan(
        config_payload=(
            build_config_payload()
        ),
        ea14_payloads={
            21270:
                build_federal_ea14(),
            21272:
                build_state_ea14(),
        },
        settings=build_settings(),
    )

    assert len(plans) == 2

    by_code = {
        plan.election_code: plan
        for plan in plans
    }

    assert (
        by_code[21270].ea14_idg
        == "1001"
    )

    assert (
        by_code[21272].ea14_idg
        == "2001"
    )

    assert len(
        by_code[21270].targets
    ) == 5

    assert len(
        by_code[21272].targets
    ) == 8


def test_state_uses_its_own_ea14_scopes():
    plans = build_collection_plan(
        config_payload=(
            build_config_payload()
        ),
        ea14_payloads={
            21270:
                build_federal_ea14(),
            21272:
                build_state_ea14(),
        },
        settings=build_settings(),
    )

    state = next(
        plan
        for plan in plans
        if plan.election_code
        == 21272
    )

    state_scopes = {
        target.scope_code
        for target
        in state.targets
    }

    assert state_scopes == {
        "go",
        "df",
    }

    assert "ac" not in state_scopes
    assert "zz" not in state_scopes


def test_missing_ea14_is_rejected():
    with pytest.raises(
        ValueError,
        match="Missing EA14 payload",
    ):
        build_collection_plan(
            config_payload=(
                build_config_payload()
            ),
            ea14_payloads={
                21270:
                    build_federal_ea14(),
            },
            settings=build_settings(),
        )


def test_plan_urls_are_unique():
    plans = build_collection_plan(
        config_payload=(
            build_config_payload()
        ),
        ea14_payloads={
            21270:
                build_federal_ea14(),
            21272:
                build_state_ea14(),
        },
        settings=build_settings(),
    )

    urls = [
        target.url
        for plan in plans
        for target
        in plan.targets
    ]

    assert len(urls) == len(
        set(urls)
    )