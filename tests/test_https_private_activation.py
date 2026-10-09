"""Offline end-to-end tests of PHP private-batch activation."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

HELPER = Path(__file__).resolve().parents[1] / "deploy/locaweb/activate-private-batch.php"


class PrivateActivationTests(unittest.TestCase):
    def setUp(self):
        self.context = tempfile.TemporaryDirectory()
        self.addCleanup(self.context.cleanup)
        self.private = Path(self.context.name) / ".election-publisher"
        self.batch = "b" * 32
        self.folder = self.private / "batches" / self.batch
        self.files = self.folder / "files"
        (self.files / "ac").mkdir(parents=True)
        self.generated = datetime.now(timezone.utc).isoformat()
        self.rows = [{"path": f"ac/target-{n}.json"} for n in range(137)]
        self.json_file("manifest.json", {"result_count": 137, "results": self.rows, "generated_at": self.generated})
        self.json_file("version.json", {"generated_at": self.generated})
        self.json_file("alerts.json", {"generated_at": self.generated, "alerts": []})
        self.json_file("ac/target-0.json", {"votes": 15})
        (self.folder / "batch.json").write_text(json.dumps({"paths": [
            "manifest.json", "version.json", "alerts.json", "ac/target-0.json"
        ]}))

    def json_file(self, path, obj):
        (self.files / path).write_text(json.dumps(obj))

    def activate(self):
        script = 'require $argv[1]; try { echo json_encode(activatePrivateBatch($argv[2],$argv[3])); } catch (RuntimeException $e) {fwrite(STDERR,$e->getMessage()); exit(42);}'
        return subprocess.run(["php", "-r", script, str(HELPER),
                               str(self.private), self.batch],
                              capture_output=True, text=True, timeout=10)

    def test_success_and_idempotence(self):
        first = self.activate()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout)["status"], "activated")
        self.assertTrue((self.private / "test-public/ac/target-0.json").exists())
        second = self.activate()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)["status"], "already_activated")
        self.assertFalse((Path(self.context.name) / "public_html").exists())

    def test_missing_delta_is_rejected(self):
        (self.files / "ac/target-0.json").unlink()
        run = self.activate()
        self.assertEqual(run.returncode, 42)
        self.assertIn("incomplete_batch", run.stderr)

    def test_older_publication_is_rejected(self):
        self.assertEqual(self.activate().returncode, 0)
        old = (datetime.fromisoformat(self.generated) - timedelta(hours=1)).isoformat()
        for name in ("manifest.json", "version.json", "alerts.json"):
            obj = json.loads((self.files / name).read_text())
            obj["generated_at"] = old
            self.json_file(name, obj)
        result = self.activate()
        self.assertEqual(result.returncode, 42)
        self.assertIn("stale_version", result.stderr)


if __name__ == "__main__":
    unittest.main()
