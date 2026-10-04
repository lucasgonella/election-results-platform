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


def test_favorites_assets_exist():
    assert (
        WEB
        / "favorites.js"
    ).is_file()


def test_favorites_are_persistent():
    text = (
        WEB
        / "favorites.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "localStorage"
        in text
    )

    assert (
        "tse_candidate_seq"
        in text
    )

    assert (
        "election-results:favorites:v1"
        in text
    )


def test_favorites_panel_is_loaded():
    html = (
        WEB
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'id="favorites-open"'
        in html
    )

    assert (
        'id="favorites-list"'
        in html
    )

    assert (
        '<script src="favorites.js?v=7"></script>'
        in html
    )


def test_candidate_cards_support_favorites():
    app = (
        WEB
        / "app.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "favorite-toggle"
        in app
    )

    assert (
        "window.Favorites.toggle"
        in app
    )

    assert (
        "\\u2605"
        in app
    )

    assert (
        "\\u2606"
        in app
    )


def test_favorites_markup_uses_safe_icons_and_cache_busting():
    html = (
        WEB
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    assert "&#9734; Favoritos" in html
    assert "&times;" in html
    assert 'href="styles.css?v=10"' in html
    assert '<script src="app.js?v=13"></script>' in html
    assert "? Favoritos" not in html


def test_favorites_refresh_current_published_data():
    js = (
        WEB
        / "favorites.js"
    ).read_text(
        encoding="utf-8"
    )

    assert '"/data/version.json"' in js
    assert '"/data/manifest.json"' in js
    assert "const REFRESH_MS = 5000;" in js
    assert "checkForPublication" in js
    assert "resultCache" in js
    assert 'cache: "no-store"' in js
    assert "item.tse_idg" in js
    assert "item.captured_at" in js
    assert "result.snapshot.tse_idg" in js
    assert "result.snapshot.captured_at" in js
    assert "Sincronizado com a publicação atual" in js


def test_favorites_show_context_and_update_metadata():
    js = (
        WEB
        / "favorites.js"
    ).read_text(
        encoding="utf-8"
    )

    assert '"Localidade"' in js
    assert '"Cargo"' in js
    assert '"Apuração"' in js
    assert '"Atualizado"' in js

    html = (
        WEB
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    assert 'id="favorites-refresh-status"' in html
    assert "a cada 5 segundos" in html
    assert "Verifica novas publicações" in html


def test_district_deputy_is_supported_in_web_order():
    app = (
        WEB
        / "app.js"
    ).read_text(
        encoding="utf-8"
    )

    favorites = (
        WEB
        / "favorites.js"
    ).read_text(
        encoding="utf-8"
    )

    assert "    8\n];" in app
    assert "        8\n    ];" in favorites