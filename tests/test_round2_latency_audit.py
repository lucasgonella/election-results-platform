"""Offline tests for read-only second-round latency audit."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.round2_latency_audit import report, seconds_between


class LatencyAuditTests(unittest.TestCase):
    def test_elapsed(self):
        self.assertEqual(seconds_between("2026-10-17T13:02:00-03:00",
                                         "2026-10-17T13:00:00-03:00"), 120)
        self.assertIsNone(seconds_between(None, "2026-10-17T13:00:00-03:00"))

    def test_same_snapshot_and_public_marker(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "health.json").write_text(json.dumps({
                "status": "unchanged",
                "observed_snapshot_id": "abc",
                "observed_snapshot_since": "2026-10-17T12:00:00-03:00",
                "last_source_success_at": "2026-10-17T12:01:00-03:00",
                "metrics": {"collection": {"duration_seconds": 4.2}}
            }))
            (root / "checkpoint.json").write_text(json.dumps({
                "snapshot_id": "abc",
                "verified_at": "2026-10-17T12:01:30-03:00"
            }))
            result = report(root, marker={"http_status": 200, "payload": {"snapshot_id": "abc"}},
                            current_time="2026-10-17T12:02:00-03:00")
            self.assertTrue(result["checkpoint_equals_public"])
            self.assertEqual(result["observed_to_verified_seconds"], 90)
            self.assertEqual(result["source_last_success_age_seconds"], 60)
            self.assertEqual(result["latest_phase_durations_seconds"]["collection"], 4.2)

    def test_different_snapshot_never_claims_publication_delay(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "health.json").write_text('{"observed_snapshot_id":"new"}')
            (root / "checkpoint.json").write_text('{"snapshot_id":"old"}')
            result = report(root, marker={"http_status": 200, "payload": {"snapshot_id": "old"}})
            self.assertFalse(result["observed_equals_checkpoint"])
            self.assertIsNone(result["observed_to_verified_seconds"])


if __name__ == "__main__":
    unittest.main()
