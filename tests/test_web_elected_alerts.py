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
