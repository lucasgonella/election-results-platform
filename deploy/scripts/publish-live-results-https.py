#!/usr/bin/env python3
"""Send an already-prepared delta to private HTTPS staging (never activate)."""
from __future__ import annotations

import argparse
import base64
import hashlib
import gzip
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

META = {"manifest.json", "version.json", "alerts.json"}


def sign(key: bytes, timestamp: str, nonce: str, body: bytes) -> str:
    return hmac.new(
        key, timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body,
        hashlib.sha256,
    ).hexdigest()


def request(url: str, key: bytes, payload: dict) -> dict:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    req = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Timestamp": timestamp,
            "X-Nonce": nonce,
            "X-Signature": sign(key, timestamp, nonce, body),
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=25) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read(256)!r}") from exc
    except URLError as exc:
        raise RuntimeError(f"HTTPS unavailable: {exc.reason}") from exc
    if result.get("status") not in {"ok", "prepared", "stored", "inspected", "activated", "already_activated"}:
        raise RuntimeError(f"Unexpected server result: {result!r}")
    return result


def stage_paths(stage: Path) -> list[str]:
    if not stage.is_dir():
        raise ValueError("Stage directory not found")
    paths = sorted(p.relative_to(stage).as_posix() for p in stage.rglob("*.json"))
    if not META.issubset(paths) or len(paths) < 4 or len(paths) > 140:
        raise ValueError("Stage must contain metadata and at least one changed result")
    for p in paths:
        parts = p.split("/")
        if not (
            p in META
            or len(parts) == 2
            and len(parts[0]) == 2
            and parts[0].islower()
            and parts[1].endswith(".json")
            and all(c.islower() or c.isdigit() or c == "-" for c in parts[1][:-5])
        ):
            raise ValueError(f"Invalid relative path: {p}")
    manifest = json.loads((stage / "manifest.json").read_text())
    version = json.loads((stage / "version.json").read_text())
    alerts = json.loads((stage / "alerts.json").read_text())
    if manifest.get("result_count") != 137 or len(manifest.get("results", [])) != 137:
        raise ValueError("Expected 137 manifest entries")
    if manifest.get("generated_at") != version.get("generated_at") or alerts.get("generated_at") != version.get("generated_at"):
        raise ValueError("Metadata generation timestamps differ")
    allowed = {item["path"] for item in manifest["results"]}
    if not set(paths).difference(META).issubset(allowed):
        raise ValueError("Unlisted result file in stage")
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("ELECTION_HTTPS_URL", "https://afgnet.com.br/api/election-publish.php"))
    parser.add_argument("--key-file", default="/etc/election-results-platform/secrets/hmac.key")
    parser.add_argument("--stage", required=True, type=Path, help="Pre-existing stage; never runs prepare/commit")
    parser.add_argument("--send", action="store_true", help="Without this flag only validates and reports")
    parser.add_argument("--batch-id", help="Resume an existing 32-character hex batch ID; otherwise create a new batch")
    parser.add_argument("--activate-test", action="store_true", help="Activate ONLY in private Locaweb sandbox after successful upload and inspection")
    args = parser.parse_args()
    if args.activate_test and not args.send:
        parser.error("--activate-test requires --send")
    if not args.url.startswith("https://"):
        parser.error("HTTPS required")
    paths = stage_paths(args.stage)
    print(f"Validated {len(paths)} JSON files; staging-only endpoint")
    if not args.send:
        print("DRY RUN: no requests sent")
        return 0
    key = bytes.fromhex(Path(args.key_file).read_text().strip())
    if len(key) != 32:
        raise ValueError("HMAC key must be 32 bytes")
    batch_id = args.batch_id or secrets.token_hex(16)
    if len(batch_id) != 32 or any(ch not in "0123456789abcdef" for ch in batch_id):
        raise ValueError("Invalid batch ID")
    print(f"BATCH ID: {batch_id}", flush=True)
    if not args.batch_id:
        request(args.url, key, {"action": "begin", "batch_id": batch_id, "paths": paths})
    remote = request(args.url, key, {"action": "inspect", "batch_id": batch_id})
    if remote.get("expected") != len(paths):
        raise RuntimeError("Remote batch differs from current stage")
    present = set(remote.get("present", []))
    for path in paths:
        data = (args.stage / path).read_bytes()
        if len(data) > 6291456:
            raise ValueError(f"Uncompressed file exceeds safe limit: {path}")
        if path in present:
            print(f"already stored {path}")
            continue
        compressed = gzip.compress(data, compresslevel=6) if len(data) > 400000 else data
        encoding = "gzip" if len(data) > 400000 and len(compressed) < len(data) else "identity"
        payload = compressed if encoding == "gzip" else data
        if len(payload) > 700000:
            raise ValueError(f"Compressed file still exceeds upload limit: {path}")
        result = request(args.url, key, {
            "action": "upload",
            "batch_id": batch_id,
            "path": path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "content_b64": base64.b64encode(payload).decode("ascii"),
            "content_encoding": encoding,
        })
        print(f"stored {result['path']}")
    result = request(args.url, key, {"action": "inspect", "batch_id": batch_id})
    if not result.get("complete"):
        raise RuntimeError("Remote staging incomplete")
    print(f"Staging complete ({result['received']} files), batch {batch_id}; NOT PUBLISHED")
    if args.activate_test:
        activated = request(args.url, key, {"action": "activate_test", "batch_id": batch_id})
        if activated.get("mode") != "sandbox" or activated.get("status") not in {"activated", "already_activated"}:
            raise RuntimeError(f"Private activation confirmation invalid: {activated!r}")
        version = json.loads((args.stage / "version.json").read_text())
        if activated.get("status") == "activated" and (activated.get("files") != len(paths) or activated.get("generated_at") != version.get("generated_at")):
            raise RuntimeError(f"Private activation metadata mismatch: {activated!r}")
        print(f"Private activation verified: {activated['status']}; production UNCHANGED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
