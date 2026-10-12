"""Isolated official second-round collection into an offline, reviewable package.

No FTP, site activation, production checkout or first-round state writes.
Requires an explicit private absolute output directory, absent at invocation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import re

from .live_static import manifest_item, static_payload, validate_target
from .parser import parse_ea20
from .planner import fetch_collection_plan
from .runtime import RuntimeSettings
from .second_round_discovery import SETTINGS
from .tse_client import TseClient


def validate_destination(path: Path):
    if not path.is_absolute() or path.is_symlink() or path.exists():
        raise ValueError("second_round_output_must_be_absent_absolute_path")
    root = path.resolve()
    if root == Path("/") or len(root.parts) < 4:
        raise ValueError("unsafe_second_round_output")
    return root


def collect_offline(output: Path, *, client=None, plans=None, clock=None):
    output = validate_destination(output)
    if SETTINGS != RuntimeSettings("https://resultados.tse.jus.br", "oficial", "ele2026", 2):
        raise ValueError("invalid_official_round_two_runtime")
    client = client or TseClient()
    plans = fetch_collection_plan(settings=SETTINGS, client=client) if plans is None else plans
    targets = [target for plan in plans for target in plan.targets]
    if not targets:
        return {"status": "awaiting_official_round_two_configuration", "targets": 0,
                "publication_enabled": False}
    if len(targets) > 60:
        raise ValueError("unexpected_second_round_target_count")
    identities = set()
    for target in targets:
        key = (target.scope_code.lower(), target.office_code)
        if target.round_number != 2 or target.office_code not in {1, 3} or key in identities:
            raise ValueError("invalid_second_round_target_inventory")
        identities.add(key)
    # Acquire and validate every EA20 before creating any output.
    values = {}
    now = clock or datetime.now(timezone.utc)
    for target in targets:
        fetched = client.fetch_json(target.url)
        if fetched.payload is None or fetched.status_code != 200:
            raise ValueError("second_round_result_unavailable")
        parsed = parse_ea20(fetched.payload)
        validate_target(target, parsed)
        payload = static_payload(parsed, environment="oficial", captured_at=now)
        name = f"{target.scope_code.lower()}/" + ("president" if target.office_code == 1 else "governor") + ".json"
        if name in values:
            raise ValueError("duplicate_second_round_result")
        values[name] = payload
    if len(values) != len(targets):
        raise ValueError("incomplete_second_round_results")
    generated = now.isoformat()
    rows = [manifest_item(value, Path(name)) for name, value in sorted(values.items())]
    if any(row["round"] != 2 for row in rows):
        raise ValueError("mixed_turn_manifest")
    manifest = {"schema_version": 1, "environment": "oficial", "generated_at": generated,
                "result_count": len(rows), "candidate_count": sum(row["candidate_count"] for row in rows),
                "results": rows}
    version = {"schema_version": 1, "environment": "oficial", "generated_at": generated,
               "round": 2}
    # A separate private immutable staging package. Activation requires its own
    # independently audited, transactional publisher and is intentionally absent.
    output.mkdir(parents=True, exist_ok=False)
    for name, value in {**values, "manifest.json": manifest, "version.json": version,
                        "alerts.json": {"schema_version": 1, "environment": "oficial",
                                        "generated_at": generated, "alerts": [], "alert_count": 0}}.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))+"\n",
                        encoding="utf-8")
    return {"status": "staged_offline", "round": 2, "targets": len(targets),
            "output": str(output), "publication_enabled": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(collect_offline(args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
