import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "deploy/scripts/election_release_assembler.py"
spec = importlib.util.spec_from_file_location("election_release_assembler", MODULE)
assembler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assembler)


class AssemblerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / "base"
        self.inbox = self.root / "inbox"
        self.base.mkdir()
        self.inbox.mkdir()
        self.new = self.root / "assembled"
        self.names = ["version.json", "manifest.json", "alerts.json"] + [
            f"state/item-{i:03}.json" for i in range(137)]
        for name in self.names:
            p = self.base / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"old")
        self.changed = ["state/item-000.json"]
        p = self.inbox / self.changed[0]
        p.parent.mkdir()
        p.write_bytes(b"new")
        self.plan = {
            "files": {
                name: {
                    "sha256": hashlib.sha256(b"new" if name in self.changed else b"old").hexdigest(),
                    "size": 3,
                }
                for name in self.names
            },
            "changed": self.changed,
        }

    def test_valid_delta_is_assembled_without_editing_baseline(self):
        receipt = assembler.assemble(self.base, self.inbox, self.new, self.plan)
        self.assertEqual(receipt["files"], 140)
        self.assertEqual(receipt["changed"], 1)
        self.assertEqual((self.new / self.changed[0]).read_bytes(), b"new")
        self.assertEqual((self.base / self.changed[0]).read_bytes(), b"old")

    def test_mismatched_payload_rejected_without_output(self):
        (self.inbox / self.changed[0]).write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError, "release_hash_mismatch"):
            assembler.assemble(self.base, self.inbox, self.new, self.plan)
        self.assertFalse(self.new.exists())

    def test_symlink_rejected(self):
        p = self.inbox / self.changed[0]
        p.unlink()
        p.symlink_to(self.base / self.changed[0])
        with self.assertRaisesRegex(ValueError, "symlink_not_allowed"):
            assembler.assemble(self.base, self.inbox, self.new, self.plan)

    def test_missing_inventory_rejected(self):
        del self.plan["files"]["alerts.json"]
        with self.assertRaisesRegex(ValueError, "incomplete_release_inventory"):
            assembler.assemble(self.base, self.inbox, self.new, self.plan)

    def test_existing_destination_preserved(self):
        self.new.mkdir()
        (self.new / "keep").write_text("keep")
        with self.assertRaisesRegex(ValueError, "destination_exists"):
            assembler.assemble(self.base, self.inbox, self.new, self.plan)
        self.assertEqual((self.new / "keep").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
