import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "deploy/scripts"
sys.path.insert(0, str(SCRIPTS))
from election_delta_reconcile import inspect_claim


class RecoveryClassificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ledger = self.root / "ledger"
        self.ledger.mkdir()
        self.release = "b" * 64
        self.base = "a" * 64
        self.output = self.root / self.release

    def check(self):
        return inspect_claim(ledger=self.ledger, output=self.output,
                             release_id=self.release, expected_base=self.base)

    def test_unclaimed(self):
        self.assertEqual(self.check()["state"], "unclaimed")

    def test_interrupted(self):
        (self.ledger / self.release).mkdir()
        self.assertEqual(self.check()["state"],
                         "interrupted_requires_manual_reconciliation")

    def test_receipt_without_output(self):
        import json
        claim = self.ledger / self.release
        claim.mkdir()
        (claim / "receipt.json").write_text(json.dumps({
            "status": "assembled", "release_id": self.release,
            "base_snapshot_id": self.base
        }))
        self.assertEqual(self.check()["state"],
                         "receipt_without_output_requires_review")
        self.output.mkdir()
        self.assertEqual(self.check()["state"],
                         "assembled_requires_external_verification")

    def test_wrong_baseline_receipt_rejected(self):
        (self.ledger / self.release).mkdir()
        (self.ledger / self.release / "receipt.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "invalid_delivery_receipt"):
            self.check()


if __name__ == "__main__":
    unittest.main()
