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


def test_elected_alert_region_is_present():
    html = (
        WEB
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'id="elected-alerts"'
        in html
    )

    assert (
        'aria-live="polite"'
        in html
    )


def test_elected_alert_feed_is_loaded_on_publication():
    app = (
        WEB
        / "app.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        '"/data/alerts.json"'
        in app
    )

    assert (
        "loadAlerts()"
        in app
    )

    assert (
        "renderElectedAlerts()"
        in app
    )

    assert (
        "Resultados definidos pelo TSE"
        in app
    )

    assert (
        "Eleito(a) segundo o dado publicado pelo TSE"
        in app
    )



def test_elected_by_state_region_is_present():
    html = (
        WEB
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'id="elected-by-state"'
        in html
    )

    assert (
        'id="elected-by-state-grid"'
        in html
    )

    assert (
        "Eleitos por estado"
        in html
    )


def test_elected_by_state_uses_official_alert_feed():
    app = (
        WEB
        / "app.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "electedStateGroups()"
        in app
    )

    assert (
        "renderElectedByState()"
        in app
    )

    assert (
        '"Governador"'
        in app
    )

    assert (
        '"Senado"'
        in app
    )

    assert (
        "Aguardando definição do TSE"
        in app
    )

    assert (
        "candidate.party_acronym"
        in app
    )

    assert (
        "        renderElectedAlerts();\n"
        "        renderElectedByState();"
        in app
    )

    assert (
        "    renderElectedAlerts();\n"
        "    renderElectedByState();"
        in app
    )



def test_second_round_alert_is_distinct_from_elected_state_panel():
    app = (
        WEB
        / "app.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "function alertKind(item)"
        in app
    )

    assert (
        '"second_round"'
        in app
    )

    assert (
        "Classificado(a) para o 2º turno"
        in app
    )

    assert (
        'alertKind(item)\n'
        '                !== "elected"'
        in app
    )
