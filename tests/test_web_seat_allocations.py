from pathlib import Path


ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

WEB = (
    ROOT
    / "web"
    / "public"
    / "eleicoes"
)


def test_seat_allocation_region_is_present():
    html = (
        WEB
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'id="seat-allocation"'
        in html
    )

    assert (
        'id="seat-allocation-grid"'
        in html
    )

    assert (
        "Vagas por partido/federação"
        in html
    )


def test_proportional_seat_allocation_is_rendered():
    app = (
        WEB
        / "app.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "PROPORTIONAL_OFFICES"
        in app
    )

    assert (
        "seat_allocations"
        in app
    )

    assert (
        "renderSeatAllocation()"
        in app
    )

    assert (
        "vagas atribuídas"
        in app
    )

    assert (
        '"Federação"'
        in app
    )

    assert (
        "renderSummary();\n"
        "    renderSeatAllocation();\n"
        "    renderResults();"
        in app
    )



def test_allocation_panel_lists_officially_elected_candidates():
    app = (
        WEB
        / "app.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "candidateIsOfficiallyElected"
        in app
    )

    assert (
        "electedCandidatesForGroup"
        in app
    )

    assert (
        "Eleitos pelo TSE"
        in app
    )

    assert (
        "Nenhum nome definido até o momento"
        in app
    )

    assert (
        "nomes definidos"
        in app
    )

    assert (
        'status === "eleito"'
        in app
    )

    assert (
        'status.startsWith('
        in app
    )
