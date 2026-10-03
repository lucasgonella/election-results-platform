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
        '<script src="favorites.js?v=3"></script>'
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
    assert 'href="styles.css?v=4"' in html
    assert '<script src="app.js?v=3"></script>' in html
    assert "? Favoritos" not in html