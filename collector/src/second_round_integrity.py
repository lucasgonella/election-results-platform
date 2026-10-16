"""Fail-closed offline verification of a second-round release candidate.

No FTP access, publication, or directory mutation. The verifier produces the
content-addressed release ID required before building a separate FTP publisher.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .election_release import UFS, candidates, parse, stamp, tree, validate_result


META = {"manifest.json", "version.json", "alerts.json"}
OFFICES = {1: "president", 3: "governor"}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def verify(directory: Path):
    return verify_values(tree(directory))


def verify_values(values, *, strict=False):
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
                or not scope in UFS + ["br", "zz"]
                or name != f"{scope}/{OFFICES[office]}.json" or name in names):
            raise ValueError("invalid_second_round_path")
        if item.get("round") != 2 or (office == 3 and scope not in UFS):
            raise ValueError("invalid_second_round_entry_identity")
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
        if strict:
            validate_result(name, payload, item, 'oficial', 2)
            for candidate in payload['candidates']:
                if not isinstance(candidate.get('name'), str) or not candidate['name'].strip():
                    raise ValueError('invalid_second_round_candidate_name')
                if candidate['elected'] and not candidate['result_status'].casefold().startswith('eleito'):
                    raise ValueError('invalid_second_round_elected_status')
            sections = payload['snapshot'].get('sections', {})
            for field in ('total', 'totalized'):
                if type(sections.get(field)) is not int or sections[field] < 0:
                    raise ValueError('invalid_second_round_sections')
            if payload['candidate_count'] < 1:
                raise ValueError('missing_second_round_candidates')
            if sections['totalized'] == 0 and any(c['votes'] != 0 or c['elected'] or Decimal(str(c['vote_percentage'])) != 0 for c in payload['candidates']):
                raise ValueError('second_round_results_without_totalized_sections')
            if sections['totalized'] > sections['total']:
                raise ValueError('invalid_second_round_sections')
            for group in ('sections', 'turnout', 'abstentions'):
                percent = payload['snapshot'].get(group, {}).get('percentage')
                if percent is not None:
                    try: numeric = Decimal(str(percent))
                    except InvalidOperation: raise ValueError('invalid_second_round_statistics') from None
                    if not numeric.is_finite() or not 0 <= numeric <= 100:
                        raise ValueError('invalid_second_round_statistics')
            for group in ('electorate', 'turnout', 'abstentions'):
                for key, value in payload['snapshot'].get(group, {}).items():
                    if key != 'percentage' and value is not None and (type(value) is not int or value < 0):
                        raise ValueError('invalid_second_round_statistics')
            if not isinstance(payload['snapshot'].get('votes'), dict):
                raise ValueError('invalid_second_round_votes')
            for value in payload['snapshot']['votes'].values():
                if value is not None and (type(value) is not int or value < 0):
                    raise ValueError('invalid_second_round_votes')
        count += payload["candidate_count"]
    extra = {'portal.json'} if 'portal.json' in values else set()
    if set(values) != names | META | extra:
        raise ValueError("unexpected_second_round_files")
    if extra:
        portal = parse(values['portal.json'])
        expected = {'schema_version': 1, 'environment': 'oficial', 'round': 2,
                    'files': {name: parse(raw) for name, raw in values.items() if name != 'portal.json'}}
        if portal != expected:
            raise ValueError('second_round_portal_bundle_mismatch')
    if count != manifest.get("candidate_count"):
        raise ValueError("second_round_candidate_count_mismatch")
    if (not isinstance(alerts.get("alerts"), list)
            or alerts.get("alert_count") != len(alerts["alerts"])):
        raise ValueError("invalid_second_round_alerts")
    phase = 'counting' if any(parse(values[name]).get('snapshot', {}).get('sections', {}).get('totalized', 0) > 0 for name in names) else 'candidate_roster'
    if strict and any(meta.get('publication_phase', phase) != phase for meta in (version, manifest, alerts)):
        raise ValueError('second_round_publication_phase_mismatch')
    listing = {name: {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
               for name, raw in sorted(values.items())}
    descriptor = {"schema_version": 1, "environment": "oficial", "round": 2,
                  "generated_at": timestamp, "files": listing}
    release_id = hashlib.sha256(canonical(descriptor)).hexdigest()
    return {"status": "verified_offline", "round": 2, "snapshot_id": release_id,
            "files": len(values), "targets": len(rows), "descriptor": descriptor,
            "publication_phase": phase,
            "publication_enabled": False}
