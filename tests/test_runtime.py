from collector.src.runtime import (
    RuntimeSettings,
    build_config_url,
    select_supported_elections,
)


def build_config_payload():
    return {
        "pl": [
            {
                "c": "ele2024",
                "e": [
                    {
                        "cd": "100",
                        "t": "1",
                        "tp": "8",
                        "nm": "Federal antiga",
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
                    }
                ],
            },
            {
                "c": "ele2026",
                "e": [
                    {
                        "cd": "6257",
                        "t": "1",
                        "tp": "8",
                        "nm": "Federal 2026",
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
                        "cd": "6259",
                        "t": "1",
                        "tp": "1",
                        "nm": "Estadual 2026",
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
                                ],
                            }
                        ],
                    },
                    {
                        "cd": "6261",
                        "t": "1",
                        "tp": "3",
                        "nm": "Municipal 2026",
                        "abr": [
                            {
                                "cd": "br",
                                "cp": [
                                    {
                                        "cd": "25",
                                        "ds": "Conselheiro Distrital",
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "cd": "6258",
                        "t": "2",
                        "tp": "8",
                        "nm": "Federal 2026 2 turno",
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
                ],
            },
        ]
    }


def test_build_config_url():
    settings = RuntimeSettings(
        base_url="https://resultados.tse.jus.br",
        environment="oficial",
        cycle="ele2026",
        round_number=1,
    )

    assert build_config_url(settings) == (
        "https://resultados.tse.jus.br/"
        "oficial/comum/config/ele-c.json"
    )


def test_selects_only_current_supported_elections():
    settings = RuntimeSettings(
        base_url="https://example.invalid",
        environment="oficial",
        cycle="ele2026",
        round_number=1,
    )

    elections = select_supported_elections(
        build_config_payload(),
        settings,
    )

    assert [
        election.election_code
        for election in elections
    ] == [
        6257,
        6259,
    ]

    assert [
        election.election_type
        for election in elections
    ] == [
        8,
        1,
    ]
