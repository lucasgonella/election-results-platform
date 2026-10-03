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


def test_main_portal_polls_lightweight_version_file():
    app = (
        WEB
        / "app.js"
    ).read_text(
        encoding="utf-8"
    )

    assert '"/data/version.json"' in app
    assert '"/data/manifest.json"' in app
    assert "const REFRESH_MS = 30000;" in app
    assert "publicationToken" in app
    assert "nextVersion" in app
    assert "=== publishedVersion" in app


def test_manifest_is_only_reloaded_after_version_change():
    app = (
        WEB
        / "app.js"
    ).read_text(
        encoding="utf-8"
    )

    version_check = app.index(
        "nextVersion"
    )

    equality_check = app.index(
        "=== publishedVersion",
        version_check,
    )

    manifest_reload = app.index(
        "await loadManifest();",
        equality_check,
    )

    assert (
        version_check
        < equality_check
        < manifest_reload
    )
