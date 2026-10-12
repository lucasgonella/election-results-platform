"""No publication or first-turn state changes in round-two discovery."""
from collector.src.second_round_discovery import SETTINGS, evaluate


def test_discovery_empty_config_never_enables_publication(monkeypatch):
    monkeypatch.setattr("collector.src.second_round_discovery.select_supported_elections",
                        lambda config, settings: ())
    result = evaluate({"idg": 1})
    assert result["status"] == "awaiting_official_round_two_configuration"
    assert result["publication_enabled"] is False
    assert SETTINGS.round_number == 2


def test_discovery_rejects_proportional_office(monkeypatch):
    from types import SimpleNamespace
    import pytest
    election = SimpleNamespace(election_code=1,round_number=2,election_type="x",
        name="Test",offices=[SimpleNamespace(code=6,name="Federal deputy")])
    monkeypatch.setattr("collector.src.second_round_discovery.select_supported_elections",
                        lambda config, settings: (election,))
    with pytest.raises(ValueError, match="second_round_unexpected_office"):
        evaluate({})
