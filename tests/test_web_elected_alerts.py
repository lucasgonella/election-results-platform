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


def test_redundant_top_alert_region_is_removed():
    html = (
        WEB
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    app = (
        WEB
        / "app.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'id="elected-alerts"'
        not in html
    )

    assert (
        "renderElectedAlerts()"
        not in app
    )

    assert (
        "resultAlertCard("
        not in app
    )


def test_official_alert_feed_still_drives_state_results():
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
        "electedStateGroups()"
        in app
    )

    assert (
        "renderElectedByState()"
        in app
    )


def test_governor_and_senate_use_separate_grids():
    html = (
        WEB
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    app = (
        WEB
        / "app.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "Resultados definidos por estado"
        in html
    )

    assert (
        "Governadores"
        in html
    )

    assert (
        "Senadores"
        in html
    )

    assert (
        'id="governor-results-grid"'
        in html
    )

    assert (
        'id="senate-results-grid"'
        in html
    )

    assert (
        'field: "governors"'
        in app
    )

    assert (
        'field: "senators"'
        in app
    )


def test_second_round_is_shown_in_governor_grid():
    app = (
        WEB
        / "app.js"
    ).read_text(
        encoding="utf-8"
    )

    grouping = app[
        app.index(
            "function electedStateGroups()"
        ):
        app.index(
            "function electedCandidateList("
        )
    ]

    assert (
        '"second_round"'
        in grouping
    )

    assert (
        "definedGovernor"
        in grouping
    )

    assert (
        'definedSenator =\n'
        '            office === 5\n'
        '            && kind === "elected"'
        in grouping
    )

    assert (
        "2º turno definido pelo TSE"
        in app
    )

    assert (
        "Eleição segue para o 2º turno"
        in app
    )


def test_mathematically_defined_governor_can_appear_without_candidate_name():
    app = (
        WEB
        / "app.js"
    ).read_text(
        encoding="utf-8"
    )

    grouping = app[
        app.index(
            "function electedStateGroups()"
        ):
        app.index(
            "function electedCandidateList("
        )
    ]

    assert (
        "|| !item.candidate_name"
        not in grouping
    )

    assert (
        '"mathematically_elected"'
        in app
    )

    assert (
        "Eleição matematicamente definida (Eleito)"
        in app
    )

    assert (
        "Nome ainda não individualizado pelo TSE"
        in app
    )


def test_state_results_render_after_alert_reload():
    app = (
        WEB
        / "app.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "        renderElectedByState();"
        in app
    )

    assert (
        "    renderElectedByState();"
        in app
    )
