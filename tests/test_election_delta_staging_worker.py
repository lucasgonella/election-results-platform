import hashlib
import hmac
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/scripts"))
from election_delta_executor import canonical
from election_delta_staging_worker import inspect_delivery


def test_worker_uses_trusted_checkpoint_not_ftp_supplied_path(tmp_path):
    base, release = "a" * 64, "b" * 64
    for folder in ("inbox", "assembled", "ledger", "baselines"):
        (tmp_path / folder).mkdir()
    (tmp_path / "baselines" / base).mkdir()
    inbox = tmp_path / "inbox" / release
    inbox.mkdir()
    secret = tmp_path / "secret"
    secret.write_bytes(b"s" * 48)
    secret.chmod(0o600)
    current = tmp_path / "current.json"
    current.write_text(json.dumps({"snapshot_id": base}))
    envelope = {"schema_version": 1, "base_snapshot_id": base,
                "release_id": release, "plan": {"files": {}, "changed": []}}
    envelope["signature"] = hmac.new(secret.read_bytes(), canonical(envelope),
                                       hashlib.sha256).hexdigest()
    (inbox / "envelope.json").write_text(json.dumps(envelope))
    info = inspect_delivery(tmp_path, secret, current, release)
    assert info["baseline"] == tmp_path / "baselines" / base
    assert info["output"] == tmp_path / "assembled" / release
    assert "public_html" not in str(info["output"])
    current.write_text(json.dumps({"snapshot_id": "c" * 64}))
    with pytest.raises(ValueError, match="wrong_release_identity"):
        inspect_delivery(tmp_path, secret, current, release)
    current.write_text(json.dumps({"snapshot_id": base}))
    (tmp_path / "baselines" / base).rmdir()
    (tmp_path / "baselines" / base).symlink_to(tmp_path / "assembled")
    with pytest.raises(ValueError, match="trusted_baseline_missing"):
        inspect_delivery(tmp_path, secret, current, release)
