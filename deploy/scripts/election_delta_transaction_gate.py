"""Read-only gate between offline delta assembly and election transaction journal.

Does NOT promote releases or alter version.json, pending.json or watermarks.
The production FTP publisher remains authoritative for commit and rollback.
"""
import argparse
import json
from pathlib import Path

from election_delta_executor import authorize
from election_release_assembler import regular_file, safe_name, sha
from collector.src.election_release import canonical, digest, targets, META
from collector.src.static_election_publish import descriptor, compare


def preflight(*, envelope, secret, current, pending, assembled, expected_base, baseline_values=None, reviews=None):
    plan, release = authorize(envelope, secret, expected_base)
    if not isinstance(current, dict) or current.get("snapshot_id") != expected_base:
        raise ValueError("current_snapshot_mismatch")
    if pending not in (None, {}) and pending.get("status") not in ("complete", "restored"):
        raise ValueError("incomplete_prior_transaction")
    if not isinstance(plan, dict) or set(plan) != {"files", "changed"}:
        raise ValueError("invalid_assembly_plan")
    files = plan["files"]
    if not isinstance(files, dict) or len(files) != 140:
        raise ValueError("invalid_release_inventory")
    assembled = Path(assembled)
    if assembled.is_symlink() or not assembled.is_dir() or assembled.name != release:
        raise ValueError("invalid_assembled_directory")
    for name, entry in files.items():
        safe_name(name)
        if not isinstance(entry, dict) or set(entry) != {"sha256", "size"}:
            raise ValueError("invalid_assembly_file")
        path = assembled
        for part in name.split("/"):
            path = path / part
            if path.is_symlink():
                raise ValueError("symlink_not_allowed")
        raw = regular_file(path)
        if len(raw) != entry["size"] or sha(raw) != entry["sha256"]:
            raise ValueError("assembled_hash_mismatch")
    actual = {p.relative_to(assembled).as_posix() for p in assembled.rglob("*") if p.is_file() or p.is_symlink()}
    if actual != set(files):
        raise ValueError("unexpected_assembled_inventory")
    if set(files) != set(targets()) | META:
        raise ValueError("incorrect_electoral_inventory")
    values = {name: regular_file(assembled / name) for name in files}
    derived = descriptor(values)
    if derived["files"] != files or digest(canonical(derived)) != release:
        raise ValueError("electoral_release_identity_mismatch")
    if baseline_values is None:
        raise ValueError("trusted_baseline_required")
    if set(baseline_values) != set(files):
        raise ValueError("baseline_inventory_mismatch")
    compare(baseline_values, values, reviews=reviews)
    return {"state": "verified_for_transaction_review",
            "snapshot_id": release, "base_snapshot_id": expected_base,
            "files": len(files), "changed": len(plan["changed"]),
            "activation_permitted": False}


def main():
    parser = argparse.ArgumentParser()
    for key in ("envelope", "secret", "current", "pending", "assembled", "expected-base"):
        parser.add_argument("--" + key, required=True)
    args = parser.parse_args()
    secret = regular_file(Path(args.secret))
    envelope = json.loads(regular_file(Path(args.envelope)))
    current = json.loads(regular_file(Path(args.current)))
    pending = json.loads(regular_file(Path(args.pending)))
    print(json.dumps(preflight(envelope=envelope, secret=secret, current=current,
                               pending=pending, assembled=args.assembled,
                               expected_base=args.expected_base)))


if __name__ == "__main__":
    main()
