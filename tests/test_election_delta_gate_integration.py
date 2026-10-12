"""End-to-end offline gate tests using real synthetic electoral schema."""
import hashlib
import hmac
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/scripts"))
from election_delta_executor import canonical as signed_canonical
from election_delta_transaction_gate import preflight
from collector.src.election_release import canonical, digest, targets, tree
from collector.src.static_election_publish import descriptor
from static_election_fixtures import bundle
import pytest


def make_envelope(values, base, key):
    desc = descriptor(values)
    sid = digest(canonical(desc))
    plan = {"files": desc["files"], "changed": ["version.json"]}
    env = {"schema_version": 1, "base_snapshot_id": base,
           "release_id": sid, "plan": plan}
    env["signature"] = hmac.new(key, signed_canonical(env), hashlib.sha256).hexdigest()
    return sid, env


def test_valid_electoral_release_passes_read_only(tmp_path):
    initial = tmp_path / "initial"
    bundle(initial, 1)
    updated_temp = tmp_path / "updated"
    bundle(updated_temp, 2)
    before, after = tree(initial), tree(updated_temp)
    old_id = "a" * 64
    key = b"k" * 48
    sid, envelope = make_envelope(after, old_id, key)
    output = tmp_path / sid
    updated_temp.rename(output)
    approvals = {name: digest(after[name]) for name in targets() if name.startswith("am/")}
    receipt = preflight(envelope=envelope, secret=key,
                        current={"snapshot_id": old_id}, pending={"status": "complete", "snapshot_id": old_id},
                        assembled=output, expected_base=old_id,
                        baseline_values=before, reviews=approvals)
    assert receipt["activation_permitted"] is False
    assert receipt["snapshot_id"] == sid
    assert receipt["files"] == 140


def test_unapproved_amazonas_change_is_blocked(tmp_path):
    initial = tmp_path / "initial"
    bundle(initial, 1)
    candidate = tmp_path / "candidate"
    bundle(candidate, 2)
    before, after = tree(initial), tree(candidate)
    old_id = "a" * 64
    key = b"k" * 48
    sid, envelope = make_envelope(after, old_id, key)
    output = tmp_path / sid
    candidate.rename(output)
    with pytest.raises(ValueError, match="candidate_change_requires_specific_review"):
        preflight(envelope=envelope, secret=key,
                  current={"snapshot_id": old_id}, pending={"status": "complete", "snapshot_id": old_id},
                  assembled=output, expected_base=old_id,
                  baseline_values=before)
