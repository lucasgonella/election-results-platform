"""Conservative on-host bridge for a signed FTP delta inbox.

This worker only assembles private outputs and writes receipts. It never modifies
public releases, activation markers, production locks or watermarks.
"""
import argparse
import json
from pathlib import Path
import sys

from election_delta_executor import authorize, execute
from election_release_assembler import regular_file


def inspect_delivery(root, secret_path, current_path, release_id):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("invalid_staging_root")
    inbox_root = root / "inbox"
    output_root = root / "assembled"
    ledger = root / "ledger"
    for directory in (inbox_root, output_root, ledger):
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("invalid_staging_layout")
    if (not isinstance(release_id, str) or len(release_id) != 64
            or any(c not in "0123456789abcdef" for c in release_id)):
        raise ValueError("invalid_release_id")
    source = inbox_root / release_id
    if source.is_symlink() or not source.is_dir():
        raise ValueError("missing_delivery_inbox")
    current = json.loads(regular_file(Path(current_path)))
    base = current.get("snapshot_id")
    if (not isinstance(base, str) or len(base) != 64
            or any(c not in "0123456789abcdef" for c in base)):
        raise ValueError("invalid_trusted_current")
    envelope_path = source / "envelope.json"
    envelope = json.loads(regular_file(envelope_path))
    secret = regular_file(Path(secret_path))
    plan, expected = authorize(envelope, secret, base)
    if expected != release_id:
        raise ValueError("delivery_release_mismatch")
    # The trusted baseline is selected exclusively by the current checkpoint,
    # never by an FTP-supplied path.
    baseline = root / "baselines" / base
    if baseline.is_symlink() or not baseline.is_dir():
        raise ValueError("trusted_baseline_missing")
    return {
        "baseline": baseline, "inbox": source / "files",
        "output": output_root / release_id,
        "envelope": envelope_path, "ledger": ledger,
        "expected_base": base, "release_id": release_id,
    }


def run(root, secret_path, current_path, release_id):
    args = inspect_delivery(root, secret_path, current_path, release_id)
    return execute(base=args["baseline"], inbox=args["inbox"],
                   output=args["output"], envelope_path=args["envelope"],
                   secret_path=secret_path, expected_base=args["expected_base"],
                   ledger=args["ledger"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging-root", required=True)
    parser.add_argument("--secret-file", required=True)
    parser.add_argument("--trusted-current", required=True)
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.staging_root, args.secret_file,
                         args.trusted_current, args.release_id)))


if __name__ == "__main__":
    main()
