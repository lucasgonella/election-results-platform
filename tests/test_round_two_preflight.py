"""Round-two readiness cannot mutate or alias the first-round state."""
from pathlib import Path

import pytest

from collector.src.runtime import RuntimeSettings
from collector.src.static_election_runner import second_round_preflight


def settings(round_number=2):
    return RuntimeSettings(base_url="https://resultados.tse.jus.br",
                           environment="oficial", cycle="ele2026",
                           round_number=round_number)


def test_read_only_second_round_preflight(tmp_path, monkeypatch):
    first = tmp_path / "round-1"
    second = tmp_path / "round-2"
    first.mkdir()
    second.mkdir()
    monkeypatch.setenv("ELECTION_STATIC_STATE_DIR", str(first))
    result = second_round_preflight(settings(), {"snapshot_id": "a" * 64}, state_dir=second)
    assert result["publication_enabled"] is False
    assert result["first_round_snapshot_id"] == "a" * 64
    assert result["round"] == 2


def test_reject_first_round_tree_and_wrong_turn(tmp_path, monkeypatch):
    first = tmp_path / "round-1"
    first.mkdir()
    monkeypatch.setenv("ELECTION_STATIC_STATE_DIR", str(first))
    with pytest.raises(ValueError, match="round_state_overlap"):
        second_round_preflight(settings(), {"snapshot_id": "a" * 64}, state_dir=first)
    with pytest.raises(ValueError, match="invalid_second_round_runtime"):
        second_round_preflight(settings(1), {"snapshot_id": "a" * 64}, state_dir=tmp_path / "round-2")


def test_reject_symlink_round_two_state(tmp_path, monkeypatch):
    first = tmp_path / "round-1"
    first.mkdir()
    second = tmp_path / "round-2"
    second.symlink_to(first)
    monkeypatch.setenv("ELECTION_STATIC_STATE_DIR", str(first))
    with pytest.raises(ValueError, match="unsafe_round_two_state"):
        second_round_preflight(settings(), {"snapshot_id": "a" * 64}, state_dir=second)
