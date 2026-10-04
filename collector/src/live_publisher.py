from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil
import threading
from typing import Any

from .discovery import ElectionTarget
from .parser import ParsedResult, parse_ea20
from .planner import (
    build_collection_plan,
    build_ea14_url,
)
from .runtime import (
    RuntimeSettings,
    build_config_url,
    load_settings,
    select_supported_elections,
)
from .static_exporter import (
    StaticExportTarget,
    result_relative_path,
    write_json_atomic,
)
from .tse_client import TseClient


DEFAULT_STATE_DIR = (
    "/var/lib/election-results-platform/live"
)
DEFAULT_WORKERS = 16
DEFAULT_EXPECTED_TARGETS = 137


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    return value


def static_payload_from_parsed(
    parsed: ParsedResult,
    *,
    captured_at: datetime,
) -> dict[str, Any]:
    if len(parsed.offices) != 1:
        raise ValueError(
            "Live result must contain exactly one office."
        )

    office = parsed.offices[0]

    candidates = [
        {
            "tse_candidate_seq":
                candidate.tse_candidate_seq,
            "display_order":
                candidate.display_order,
            "ballot_number":
                candidate.ballot_number,
            "name":
                candidate.name,
            "ballot_name":
                candidate.ballot_name,
            "party_number":
                candidate.party_number,
            "party_acronym":
                candidate.party_acronym,
            "party_name":
                candidate.party_name,
            "alliance_name":
                candidate.alliance_name,
            "votes":
                candidate.votes,
            "vote_percentage":
                _json_value(
                    candidate.vote_percentage
                ),
            "candidate_status":
                candidate.candidate_status,
            "result_status":
                candidate.result_status,
            "elected":
                candidate.elected,
            "running_mates":
                list(
                    candidate.running_mates
                ),
        }
        for candidate in office.candidates
    ]

    stats = parsed.stats

    return {
        "schema_version": 1,
        "environment": os.getenv(
            "TSE_ENVIRONMENT",
            "simulado2026",
        ),

        "election": {
            "code": parsed.election_code,
            "round": parsed.round_number,
        },

        "scope": {
            "code": parsed.scope_code,
            "type": parsed.scope_type,
            "uf": (
                parsed.scope_code.upper()
                if (
                    parsed.scope_type == "uf"
                    and len(parsed.scope_code) == 2
                )
                else None
            ),
        },

        "office": {
            "code": office.code,
            "name": office.name,
            "seats": office.seats,
        },

        "snapshot": {
            "tse_idg": parsed.tse_idg,
            "generated_at":
                _json_value(
                    parsed.generated_at
                ),
            "totalized_at":
                _json_value(
                    parsed.totalized_at
                ),
            "captured_at":
                captured_at.isoformat(),

            "sections": {
                "total":
                    stats.sections_total,
                "totalized":
                    stats.sections_totalized,
                "percentage":
                    _json_value(
                        stats.sections_percentage
                    ),
            },

            "electorate": {
                "total":
                    stats.electorate_total,
                "totalized":
                    stats.electorate_totalized,
            },

            "turnout": {
                "total":
                    stats.turnout,
                "percentage":
                    _json_value(
                        stats.turnout_percentage
                    ),
            },

            "abstentions": {
                "total":
                    stats.abstentions,
                "percentage":
                    _json_value(
                        stats.abstention_percentage
                    ),
            },

            "votes": {
                "total":
                    stats.votes_total,
                "candidate_valid":
                    stats.candidate_valid_votes,
                "valid":
                    stats.valid_votes,
                "blank":
                    stats.blank_votes,
                "null":
                    stats.null_votes,
            },
        },

        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def _validate_target(
    *,
    target: ElectionTarget,
    parsed: ParsedResult,
) -> None:
    if parsed.election_code != target.election_code:
        raise ValueError(
            "Live EA20 election mismatch."
        )

    if parsed.round_number != target.round_number:
        raise ValueError(
            "Live EA20 round mismatch."
        )

    if (
        parsed.scope_code.lower()
        != target.scope_code.lower()
    ):
        raise ValueError(
            "Live EA20 scope mismatch."
        )

    office_codes = tuple(
        office.code
        for office in parsed.offices
    )

    if office_codes != (
        target.office_code,
    ):
        raise ValueError(
            "Live EA20 office mismatch."
        )


def _manifest_item(
    *,
    payload: dict[str, Any],
    relative_path: Path,
) -> dict[str, Any]:
    return {
        "scope":
            payload["scope"]["code"],
        "scope_type":
            payload["scope"]["type"],
        "uf":
            payload["scope"]["uf"],
        "office":
            payload["office"]["code"],
        "office_name":
            payload["office"]["name"],
        "election_code":
            payload["election"]["code"],
        "round":
            payload["election"]["round"],
        "candidate_count":
            payload["candidate_count"],
        "tse_idg":
            payload["snapshot"]["tse_idg"],
        "captured_at":
            payload["snapshot"]["captured_at"],
        "path":
            relative_path.as_posix(),
    }


def _load_json(
    path: Path,
    default,
):
    if not path.is_file():
        return default

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def _write_json(
    path: Path,
    payload,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = (
        path.with_suffix(
            path.suffix + ".tmp"
        )
    )

    temporary.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    temporary.replace(path)


def _state_paths() -> tuple[
    Path,
    Path,
    Path,
]:
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


def _fetch_targets(
    *,
    targets: tuple[
        ElectionTarget,
        ...
    ],
    target_state: dict[str, Any],
    workers: int,
) -> tuple[
    list[
        tuple[
            ElectionTarget,
            object,
            ParsedResult | None,
        ]
    ],
    list[str],
]:
    local_state = threading.local()

    def client() -> TseClient:
        selected = getattr(
            local_state,
            "client",
            None,
        )

        if selected is None:
            selected = TseClient()
            local_state.client = selected

        return selected

    def job(target: ElectionTarget):
        cached = target_state.get(
            target.url,
            {},
        )

        response = client().fetch_json(
            target.url,
            etag=cached.get("etag"),
            last_modified=(
                cached.get(
                    "last_modified"
                )
            ),
        )

        if response.status_code == 304:
            return (
                target,
                response,
                None,
            )

        if response.payload is None:
            raise RuntimeError(
                "Live EA20 returned no payload."
            )

        parsed = parse_ea20(
            response.payload
        )

        _validate_target(
            target=target,
            parsed=parsed,
        )

        return (
            target,
            response,
            parsed,
        )

    results = []
    errors = []

    with ThreadPoolExecutor(
        max_workers=min(
            workers,
            max(
                len(targets),
                1,
            ),
        ),
        thread_name_prefix="live-ea20",
    ) as executor:
        futures = [
            executor.submit(
                job,
                target,
            )
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
                    (
                        f"{target.url} -> "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    )
                )

    return results, errors


def prepare_live_publish(
    *,
    settings: RuntimeSettings | None = None,
) -> dict[str, Any]:
    selected_settings = (
        settings
        or load_settings()
    )

    workers = int(
        os.getenv(
            "LIVE_PUBLISH_WORKERS",
            str(DEFAULT_WORKERS),
        )
    )

    expected_targets = int(
        os.getenv(
            "LIVE_PUBLISH_EXPECTED_TARGETS",
            os.getenv(
                "PUBLISH_EXPECTED_TARGETS",
                str(
                    DEFAULT_EXPECTED_TARGETS
                ),
            ),
        )
    )

    active_dir, pending_dir, stage_dir = (
        _state_paths()
    )

    root = active_dir.parent
    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.rmtree(
        pending_dir,
        ignore_errors=True,
    )

    shutil.rmtree(
        stage_dir,
        ignore_errors=True,
    )

    pending_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    stage_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    planning_client = TseClient()

    config_response = (
        planning_client.fetch_json(
            build_config_url(
                selected_settings
            )
        )
    )

    if config_response.payload is None:
        raise RuntimeError(
            "TSE configuration returned no payload."
        )

    elections = (
        select_supported_elections(
            config_response.payload,
            selected_settings,
        )
    )

    ea14_payloads: dict[
        int,
        dict[str, Any],
    ] = {}

    for election in elections:
        response = (
            planning_client.fetch_json(
                build_ea14_url(
                    settings=(
                        selected_settings
                    ),
                    election_code=(
                        election.election_code
                    ),
                    cycle=election.cycle,
                )
            )
        )

        if response.payload is None:
            raise RuntimeError(
                "EA14 returned no payload "
                f"for {election.election_code}."
            )

        ea14_payloads[
            election.election_code
        ] = response.payload

    plans = build_collection_plan(
        config_payload=(
            config_response.payload
        ),
        ea14_payloads=ea14_payloads,
        settings=selected_settings,
    )

    targets = tuple(
        target
        for plan in plans
        for target in plan.targets
    )

    if len(targets) != expected_targets:
        raise RuntimeError(
            "Unexpected live target count: "
            f"expected {expected_targets}, "
            f"got {len(targets)}."
        )

    active_target_state = _load_json(
        active_dir
        / "target-state.json",
        {},
    )

    next_target_state = dict(
        active_target_state
    )

    active_manifest = _load_json(
        active_dir / "manifest.json",
        None,
    )

    fetched, errors = _fetch_targets(
        targets=targets,
        target_state=(
            active_target_state
        ),
        workers=workers,
    )

    changed: list[
        tuple[
            ElectionTarget,
            dict[str, Any],
            Path,
        ]
    ] = []

    for (
        target,
        response,
        parsed,
    ) in fetched:
        cached = {
            "etag": response.etag,
            "last_modified":
                response.last_modified,
        }

        if response.status_code == 304:
            previous = dict(
                next_target_state.get(
                    target.url,
                    {},
                )
            )

            previous.update(
                {
                    key: value
                    for key, value
                    in cached.items()
                    if value is not None
                }
            )

            next_target_state[
                target.url
            ] = previous

            continue

        if parsed is None:
            raise RuntimeError(
                "Parsed live EA20 is missing."
            )

        captured_at = datetime.now(
            timezone.utc
        )

        payload = (
            static_payload_from_parsed(
                parsed,
                captured_at=(
                    captured_at
                ),
            )
        )

        relative_path = (
            result_relative_path(
                StaticExportTarget(
                    scope_code=(
                        target.scope_code
                    ),
                    office_code=(
                        target.office_code
                    ),
                )
            )
        )

        write_json_atomic(
            payload,
            stage_dir / relative_path,
        )

        next_target_state[
            target.url
        ] = {
            **cached,
            "tse_idg":
                payload["snapshot"][
                    "tse_idg"
                ],
            "path":
                relative_path
                .as_posix(),
        }

        changed.append(
            (
                target,
                payload,
                relative_path,
            )
        )

    if (
        active_manifest is None
        and (
            errors
            or len(changed)
            != expected_targets
        )
    ):
        raise RuntimeError(
            "Live publisher bootstrap requires "
            "a complete first snapshot. "
            f"changed={len(changed)}, "
            f"errors={len(errors)}."
        )

    manifest_entries = {}

    if active_manifest is not None:
        for item in active_manifest.get(
            "results",
            [],
        ):
            manifest_entries[
                (
                    str(
                        item["scope"]
                    ).lower(),
                    int(
                        item["office"]
                    ),
                )
            ] = item

    for (
        target,
        payload,
        relative_path,
    ) in changed:
        manifest_entries[
            (
                target.scope_code.lower(),
                target.office_code,
            )
        ] = _manifest_item(
            payload=payload,
            relative_path=(
                relative_path
            ),
        )

    if len(manifest_entries) != expected_targets:
        raise RuntimeError(
            "Live manifest is incomplete: "
            f"expected {expected_targets}, "
            f"got {len(manifest_entries)}."
        )

    generated_at = datetime.now(
        timezone.utc
    ).isoformat()

    manifest_results = sorted(
        manifest_entries.values(),
        key=lambda item: (
            int(item["office"]),
            str(item["scope"]),
        ),
    )

    manifest = {
        "schema_version": 1,
        "environment":
            selected_settings.environment,
        "generated_at":
            generated_at,
        "result_count":
            len(manifest_results),
        "candidate_count":
            sum(
                int(
                    item[
                        "candidate_count"
                    ]
                )
                for item
                in manifest_results
            ),
        "results":
            manifest_results,
    }

    version = {
        "schema_version": 1,
        "environment":
            selected_settings.environment,
        "generated_at":
            generated_at,
    }

    _write_json(
        pending_dir
        / "target-state.json",
        next_target_state,
    )

    _write_json(
        pending_dir
        / "manifest.json",
        manifest,
    )

    _write_json(
        pending_dir
        / "version.json",
        version,
    )

    if changed:
        _write_json(
            stage_dir
            / "manifest.json",
            manifest,
        )

        _write_json(
            stage_dir
            / "version.json",
            version,
        )

    else:
        shutil.rmtree(
            stage_dir,
            ignore_errors=True,
        )

    return {
        "status": "prepared",
        "environment":
            selected_settings.environment,
        "targets_checked":
            len(targets),
        "changed_targets":
            len(changed),
        "not_modified_targets":
            (
                len(fetched)
                - len(changed)
            ),
        "errors":
            errors,
        "stage_dir":
            str(stage_dir),
    }


def commit_live_state() -> dict[str, Any]:
    active_dir, pending_dir, stage_dir = (
        _state_paths()
    )

    if not pending_dir.is_dir():
        raise RuntimeError(
            "No pending live state to commit."
        )

    backup_dir = (
        active_dir.parent
        / "state.old"
    )

    shutil.rmtree(
        backup_dir,
        ignore_errors=True,
    )

    if active_dir.exists():
        active_dir.replace(
            backup_dir
        )

    try:
        pending_dir.replace(
            active_dir
        )

    except Exception:
        if (
            backup_dir.exists()
            and not active_dir.exists()
        ):
            backup_dir.replace(
                active_dir
            )

        raise

    shutil.rmtree(
        backup_dir,
        ignore_errors=True,
    )

    shutil.rmtree(
        stage_dir,
        ignore_errors=True,
    )

    return {
        "status": "committed",
        "state_dir":
            str(active_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Low-latency direct TSE "
            "static publisher."
        )
    )

    parser.add_argument(
        "action",
        choices=(
            "prepare",
            "commit",
        ),
    )

    args = parser.parse_args()

    if args.action == "prepare":
        result = prepare_live_publish()
    else:
        result = commit_live_state()

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
