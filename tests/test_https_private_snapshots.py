"""Integration test: immutable private snapshots, delta carry-forward and rollback."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / "deploy/locaweb"
BUILD = ROOT / "build-private-snapshot.php"
PROMOTE = ROOT / "promote-private-snapshot.php"


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.base = Path(self.t.name) / ".election-publisher"
        self.base.mkdir()
        self.paths = [f"ac/target-{n}.json" for n in range(137)]
        self.initial = "a" * 32
        self.delta = "b" * 32
        self.make_batch(self.initial, "2026-10-09T10:00:00+00:00", self.paths)
        self.make_batch(self.delta, "2026-10-09T11:00:00+00:00", [self.paths[0]])

    def make_batch(self, batch_id, stamp, changed):
        directory = self.base / "batches" / batch_id
        (directory / "files/ac").mkdir(parents=True)
        all_paths = ["version.json", "manifest.json", "alerts.json"] + changed
        (directory / "batch.json").write_text(json.dumps({"paths": all_paths}))
        manifest = {"generated_at": stamp, "result_count": 137, "results": [{"path": p} for p in self.paths]}
        files = {"version.json": {"generated_at": stamp}, "manifest.json": manifest, "alerts.json": {"generated_at": stamp}}
        files.update({p: {"path": p, "votes": 2 if batch_id == self.delta else 1} for p in changed})
        for p, data in files.items():
            dest = directory / "files" / p
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(data))

    def call(self, helper, function, *args):
        php = f'require $argv[1]; try {{ echo json_encode({function}($argv[2], $argv[3]{", true" if args else ""})); }} catch (RuntimeException $e) {{ fwrite(STDERR, $e->getMessage()); exit(42); }}'
        return subprocess.run(["php", "-r", php, str(helper), str(self.base), args[0] if args else self.initial],
                              text=True, capture_output=True, timeout=20)

    def test_full_then_incremental_then_rollback(self):
        first = self.call(BUILD, "buildPrivateSnapshot")
        self.assertEqual(first.returncode, 0, first.stderr)
        first_id = json.loads(first.stdout)["snapshot_id"]
        published = self.call(PROMOTE, "promotePrivateSnapshot", first_id)
        self.assertEqual(published.returncode, 0, published.stderr)
        second = self.call(BUILD, "buildPrivateSnapshot", self.delta)
        self.assertEqual(second.returncode, 0, second.stderr)
        second_id = json.loads(second.stdout)["snapshot_id"]
        root = self.base / "snapshot-sandbox/releases"
        self.assertEqual(len(list((root / second_id / "ac").glob("*.json"))), 137)
        self.assertEqual(json.loads((root / second_id / self.paths[0]).read_text())["votes"], 2)
        self.assertEqual(json.loads((root / second_id / self.paths[1]).read_text())["votes"], 1)
        new = self.call(PROMOTE, "promotePrivateSnapshot", second_id)
        self.assertEqual(new.returncode, 0, new.stderr)
        old = self.call(PROMOTE, "promotePrivateSnapshot", first_id)
        self.assertEqual(old.returncode, 42)
        back = self.call(PROMOTE, "promotePrivateSnapshot", first_id, True)
        self.assertEqual(back.returncode, 0, back.stderr)
        self.assertEqual((self.base / "snapshot-sandbox/current").read_text().strip(), first_id)
        self.assertFalse((Path(self.t.name) / "public_html").exists())

    def test_delta_without_base_is_rejected(self):
        attempted = self.call(BUILD, "buildPrivateSnapshot", self.delta)
        self.assertEqual(attempted.returncode, 42)
        self.assertIn("missing_baseline", attempted.stderr)


if __name__ == "__main__":
    unittest.main()
