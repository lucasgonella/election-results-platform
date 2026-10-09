"""CLI regression tests: HTTPS sandbox activation must remain opt-in."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/scripts/publish-live-results-https.py"
spec = importlib.util.spec_from_file_location("https_publisher", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestSandboxCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.stage = root / "stage"
        (self.stage / "ac").mkdir(parents=True)
        stamp = "2026-10-09T12:49:55+00:00"
        self.paths = ["alerts.json", "manifest.json", "version.json", "ac/result-0.json"]
        for path, payload in {
            "alerts.json": {"generated_at": stamp},
            "manifest.json": {
                "generated_at": stamp,
                "result_count": 137,
                "results": [{"path": "ac/result-0.json"}] * 137,
            },
            "version.json": {"generated_at": stamp},
            "ac/result-0.json": {"votes": 1},
        }.items():
            (self.stage / path).write_text(json.dumps(payload))
        self.key = root / "hmac.key"
        self.key.write_text("aa" * 32)

    def run_cli(self, *flags, activation_status="activated"):
        calls = []

        def fake_request(url, key, payload):
            calls.append(payload["action"])
            action = payload["action"]
            if action == "inspect":
                return {"status": "inspected", "complete": True, "received": 4, "expected": 4, "present": []}
            if action == "activate_test":
                return {
                    "status": activation_status, "mode": "sandbox",
                    "files": 4, "generated_at": "2026-10-09T12:49:55+00:00",
                }
            if action == "upload":
                return {"status": "stored", "path": payload["path"]}
            return {"status": "prepared"}

        with patch.object(module, "request", side_effect=fake_request), patch.object(
            sys, "argv",
            ["publisher", "--stage", str(self.stage), "--key-file", str(self.key), *flags],
        ):
            result = module.main()
        return result, calls

    def test_no_publish_without_send(self):
        result, calls = self.run_cli()
        self.assertEqual(result, 0)
        self.assertEqual(calls, [])

    def test_sends_without_activation_by_default(self):
        result, calls = self.run_cli("--send")
        self.assertEqual(result, 0)
        self.assertNotIn("activate_test", calls)

    def test_activation_is_explicit_and_last(self):
        result, calls = self.run_cli("--send", "--activate-test")
        self.assertEqual(result, 0)
        self.assertEqual(calls[-2:], ["inspect", "activate_test"])

    def test_activation_requires_send(self):
        with self.assertRaises(SystemExit):
            self.run_cli("--activate-test")

    def test_invalid_activation_confirmation_fails(self):
        with self.assertRaises(RuntimeError):
            self.run_cli("--send", "--activate-test", activation_status="inspected")


if __name__ == "__main__":
    unittest.main()
