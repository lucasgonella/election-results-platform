"""Readiness probe tests run offline and never touch production."""
from unittest.mock import patch
from deploy.scripts.verify_round_two_readiness import probe


def test_awaiting_official_data_with_switch():
    def fake(url):
        if url.endswith("/"): return 200, b'<a id="round-first"></a><a id="round-second"></a>'
        if url == "https://example.invalid/data/version.json": return 200, b'{"snapshot_id":"abc"}'
        return 404, b''
    with patch("deploy.scripts.verify_round_two_readiness.get", side_effect=fake):
        result = probe("https://example.invalid/eleicoes")
    assert result["ready_waiting_for_official_data"] is True
    assert result["second_round"] == "awaiting_official_release"


def test_second_round_invalid_never_signals_readiness():
    def fake(url):
        if url.endswith("/"): return 200, b'<a id="round-first"></a><a id="round-second"></a>'
        if url == "https://example.invalid/data/version.json": return 200, b'{"snapshot_id":"abc"}'
        return 200, b'{"snapshot_id":"invalid"}'
    with patch("deploy.scripts.verify_round_two_readiness.get", side_effect=fake):
        result = probe("https://example.invalid/eleicoes")
    assert not result["ready_waiting_for_official_data"]
    assert result["second_round"] == "invalid_second_round_marker"


def test_data_requests_use_domain_root_not_elections_subpath():
    calls = []
    def fake(url):
        calls.append(url)
        if url.endswith("/eleicoes/"): return 200, b'<a id="round-first"></a><a id="round-second"></a>'
        if url == "https://example.invalid/data/version.json": return 200, b'{"snapshot_id":"abc"}'
        return 404, b''
    with patch("deploy.scripts.verify_round_two_readiness.get", side_effect=fake):
        result = probe("https://example.invalid/eleicoes")
    assert result["ready_waiting_for_official_data"]
    assert "https://example.invalid/data/turnos/2/version.json" in calls
    assert all("/eleicoes/data/" not in url for url in calls)
