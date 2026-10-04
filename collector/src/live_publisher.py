from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import threading

from .live_static import (
    elected_alerts,
    manifest_item,
    static_payload,
    validate_target,
)
from .parser import parse_ea20
from .planner import (
    build_collection_plan,
    build_ea14_url,
)
from .runtime import (
    build_config_url,
    load_settings,
    select_supported_elections,
)
from .static_exporter import write_json_atomic
from .static_site_builder import (
    StaticExportTarget,
    result_relative_path,
)
from .tse_client import TseClient


DEFAULT_STATE_DIR = "/var/lib/election-results-platform/live"


def state_paths():
    root = Path(
        os.getenv(
            "LIVE_PUBLISH_STATE_DIR",
            DEFAULT_STATE_DIR,
        )
    )
    return (
        root / "state",
        root / "pending",
        root / "stage",
    )


def load_json(path: Path, default):
    if not path.is_file():
        return default
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )
    temporary.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def fetch_targets(
    targets,
    target_state,
    workers,
):
    local = threading.local()

    def client():
        value = getattr(local, "client", None)
        if value is None:
            value = TseClient()
            local.client = value
        return value

    def job(target):
        cached = target_state.get(
            target.url,
            {},
        )
        response = client().fetch_json(
            target.url,
            etag=cached.get("etag"),
            last_modified=cached.get(
                "last_modified"
            ),
        )
        if response.status_code == 304:
            return target, response, None

        if response.payload is None:
            raise RuntimeError(
                "EA20 returned no payload."
            )

        parsed = parse_ea20(
            response.payload
        )
        validate_target(target, parsed)
        return target, response, parsed

    results = []
    errors = []

    with ThreadPoolExecutor(
        max_workers=min(
            workers,
            max(len(targets), 1),
        )
    ) as executor:
        futures = [
            executor.submit(job, target)
            for target in targets
        ]
        for target, future in zip(
            targets,
            futures,
            strict=True,
        ):
            try:
                results.append(
                    future.result()
                )
            except Exception as exc:
                errors.append(
                    f"{target.url} -> "
                    f"{type(exc).__name__}: {exc}"
                )

    return results, errors


def prepare() -> dict:
    settings = load_settings()
    workers = int(
        os.getenv(
            "LIVE_PUBLISH_WORKERS",
            "16",
        )
    )
    expected = int(
        os.getenv(
            "LIVE_PUBLISH_EXPECTED_TARGETS",
            os.getenv(
                "PUBLISH_EXPECTED_TARGETS",
                "137",
            ),
        )
    )

    active, pending, stage = state_paths()
    active.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    shutil.rmtree(
        pending,
        ignore_errors=True,
    )
    shutil.rmtree(
        stage,
        ignore_errors=True,
    )
    pending.mkdir(
        parents=True,
        exist_ok=True,
    )
    stage.mkdir(
        parents=True,
        exist_ok=True,
    )

    planning_client = TseClient()
    config = planning_client.fetch_json(
        build_config_url(settings)
    )
    if config.payload is None:
        raise RuntimeError(
            "TSE config returned no payload."
        )

    elections = select_supported_elections(
        config.payload,
        settings,
    )
    ea14_payloads = {}

    for election in elections:
        response = planning_client.fetch_json(
            build_ea14_url(
                settings=settings,
                election_code=(
                    election.election_code
                ),
                cycle=election.cycle,
            )
        )
        if response.payload is None:
            raise RuntimeError(
                "EA14 returned no payload."
            )
        ea14_payloads[
            election.election_code
        ] = response.payload

    plans = build_collection_plan(
        config_payload=config.payload,
        ea14_payloads=ea14_payloads,
        settings=settings,
    )
    targets = tuple(
        target
        for plan in plans
        for target in plan.targets
    )
    if len(targets) != expected:
        raise RuntimeError(
            f"Expected {expected} targets, "
            f"got {len(targets)}."
        )

    old_state = load_json(
        active / "target-state.json",
        {},
    )
    next_state = dict(old_state)
    old_manifest = load_json(
        active / "manifest.json",
        None,
    )
    old_alerts = load_json(
        active / "alerts.json",
        {
            "schema_version": 1,
            "alerts": [],
        },
    )

    fetched, errors = fetch_targets(
        targets,
        old_state,
        workers,
    )

    changed = []

    for target, response, parsed in fetched:
        cache = {
            "etag": response.etag,
            "last_modified":
                response.last_modified,
        }

        if response.status_code == 304:
            previous = dict(
                next_state.get(
                    target.url,
                    {},
                )
            )
            previous.update(
                {
                    key: value
                    for key, value
                    in cache.items()
                    if value is not None
                }
            )
            next_state[
                target.url
            ] = previous
            continue

        if parsed is None:
            raise RuntimeError(
                "Parsed EA20 is missing."
            )

        payload = static_payload(
            parsed,
            environment=settings.environment,
            captured_at=datetime.now(
                timezone.utc
            ),
        )
        relative = result_relative_path(
            StaticExportTarget(
                scope_code=target.scope_code,
                office_code=target.office_code,
            )
        )
        write_json_atomic(
            payload,
            stage / relative,
        )
        next_state[target.url] = {
            **cache,
            "tse_idg":
                payload["snapshot"][
                    "tse_idg"
                ],
            "path": relative.as_posix(),
        }
        changed.append(
            (
                target,
                payload,
                relative,
            )
        )

    if (
        old_manifest is None
        and (
            errors
            or len(changed) != expected
        )
    ):
        raise RuntimeError(
            "Initial live snapshot incomplete: "
            f"changed={len(changed)} "
            f"errors={len(errors)}."
        )

    entries = {}
    if old_manifest:
        for item in old_manifest.get(
            "results",
            [],
        ):
            entries[
                (
                    str(item["scope"]).lower(),
                    int(item["office"]),
                )
            ] = item

    for target, payload, relative in changed:
        entries[
            (
                target.scope_code.lower(),
                target.office_code,
            )
        ] = manifest_item(
            payload,
            relative,
        )

    alert_entries = {
        str(item["id"]): item
        for item in old_alerts.get(
            "alerts",
            [],
        )
    }

    for target, payload, _ in changed:
        target_scope = (
            target.scope_code.lower()
        )
        target_office = (
            target.office_code
        )

        alert_entries = {
            key: item
            for key, item
            in alert_entries.items()
            if not (
                str(
                    item.get("scope", "")
                ).lower()
                == target_scope
                and int(
                    item.get("office", -1)
                )
                == target_office
            )
        }

        for item in elected_alerts(
            payload
        ):
            alert_entries[
                str(item["id"])
            ] = item

    if len(entries) != expected:
        raise RuntimeError(
            f"Live manifest incomplete: "
            f"{len(entries)}/{expected}."
        )

    generated_at = datetime.now(
        timezone.utc
    ).isoformat()
    results = sorted(
        entries.values(),
        key=lambda item: (
            int(item["office"]),
            str(item["scope"]),
        ),
    )
    manifest = {
        "schema_version": 1,
        "environment": settings.environment,
        "generated_at": generated_at,
        "result_count": len(results),
        "candidate_count": sum(
            int(item["candidate_count"])
            for item in results
        ),
        "results": results,
    }
    version = {
        "schema_version": 1,
        "environment": settings.environment,
        "generated_at": generated_at,
    }
    alerts = {
        "schema_version": 1,
        "environment": settings.environment,
        "generated_at": generated_at,
        "alerts": sorted(
            alert_entries.values(),
            key=lambda item: (
                str(
                    item.get(
                        "generated_at"
                    )
                    or ""
                ),
                str(item["id"]),
            ),
            reverse=True,
        ),
    }

    write_json(
        pending / "target-state.json",
        next_state,
    )
    write_json(
        pending / "manifest.json",
        manifest,
    )
    write_json(
        pending / "version.json",
        version,
    )
    write_json(
        pending / "alerts.json",
        alerts,
    )

    if changed:
        write_json(
            stage / "manifest.json",
            manifest,
        )
        write_json(
            stage / "version.json",
            version,
        )
        write_json(
            stage / "alerts.json",
            alerts,
        )
    else:
        shutil.rmtree(
            stage,
            ignore_errors=True,
        )

    return {
        "status": "prepared",
        "targets_checked": len(targets),
        "changed_targets": len(changed),
        "not_modified_targets":
            len(fetched) - len(changed),
        "errors": errors,
        "stage_dir": str(stage),
    }


def commit() -> dict:
    active, pending, stage = state_paths()
    if not pending.is_dir():
        raise RuntimeError(
            "No pending live state."
        )

    backup = active.parent / "state.old"
    shutil.rmtree(
        backup,
        ignore_errors=True,
    )
    if active.exists():
        active.replace(backup)

    try:
        pending.replace(active)
    except Exception:
        if (
            backup.exists()
            and not active.exists()
        ):
            backup.replace(active)
        raise

    shutil.rmtree(
        backup,
        ignore_errors=True,
    )
    shutil.rmtree(
        stage,
        ignore_errors=True,
    )
    return {
        "status": "committed",
        "state_dir": str(active),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("prepare", "commit"),
    )
    action = parser.parse_args().action
    result = (
        prepare()
        if action == "prepare"
        else commit()
    )
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())