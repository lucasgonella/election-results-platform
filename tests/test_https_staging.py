"""Offline tests for the staging-only HTTPS uploader."""
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/scripts/publish-live-results-https.py"
spec = importlib.util.spec_from_file_location("https_publisher", SCRIPT)
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class HttpsStagingTests(unittest.TestCase):
    def test_signature_matches_protocol(self):
        key = bytes(range(32))
        body = b'{"action":"health"}'
        msg = b"1760000000\n" + b"a" * 32 + b"\n" + body
        self.assertEqual(publisher.sign(key, "1760000000", "a" * 32, body),
                         hmac.new(key, msg, hashlib.sha256).hexdigest())

    def test_valid_synthetic_delta(self):
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp)
            generated = "2026-10-09T12:00:00+00:00"
            rows = [{"path": f"ac/result-{i}.json"} for i in range(137)]
            (stage / "ac").mkdir()
            (stage / "ac/result-0.json").write_text('{"votes":1}')
            (stage / "manifest.json").write_text(json.dumps({
                "result_count": 137, "results": rows, "generated_at": generated
            }))
            (stage / "version.json").write_text(json.dumps({"generated_at": generated}))
            (stage / "alerts.json").write_text(json.dumps({"generated_at": generated}))
            self.assertEqual(len(publisher.stage_paths(stage)), 4)
            (stage / "ac/unknown.json").write_text("{}")
            with self.assertRaises(ValueError):
                publisher.stage_paths(stage)


if __name__ == "__main__":
    unittest.main()
