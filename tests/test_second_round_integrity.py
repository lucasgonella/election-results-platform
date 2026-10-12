"""Round-two release integrity guard tests."""
import json

import pytest

from collector.src.second_round_integrity import verify


def fixture(tmp_path):
    root = tmp_path / "turno2"
    root.mkdir()
    (root / "go").mkdir()
    at = "2026-10-25T20:00:00+00:00"
    result = {
        "environment": "oficial", "election": {"round": 2, "code": 42},
        "scope": {"code": "go"}, "office": {"code": 3},
        "snapshot": {"tse_idg": "100", "captured_at": at},
        "candidate_count": 0, "candidates": [],
    }
    row = {"path": "go/governor.json", "round": 2, "scope": "go", "office": 3,
           "election_code": 42, "tse_idg": "100", "captured_at": at, "candidate_count": 0}
    files = {
        "go/governor.json": result,
        "manifest.json": {"environment": "oficial", "generated_at": at,
                          "result_count": 1, "candidate_count": 0, "results": [row]},
        "version.json": {"environment": "oficial", "generated_at": at, "round": 2},
        "alerts.json": {"environment": "oficial", "generated_at": at,
                        "alerts": [], "alert_count": 0},
    }
    for name, value in files.items():
        (root / name).write_text(json.dumps(value))
    return root


def test_second_round_integrity_is_immutable_content_addressed(tmp_path):
    root = fixture(tmp_path)
    first = verify(root)
    assert first["status"] == "verified_offline"
    assert first["publication_enabled"] is False
    assert first["files"] == 4
    assert first["snapshot_id"] == verify(root)["snapshot_id"]


def test_reject_mixed_first_round(tmp_path):
    root = fixture(tmp_path)
    path = root / "go/governor.json"
    data = json.loads(path.read_text())
    data["election"]["round"] = 1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="invalid_second_round_result_identity"):
        verify(root)


def test_reject_unexpected_files(tmp_path):
    root = fixture(tmp_path)
    (root / "extra.json").write_text("{}")
    with pytest.raises(ValueError, match="unexpected_second_round_files"):
        verify(root)


def test_reject_symlink(tmp_path):
    root = fixture(tmp_path)
    (root / "other.json").symlink_to(root / "version.json")
    with pytest.raises(ValueError, match="symlink"):
        verify(root)
