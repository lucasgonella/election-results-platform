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


def test_composition_assets_exist():
    assert (
        WEB
        / "composicao.html"
    ).is_file()

    assert (
        WEB
        / "composition.js"
    ).is_file()

    assert (
        WEB
        / "composition.css"
    ).is_file()


def test_main_portal_links_to_composition():
    html = (
        WEB
        / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'href="composicao.html"'
        in html
    )

    assert (
        "Composição 2027"
        in html
    )


def test_composition_uses_official_live_results():
    js = (
        WEB
        / "composition.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        '"/data/manifest.json"'
        in js
    )

    assert (
        '"/data/alerts.json"'
        in js
    )

    assert (
        "Number(\n"
        "                        item.office\n"
        "                    ) === 6"
        in js
    )

    assert (
        "candidateIsOfficiallyElected"
        in js
    )

    assert (
        "candidate.party_acronym"
        in js
    )

    assert (
        "seat_allocations"
        not in js
    )

    assert (
        "Number(\n"
        "                item.office\n"
        "            ) !== 5"
        in js
    )


def test_composition_models_full_chambers():
    js = (
        WEB
        / "composition.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "const CAMERA_TOTAL = 513;"
        in js
    )

    assert (
        "const SENATE_TOTAL = 81;"
        in js
    )

    assert (
        "const SENATE_ELECTED_2026 = 54;"
        in js
    )

    assert (
        "SENATE_HOLDOVER_2027"
        in js
    )


def test_composition_has_current_and_2027_views():
    html = (
        WEB
        / "composicao.html"
    ).read_text(
        encoding="utf-8"
    )

    for element_id in (
        "camera-current-chart",
        "camera-future-chart",
        "senate-current-chart",
        "senate-future-chart",
        "camera-table",
        "senate-table",
    ):
        assert (
            f'id="{element_id}"'
            in html
        )

    assert (
        "Atual"
        in html
    )

    assert (
        "2027"
        in html
    )


def test_senate_second_round_substitutions_are_supported():
    js = (
        WEB
        / "composition.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        '"ALAN RICK"'
        in js
    )

    assert (
        '"OMAR AZIZ"'
        in js
    )

    assert (
        "result.REPUBLICANOS -= 1;"
        in js
    )

    assert (
        "result.PSD -= 1;"
        in js
    )



def test_chamber_composition_counts_elected_candidates_by_party():
    js = (
        WEB
        / "composition.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "candidateIsOfficiallyElected("
        in js
    )

    assert (
        "candidate.elected"
        in js
    )

    assert (
        '"ELEITO POR "'
        in js
    )

    assert (
        "candidate.party_acronym"
        in js
    )

    assert (
        "cameraGroupKey"
        not in js
    )

    assert (
        '"PRD": 3'
        in js
    )


def test_chamber_current_baseline_is_party_level():
    js = (
        WEB
        / "composition.js"
    ).read_text(
        encoding="utf-8"
    )

    expected = (
        '"UNIAO": 52',
        '"PSD": 48',
        '"PP": 46',
        '"REPUBLICANOS": 42',
        '"MDB": 38',
        '"PODE": 27',
        '"PSDB": 15',
        '"CIDADANIA": 4',
        '"PL": 98',
        '"PT": 65',
        '"PCDOB": 11',
        '"PV": 6',
        '"PSOL": 13',
        '"REDE": 3',
        '"PRD": 3',
    )

    for value in expected:
        assert value in js


def test_composition_script_cache_is_bumped():
    html = (
        WEB
        / "composicao.html"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'src="composition.js?v=2"'
        in html
    )
