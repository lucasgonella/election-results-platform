"""Exercise the CLI activation sandbox without contacting production."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/locaweb/activate-sandbox.php"


class SandboxActivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.private = self.home / ".election-publisher"
        self.batch_id = "a" * 32
        self.stage = self.private / "batches" / self.batch_id / "files"
        (self.stage / "ac").mkdir(parents=True)
        self.generated = datetime.now(timezone.utc).isoformat()
        self.results = [{"path": f"ac/result-{i}.json"} for i in range(137)]
        self.write("manifest.json", {"result_count": 137, "results": self.results, "generated_at": self.generated})
        self.write("version.json", {"generated_at": self.generated})
        self.write("alerts.json", {"generated_at": self.generated, "alerts": []})
        self.write("ac/result-0.json", {"votes": 123})
        (self.stage.parent / "batch.json").write_text(json.dumps({
            "paths": ["manifest.json", "version.json", "alerts.json", "ac/result-0.json"]
        }))

    def write(self, path, obj):
        (self.stage / path).write_text(json.dumps(obj))

    def invoke(self):
        return subprocess.run(
            ["php", str(SCRIPT), self.batch_id],
            env={**os.environ, "HOME": str(self.home)},
            capture_output=True, text=True
        )

    def test_publish_and_replay_are_sandbox_only(self):
        first = self.invoke()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout)["status"], "activated")
        self.assertTrue((self.private / "test-public/ac/result-0.json").is_file())
        second = self.invoke()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)["status"], "already_activated")
        self.assertFalse((self.home / "public_html").exists())

    def test_missing_file_rejected(self):
        (self.stage / "ac/result-0.json").unlink()
        r = self.invoke()
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.private / "test-public/version.json").exists())

    def test_old_generation_cannot_overwrite_new(self):
        self.assertEqual(self.invoke().returncode, 0)
        old = (datetime.fromisoformat(self.generated) - timedelta(hours=1)).isoformat()
        for p in ("manifest.json", "version.json", "alerts.json"):
            obj = json.loads((self.stage / p).read_text())
            obj["generated_at"] = old
            self.write(p, obj)
        r = self.invoke()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("stale version", r.stderr)


if __name__ == "__main__":
    unittest.main()
