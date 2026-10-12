"""Isolated round-two collector guards; no live network access."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from collector.src.second_round_offline import collect_offline, validate_destination


def test_awaiting_config_does_not_create_files(tmp_path):
    destination = tmp_path / "packages" / "batch"
    result = collect_offline(destination, plans=[])
    assert result["status"] == "awaiting_official_round_two_configuration"
    assert result["publication_enabled"] is False
    assert not destination.exists()


def test_invalid_target_inventory_does_not_create_files(tmp_path):
    destination = tmp_path / "packages" / "batch"
    wrong = SimpleNamespace(scope_code="go", office_code=6, round_number=2)
    plan = SimpleNamespace(targets=(wrong,))
    with pytest.raises(ValueError, match="invalid_second_round_target_inventory"):
        collect_offline(destination, plans=[plan])
    assert not destination.exists()


def test_duplicate_scope_office_is_rejected_before_network(tmp_path):
    target = SimpleNamespace(scope_code="go", office_code=3, round_number=2)
    plan = SimpleNamespace(targets=(target, target))
    with pytest.raises(ValueError, match="invalid_second_round_target_inventory"):
        collect_offline(tmp_path / "packages" / "batch", plans=[plan])


def test_existing_or_relative_output_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="second_round_output_must_be_absent_absolute_path"):
        validate_destination(Path("relative"))
    with pytest.raises(ValueError, match="second_round_output_must_be_absent_absolute_path"):
        validate_destination(tmp_path)
