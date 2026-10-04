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


def test_footer_contains_author_credit_and_repository_link():
    html = (
        WEB
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    assert "Lucas Gonella" in html

    assert (
        "https://www.linkedin.com/in/"
        "lucasgonella/"
        in html
    )

    assert (
        "https://github.com/lucasgonella/"
        "election-results-platform"
        in html
    )

    assert (
        'class="footer-credits"'
        in html
    )


def test_footer_styles_are_cache_busted():
    html = (
        WEB
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'href="styles.css?v=6"'
        in html
    )


def test_google_analytics_tag_is_present():
    html = (
        WEB
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "https://www.googletagmanager.com/"
        "gtag/js?id=G-X6KE82RM68"
        in html
    )

    assert (
        'gtag(\n            "config",\n'
        '            "G-X6KE82RM68"'
        in html
    )