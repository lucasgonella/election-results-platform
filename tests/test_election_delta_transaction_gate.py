import hashlib
import hmac
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/scripts"))
from election_delta_executor import canonical
from election_delta_transaction_gate import preflight


class TransactionGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = "a" * 64
        self.release = "b" * 64
        self.secret = b"s" * 48
        self.output = self.root / self.release
        self.output.mkdir()
        names = ["version.json", "manifest.json", "alerts.json"] + [
            f"state/item-{n:03d}.json" for n in range(137)
        ]
        for name in names:
            path = self.output / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"abc")
        self.plan = {"files": {name: {
            "sha256": hashlib.sha256(b"abc").hexdigest(), "size": 3,
        } for name in names}, "changed": ["version.json"]}
        self.envelope = {"schema_version": 1, "base_snapshot_id": self.base,
                         "release_id": self.release, "plan": self.plan}
        self.envelope["signature"] = hmac.new(
            self.secret, canonical(self.envelope), hashlib.sha256
        ).hexdigest()

    def run_gate(self, **kwargs):
        args = {"envelope": self.envelope, "secret": self.secret,
                "current": {"snapshot_id": self.base},
                "pending": {"status": "complete"},
                "assembled": self.output, "expected_base": self.base}
        args.update(kwargs)
        return preflight(**args)

    def test_valid_read_only_gate(self):
        result = self.run_gate()
        self.assertEqual(result["state"], "verified_for_transaction_review")
        self.assertFalse(result["activation_permitted"])
        self.assertEqual(result["files"], 140)

    def test_prepared_prior_transaction_rejected(self):
        with self.assertRaisesRegex(ValueError, "incomplete_prior_transaction"):
            self.run_gate(pending={"status": "prepared"})

    def test_unexpected_baseline_rejected(self):
        with self.assertRaisesRegex(ValueError, "current_snapshot_mismatch"):
            self.run_gate(current={"snapshot_id": "c" * 64})

    def test_corrupt_assembled_file_rejected(self):
        (self.output / "version.json").write_bytes(b"BAD")
        with self.assertRaisesRegex(ValueError, "assembled_hash_mismatch"):
            self.run_gate()

    def test_extra_file_rejected(self):
        (self.output / "extra").write_text("no")
        with self.assertRaisesRegex(ValueError, "unexpected_assembled_inventory"):
            self.run_gate()


if __name__ == "__main__":
    unittest.main()
