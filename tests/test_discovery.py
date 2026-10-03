from collections import Counter

from collector.src.discovery import (
    build_ea20_url,
    generate_targets,
    parse_ea14_scopes,
    parse_election_config,
)


UF_CODES = (
    "ac",
    "al",
    "ap",
    "am",
    "ba",
    "ce",
    "df",
    "es",
    "go",
    "ma",
    "mt",
    "ms",
    "mg",
    "pa",
    "pb",
    "pr",
    "pe",
    "pi",
    "rj",
    "rn",
    "rs",
    "ro",
    "rr",
    "sc",
    "sp",
    "se",
    "to",
)


def build_config_payload():
    return {
        "pl": [
            {
                "cd": "17801",
                "c": "ele2026",
                "dt": "26/04/2026",
                "e": [
                    {
                        "cd": "21274",
                        "t": "1",
                        "tp": "3",
                        "nm": "Municipal",
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


def build_ea14_payload():
    scopes = [
        {
            "tpabr": "uf",
            "cdabr": uf,
            "dt": "29/09/2026",
            "ht": "16:20:00",
        }
        for uf in UF_CODES
    ]

    scopes.append(
        {
            "tpabr": "uf",
            "cdabr": "zz",
            "dt": "29/09/2026",
            "ht": "16:20:00",
        }
    )

    scopes.append(
        {
            "tpabr": "br",
            "cdabr": "br",
            "dt": "29/09/2026",
            "ht": "16:20:00",
        }
    )

    return {
        "ele": "21270",
        "t": "1",
        "abr": scopes,
    }


def build_targets():
    return generate_targets(
        config_payload=build_config_payload(),
        ea14_payload=build_ea14_payload(),
        base_url=(
            "https://resultados-sim.tse.jus.br/"
            "simulado"
        ),
        environment="simulado2026",
    )


def test_parse_election_config():
    elections = parse_election_config(
        build_config_payload()
    )

    assert len(elections) == 3

    by_code = {
        election.election_code: election
        for election in elections
    }

    assert by_code[21270].cycle == "ele2026"
    assert by_code[21270].election_type == 8

    assert [
        office.code
        for office in by_code[21272].offices
    ] == [3, 5, 6, 7, 8]


def test_parse_ea14_scopes():
    scopes = parse_ea14_scopes(
        build_ea14_payload()
    )

    assert len(scopes) == 29

    assert sum(
        scope.is_federative_unit
        for scope in scopes
    ) == 27

    assert any(
        scope.is_exterior
        for scope in scopes
    )

    assert any(
        scope.is_brazil
        for scope in scopes
    )


def test_generates_expected_137_targets():
    targets = build_targets()

    assert len(targets) == 137

    elections = Counter(
        target.election_code
        for target in targets
    )

    assert elections == Counter(
        {
            21270: 29,
            21272: 108,
        }
    )

    offices = Counter(
        target.office_code
        for target in targets
    )

    assert offices == Counter(
        {
            1: 29,
            3: 27,
            5: 27,
            6: 27,
            7: 26,
            8: 1,
        }
    )


def test_municipal_election_is_not_generated():
    targets = build_targets()

    assert not any(
        target.election_code == 21274
        for target in targets
    )

    assert not any(
        target.office_code == 25
        for target in targets
    )


def test_exterior_only_has_president():
    targets = build_targets()

    exterior = [
        target
        for target in targets
        if target.scope_code == "zz"
    ]

    assert len(exterior) == 1

    assert exterior[0].election_code == 21270
    assert exterior[0].office_code == 1
    assert exterior[0].office_name == "Presidente"


def test_deputies_cover_all_states_and_df():
    targets = build_targets()

    federal = [
        target
        for target in targets
        if target.office_code == 6
    ]

    state = [
        target
        for target in targets
        if target.office_code == 7
    ]

    district = [
        target
        for target in targets
        if target.office_code == 8
    ]

    assert len(federal) == 27
    assert {
        target.scope_code
        for target in federal
    } == set(UF_CODES)

    assert len(state) == 26
    assert "df" not in {
        target.scope_code
        for target in state
    }

    assert len(district) == 1
    assert (
        district[0].scope_code
        == "df"
    )


def test_df_uses_district_not_state_deputy():
    targets = build_targets()

    df_offices = {
        target.office_code
        for target in targets
        if target.scope_code == "df"
    }

    assert 6 in df_offices
    assert 8 in df_offices
    assert 7 not in df_offices


def test_ea20_url_format():
    url = build_ea20_url(
        base_url=(
            "https://resultados-sim.tse.jus.br/"
            "simulado"
        ),
        environment="simulado2026",
        cycle="ele2026",
        election_code=21272,
        scope_code="go",
        office_code=3,
    )

    assert url == (
        "https://resultados-sim.tse.jus.br/"
        "simulado/"
        "simulado2026/"
        "ele2026/"
        "21272/"
        "dados/"
        "go/"
        "go-c0003-e021272-u.json"
    )


def test_all_targets_have_unique_urls():
    targets = build_targets()

    urls = [
        target.url
        for target in targets
    ]

    assert len(urls) == len(set(urls))