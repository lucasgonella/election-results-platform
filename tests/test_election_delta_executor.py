import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "deploy/scripts"
sys.path.insert(0, str(SCRIPTS))
from election_delta_executor import authorize, canonical, execute


class DeltaAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.base = "a" * 64
        self.release = "b" * 64
        self.secret = b"s" * 48
        self.payload = {
            "schema_version": 1,
            "base_snapshot_id": self.base,
            "release_id": self.release,
            "plan": {"files": {}, "changed": []},
        }
        self.envelope = dict(self.payload)
        self.envelope["signature"] = hmac.new(
            self.secret, canonical(self.payload), hashlib.sha256
        ).hexdigest()

    def test_signed_envelope_matches_baseline(self):
        plan, sid = authorize(self.envelope, self.secret, self.base)
        self.assertEqual(plan, self.payload["plan"])
        self.assertEqual(sid, self.release)

    def test_tampering_fails(self):
        self.envelope["plan"]["changed"].append("other.json")
        with self.assertRaisesRegex(ValueError, "unauthenticated_delta"):
            authorize(self.envelope, self.secret, self.base)

    def test_mismatched_baseline_fails(self):
        with self.assertRaisesRegex(ValueError, "wrong_release_identity"):
            authorize(self.envelope, self.secret, "c" * 64)

    def test_unknown_fields_fail(self):
        self.envelope["command"] = "rm -rf /"
        with self.assertRaisesRegex(ValueError, "invalid_envelope"):
            authorize(self.envelope, self.secret, self.base)

    def test_secret_file_permissions_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = root / "secret"
            secret.write_bytes(self.secret)
            secret.chmod(0o644)
            envelope = root / "envelope.json"
            envelope.write_text(json.dumps(self.envelope))
            with self.assertRaisesRegex(ValueError, "insecure_secret_permissions"):
                execute(base=root, inbox=root, output=root / self.release,
                        envelope_path=envelope, secret_path=secret,
                        expected_base=self.base)


if __name__ == "__main__":
    unittest.main()
