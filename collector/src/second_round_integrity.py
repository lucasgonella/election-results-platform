"""Fail-closed offline verification of a second-round release candidate.

No FTP access, publication, or directory mutation. The verifier produces the
content-addressed release ID required before building a separate FTP publisher.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .election_release import candidates, parse, stamp, tree


META = {"manifest.json", "version.json", "alerts.json"}
OFFICES = {1: "president", 3: "governor"}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def verify(directory: Path):
    values = tree(directory)
    if not META.issubset(values):
        raise ValueError("missing_second_round_metadata")
    version = parse(values["version.json"])
    manifest = parse(values["manifest.json"])
    alerts = parse(values["alerts.json"])
    timestamp = version.get("generated_at")
    stamp(timestamp)
    for metadata in (version, manifest, alerts):
        if metadata.get("environment") != "oficial" or metadata.get("generated_at") != timestamp:
            raise ValueError("second_round_metadata_mismatch")
    if version.get("round") != 2:
        raise ValueError("invalid_second_round_marker")
    rows = manifest.get("results")
    if not isinstance(rows, list) or not rows or len(rows) > 60:
        raise ValueError("invalid_second_round_manifest")
    if manifest.get("result_count") != len(rows):
        raise ValueError("inconsistent_second_round_inventory")
    names = set()
    count = 0
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("invalid_second_round_entry")
        name = item.get("path")
        office = item.get("office")
        scope = item.get("scope")
        if (type(office) is not int or office not in OFFICES or not isinstance(scope, str)
                or not (scope == "br" or scope == "zz" or (len(scope) == 2 and scope.isalpha() and scope.islower()))
                or name != f"{scope}/{OFFICES[office]}.json" or name in names):
            raise ValueError("invalid_second_round_path")
        names.add(name)
        payload = parse(values[name]) if name in values else None
        if not isinstance(payload, dict):
            raise ValueError("missing_second_round_result")
        if (payload.get("environment") != "oficial"
                or payload.get("election", {}).get("round") != 2
                or payload.get("election", {}).get("code") != item.get("election_code")
                or payload.get("scope", {}).get("code") != scope
                or payload.get("office", {}).get("code") != office
                or payload.get("candidate_count") != item.get("candidate_count")
                or payload.get("snapshot", {}).get("tse_idg") != item.get("tse_idg")
                or payload.get("snapshot", {}).get("captured_at") != item.get("captured_at")):
            raise ValueError("invalid_second_round_result_identity")
        candidates(payload)
        count += payload["candidate_count"]
    if set(values) != names | META:
        raise ValueError("unexpected_second_round_files")
    if count != manifest.get("candidate_count"):
        raise ValueError("second_round_candidate_count_mismatch")
    if (not isinstance(alerts.get("alerts"), list)
            or alerts.get("alert_count") != len(alerts["alerts"])):
        raise ValueError("invalid_second_round_alerts")
    listing = {name: {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
               for name, raw in sorted(values.items())}
    descriptor = {"schema_version": 1, "environment": "oficial", "round": 2,
                  "generated_at": timestamp, "files": listing}
    release_id = hashlib.sha256(canonical(descriptor)).hexdigest()
    return {"status": "verified_offline", "round": 2, "snapshot_id": release_id,
            "files": len(values), "targets": len(rows), "descriptor": descriptor,
            "publication_enabled": False}
