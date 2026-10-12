"""Restricted offline delta executor; NEVER activates the public marker.

Envelope: {schema_version, base_snapshot_id, release_id, plan, signature}.
signature = hex(HMAC-SHA256(secret, canonical JSON of the first four fields)).
A trusted scheduler supplies absolute paths and a private secret file.
"""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re

from election_release_assembler import assemble, regular_file

HEX64 = re.compile(r"^[a-f0-9]{64}$")


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def authorize(envelope, secret, expected_base):
    if not isinstance(envelope, dict) or set(envelope) != {
        "schema_version", "base_snapshot_id", "release_id", "plan", "signature"
    }:
        raise ValueError("invalid_envelope")
    base = envelope["base_snapshot_id"]
    release = envelope["release_id"]
    if (envelope["schema_version"] != 1 or not isinstance(base, str)
            or not isinstance(release, str) or not HEX64.fullmatch(base)
            or not HEX64.fullmatch(release) or base != expected_base or base == release):
        raise ValueError("wrong_release_identity")
    supplied = envelope["signature"]
    if not isinstance(supplied, str) or not HEX64.fullmatch(supplied):
        raise ValueError("invalid_signature")
    payload = {k: v for k, v in envelope.items() if k != "signature"}
    expected = hmac.new(secret, canonical(payload), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise ValueError("unauthenticated_delta")
    return envelope["plan"], release


def execute(*, base, inbox, output, envelope_path, secret_path, expected_base, ledger):
    secret_path = Path(secret_path)
    if secret_path.is_symlink():
        raise ValueError("unsafe_secret_path")
    st = secret_path.stat()
    if st.st_mode & 0o077:
        raise ValueError("insecure_secret_permissions")
    secret = regular_file(secret_path)
    if len(secret) < 32:
        raise ValueError("weak_secret")
    envelope = json.loads(regular_file(Path(envelope_path)))
    plan, release = authorize(envelope, secret, expected_base)
    output = Path(output)
    if output.name != release:
        raise ValueError("destination_release_mismatch")
    ledger = Path(ledger)
    if not ledger.is_dir() or ledger.is_symlink():
        raise ValueError("invalid_delivery_ledger")
    # Atomic claim: a crash intentionally leaves the claim in place, requiring
    # operator reconciliation rather than replaying a possibly promoted release.
    claim = ledger / release
    try:
        claim.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ValueError("delivery_already_claimed") from exc
    result = assemble(base, inbox, output, plan)
    # A missing receipt after crash does not permit implicit retry.
    receipt = claim / "receipt.json"
    with receipt.open("x", encoding="utf-8") as handle:
        json.dump({"status": "assembled", "release_id": release,
                   "base_snapshot_id": expected_base}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    return result | {"release_id": release, "base_snapshot_id": expected_base}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--inbox", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--envelope", type=Path, required=True)
    parser.add_argument("--secret-file", type=Path, required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(execute(base=args.base, inbox=args.inbox,
                            output=args.output, envelope_path=args.envelope,
                            secret_path=args.secret_file,
                            expected_base=args.expected_base, ledger=args.ledger)))


if __name__ == "__main__":
    main()
