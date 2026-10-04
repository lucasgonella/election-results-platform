from pathlib import Path


ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

PUBLIC = (
    ROOT
    / "web"
    / "public"
)

PORTAL = (
    PUBLIC
    / "eleicoes"
    / "index.html"
)


def test_portal_has_search_metadata():
    html = PORTAL.read_text(
        encoding="utf-8"
    )

    assert (
        "Resultados das Eleições 2026"
        in html
    )

    assert (
        'name="description"'
        in html
    )

    assert (
        'name="robots"'
        in html
    )

    assert (
        'rel="canonical"'
        in html
    )

    assert (
        "https://afgnet.com.br/eleicoes/"
        in html
    )


def test_portal_has_open_graph_metadata():
    html = PORTAL.read_text(
        encoding="utf-8"
    )

    assert (
        'property="og:title"'
        in html
    )

    assert (
        'property="og:description"'
        in html
    )

    assert (
        'property="og:url"'
        in html
    )

    assert (
        'property="og:type"'
        in html
    )


def test_robots_points_to_sitemap():
    robots = (
        PUBLIC
        / "robots.txt"
    ).read_text(
        encoding="utf-8"
    )

    assert "User-agent: *" in robots
    assert "Allow: /" in robots

    assert (
        "Sitemap: "
        "https://afgnet.com.br/sitemap.xml"
        in robots
    )


def test_sitemap_contains_election_portal():
    sitemap = (
        PUBLIC
        / "sitemap.xml"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "<loc>"
        "https://afgnet.com.br/eleicoes/"
        "</loc>"
        in sitemap
    )
