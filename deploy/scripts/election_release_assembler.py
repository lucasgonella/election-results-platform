"""Offline release assembler for a controlled Locaweb FTP inbox.

Does not read credentials, run FTP, alter public releases or switch version.json.
Operator must independently verify the completed output before publication.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_name(name):
    if (not isinstance(name, str) or not name or "\\" in name
            or name.startswith("/") or any(p in ("", ".", "..") for p in name.split("/"))):
        raise ValueError("unsafe_release_path")
    return name


def regular_file(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("not_regular_file")
    return path.read_bytes()


def assemble(base, inbox, destination, manifest):
    base, inbox, destination = map(Path, (base, inbox, destination))
    if base.is_symlink() or inbox.is_symlink() or not base.is_dir() or not inbox.is_dir():
        raise ValueError("invalid_input_directory")
    if destination.exists() or destination.is_symlink():
        raise ValueError("destination_exists")
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise ValueError("invalid_destination_parent")
    # Reject overlap; never create an output within a source.
    for source_dir in (base, inbox):
        if destination.resolve().is_relative_to(source_dir.resolve()):
            raise ValueError("overlapping_directories")
    if not isinstance(manifest, dict) or set(manifest) != {"files", "changed"}:
        raise ValueError("invalid_assembly_manifest")
    inventory = manifest["files"]
    changes = manifest["changed"]
    if not isinstance(inventory, dict) or not isinstance(changes, list) or not inventory:
        raise ValueError("invalid_assembly_inventory")
    names = set(inventory)
    if len(names) != 140 or not {"version.json", "manifest.json", "alerts.json"}.issubset(names):
        raise ValueError("incomplete_release_inventory")
    for name in names:
        safe_name(name)
    if any(not isinstance(name, str) for name in changes):
        raise ValueError("invalid_changed_set")
    if len(changes) != len(set(changes)) or not set(changes).issubset(names):
        raise ValueError("invalid_changed_set")
    for name, expected in inventory.items():
        if (not isinstance(expected, dict) or set(expected) != {"sha256", "size"}
                or not isinstance(expected["sha256"], str)
                or len(expected["sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in expected["sha256"])
                or not isinstance(expected["size"], int)
                or expected["size"] < 1):
            raise ValueError("invalid_file_fingerprint")

    def read_under(root, name):
        path = root
        for component in name.split("/"):
            path = path / component
            if path.is_symlink():
                raise ValueError("symlink_not_allowed")
        return regular_file(path)

    # Validate every input byte before creating the destination.
    verified = {}
    for name in sorted(names):
        raw = read_under(inbox if name in changes else base, name)
        entry = inventory[name]
        if len(raw) != entry["size"] or sha(raw) != entry["sha256"]:
            raise ValueError("release_hash_mismatch:" + name)
        verified[name] = raw
    # Reject unexpected files in the copied baseline to avoid leaking extra assets.
    baseline_names = {p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file()}
    if baseline_names != names:
        raise ValueError("unexpected_baseline_inventory")
    inbox_names = {p.relative_to(inbox).as_posix() for p in inbox.rglob("*") if p.is_file() or p.is_symlink()}
    if inbox_names != set(changes):
        raise ValueError("unexpected_delta_inventory")

    tmp = Path(tempfile.mkdtemp(prefix=".assembly-", dir=destination.parent))
    try:
        for name, raw in verified.items():
            output = tmp / name
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        for name, entry in inventory.items():
            if sha(regular_file(tmp / name)) != entry["sha256"]:
                raise ValueError("assembled_output_mismatch")
        os.rename(tmp, destination)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)
    return {"status": "assembled", "files": len(inventory), "changed": len(changes),
            "directory": str(destination)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--inbox", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    a = p.parse_args()
    plan = json.loads(regular_file(a.manifest))
    print(json.dumps(assemble(a.base, a.inbox, a.output, plan)))


if __name__ == "__main__":
    main()
