from decimal import Decimal

import pytest

from collector.src.parser import (
    as_bool,
    as_decimal,
    as_int,
    parse_ea20,
)


def build_payload():
    return {
        "ele": "21272",
        "t": "1",
        "tpabr": "uf",
        "cdabr": "ac",
        "idg": "123456",
        "dg": "03/10/2026",
        "hg": "12:00:00",
        "dt": "03/10/2026",
        "ht": "11:59:59",
        "s": {
            "ts": "100",
            "st": "50",
            "pstn": "50",
        },
        "e": {
            "te": "1000",
            "est": "1000",
            "c": "800",
            "pcn": "80",
            "a": "200",
            "pan": "20",
        },
        "v": {
            "tv": "800",
            "vvc": "700",
            "vv": "680",
            "vb": "50",
            "tvn": "70",
        },
        "carg": [
            {
                "cd": "3",
                "nmn": "Governador",
                "nv": "1",
                "agr": [
                    {
                        "n": "1",
                        "nm": "Coligação Teste",
                        "tp": "c",
                        "par": [
                            {
                                "n": "99",
                                "sg": "PTST",
                                "nm": "PARTIDO TESTE",
                                "cand": [
                                    {
                                        "n": "99",
                                        "sqcand": "200",
                                        "seq": "2",
                                        "nm": "Candidato B",
                                        "nmu": "B",
                                        "dt": "01/01/1980",
                                        "dvt": "Válido",
                                        "st": "Não eleito",
                                        "e": "n",
                                        "vap": "300",
                                        "pvapn": "44,117647059",
                                        "vs": [],
                                    },
                                    {
                                        "n": "98",
                                        "sqcand": "100",
                                        "seq": "1",
                                        "nm": "Candidato A",
                                        "nmu": "A",
                                        "dt": "02/02/1980",
                                        "dvt": "Válido",
                                        "st": "2º turno",
                                        "e": "s",
                                        "vap": "380",
                                        "pvapn": "55,882352941",
                                        "vs": [],
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }


def test_as_int():
    assert as_int("123") == 123
    assert as_int("") is None
    assert as_int(None) is None


def test_as_decimal_handles_tse_comma():
    assert as_decimal("10,849742616") == Decimal(
        "10.849742616"
    )


def test_as_bool():
    assert as_bool("s") is True
    assert as_bool("n") is False
    assert as_bool("") is None


def test_parse_ea20():
    result = parse_ea20(build_payload())

    assert result.election_code == 21272
    assert result.round_number == 1

    assert result.scope_type == "uf"
    assert result.scope_code == "ac"

    assert result.stats.sections_total == 100
    assert result.stats.sections_totalized == 50
    assert result.stats.sections_percentage == Decimal("50")

    assert result.mathematical_definition is None
    assert result.totalization_final is None

    assert len(result.offices) == 1

    office = result.offices[0]

    assert office.code == 3
    assert office.name == "Governador"
    assert len(office.candidates) == 2

    assert office.candidates[0].name == "Candidato A"
    assert office.candidates[0].display_order == 1

    assert office.candidates[1].name == "Candidato B"
    assert office.candidates[1].display_order == 2


def test_duplicate_candidate_is_rejected():
    payload = build_payload()

    candidates = (
        payload["carg"][0]
        ["agr"][0]
        ["par"][0]
        ["cand"]
    )

    candidates[1]["sqcand"] = candidates[0]["sqcand"]

    with pytest.raises(
        ValueError,
        match="Duplicate candidate",
    ):
        parse_ea20(payload)



def test_parse_proportional_seat_allocation():
    payload = build_payload()

    office_payload = payload["carg"][0]
    office_payload["cd"] = "6"
    office_payload["nmn"] = (
        "Deputado Federal"
    )
    office_payload["nv"] = "17"
    office_payload["qe"] = "123456"

    alliance = (
        office_payload["agr"][0]
    )
    alliance["tp"] = "f"
    alliance["vag"] = "5"
    alliance["com"] = (
        "PTST / OUT"
    )

    result = parse_ea20(payload)
    office = result.offices[0]

    assert office.code == 6
    assert office.seats == 17
    assert (
        office.electoral_quotient
        == 123456
    )

    assert (
        len(office.seat_allocations)
        == 1
    )

    allocation = (
        office.seat_allocations[0]
    )

    assert allocation.kind == "f"
    assert allocation.seats == 5
    assert (
        allocation.composition
        == "PTST / OUT"
    )
    assert (
        allocation.parties[0]
        ["acronym"]
        == "PTST"
    )



def test_parse_mathematical_definition():
    payload = build_payload()
    payload["md"] = "e"
    payload["tf"] = "n"

    result = parse_ea20(payload)

    assert (
        result.mathematical_definition
        == "e"
    )
    assert (
        result.totalization_final
        is False
    )
