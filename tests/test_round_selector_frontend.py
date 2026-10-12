"""Round selector must never fall back to first-turn results."""
from pathlib import Path

PORTAL = Path(__file__).resolve().parents[1] / "web/public/eleicoes"


def test_round_switch_is_visible_and_accessible():
    html = (PORTAL / "index.html").read_text(encoding="utf-8")
    assert 'aria-label="Selecionar turno da eleição"' in html
    assert 'id="round-first"' in html
    assert 'id="round-second"' in html
    assert 'id="round-unavailable"' in html
    assert 'href="?turno=2"' in html


def test_second_round_data_isolated_and_fails_closed():
    js = (PORTAL / "app.js").read_text(encoding="utf-8")
    assert '"/data/turnos/2"' in js
    assert 'ROUND_DATA_ROOT + "/version.json"' in js
    assert 'candidateManifest.results.some(row => Number(row.round) !== 2)' in js
    assert 'candidateManifest.environment !== "oficial"' in js
    assert 'classList.add("round-two-unavailable")' in js
    assert 'return;' in js
