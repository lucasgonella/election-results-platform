"""Read-only publication monitoring: public GETs and local JSON checkpoints.

Never collects TSE data, loads credentials, invokes control or changes live state.
Exit 2 means an operator alert; exit 0 means the requested checks passed.
Publication generation time is not an upload/activation timestamp.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .election_release import META, entries, parse, stamp, targets, validate_release, validate_result


def origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise ValueError('invalid_public_origin')
    return value.rstrip('/')


def get_public(base, relative):
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    url = origin(base) + '/data/' + relative + '?health=' + secrets.token_hex(8)
    request = Request(url, headers={'Accept': 'application/json', 'Cache-Control': 'no-cache'})
    with build_opener(NoRedirect).open(request, timeout=20) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError('unexpected_public_response')
        raw = response.read(16777217)
    if len(raw) > 16777216:
        raise ValueError('public_file_too_large')
    return raw


def local_checkpoint(root, leaf):
    path = root / leaf / 'version.json'
    if not path.exists():
        return None
    if root.is_symlink() or (root / leaf).is_symlink() or path.is_symlink():
        raise ValueError('unsafe_checkpoint')
    return parse(path.read_bytes())


def assess(marker, rj, checkpoints, now, max_age):
    public_time = stamp(marker['generated_at'])
    if public_time > now:
        raise ValueError('future_public_generation')
    alerts = []
    age = (now - public_time).total_seconds()
    if age > max_age:
        alerts.append('publication_generation_overdue')
    for value in checkpoints.values():
        if value and (value.get('environment') != marker['environment'] or stamp(value['generated_at']) > now):
            raise ValueError('invalid_checkpoint_generation')
    prepared = max((stamp(value['generated_at']) for value in checkpoints.values() if value), default=None)
    pending = checkpoints.get('pending')
    if (pending and stamp(pending['generated_at']) > public_time
            and (now - stamp(pending['generated_at'])).total_seconds() > max_age):
        alerts.append('prepared_generation_unpublished')
    active = checkpoints.get('state')
    if active and stamp(active['generated_at']) != public_time:
        alerts.append('local_public_generation_mismatch')
    if prepared and (now - prepared).total_seconds() > max_age:
        alerts.append('collection_generation_overdue')
    snapshot = rj['snapshot']
    source_age = (now - stamp(snapshot['generated_at'])).total_seconds()
    if source_age < 0 or stamp(snapshot['captured_at']) > now:
        raise ValueError('future_source_generation')
    return {
        'status': 'alert' if alerts else 'ok', 'alerts': alerts,
        'public_snapshot_id': marker['snapshot_id'],
        'public_generation_at': marker['generated_at'],
        'publication_generation_age_seconds': round(age, 3),
        'last_prepared_generation_at': prepared.isoformat() if prepared else None,
        'last_successful_publication_at': None,
        'publication_time_note': 'Activation time is not recorded by the existing marker/receipt.',
        'rj': {'tse_idg': snapshot['tse_idg'], 'source_generated_at': snapshot['generated_at'],
               'captured_at': snapshot['captured_at'], 'source_age_seconds': round(source_age, 3),
               'totalization_final': snapshot.get('totalization_final'),
               'douglas_ruas': [{key: candidate.get(key) for key in
                   ('ballot_name', 'votes', 'vote_percentage', 'result_status')}
                   for candidate in rj['candidates'] if candidate.get('ballot_number') == 22]},
    }


def inspect(base, live_root=None, full=False, expected=None, now=None, max_age=900, read=None):
    now = now or datetime.now(timezone.utc)
    base = origin(base)
    if live_root and (not live_root.is_dir() or live_root.is_symlink()):
        raise ValueError('unsafe_live_root')
    read = read or (lambda relative: get_public(base, relative))
    marker_raw = read('version.json')
    marker = parse(marker_raw)
    sid = marker.get('snapshot_id')
    if not isinstance(sid, str) or not re.fullmatch('[a-f0-9]{64}', sid):
        raise ValueError('invalid_public_snapshot')
    prefix = 'releases/' + sid + '/'
    values = {name: read(prefix + name) for name in sorted(META)}
    manifest = parse(values['manifest.json'])
    rows = entries(manifest)
    version = parse(values['version.json'])
    for name in META:
        value = parse(values[name])
        if any(value.get(key) != marker.get(key) for key in ('environment', 'generated_at')):
            raise ValueError('public_metadata_mismatch')
    if marker.get('environment') not in ('oficial', 'fixture'):
        raise ValueError('invalid_public_environment')
    round_number = rows['rj/governor.json']['round']
    if type(round_number) is not int or round_number not in (1, 2):
        raise ValueError('invalid_public_round')
    if full or expected:
        with ThreadPoolExecutor(max_workers=4) as pool:
            names = sorted(targets())
            values.update(zip(names, pool.map(lambda name: read(prefix + name), names)))
        validate_release(values, version['environment'], round_number)
    else:
        values['rj/governor.json'] = read(prefix + 'rj/governor.json')
        validate_result('rj/governor.json', parse(values['rj/governor.json']),
                        rows['rj/governor.json'], version['environment'], round_number)
    inventory = {name: {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
                 for name, raw in values.items()}
    if expected and (expected['snapshot_id'] != sid or expected['files'] != inventory):
        raise ValueError('public_checksum_mismatch')
    if read('version.json') != marker_raw:
        raise ValueError('public_selection_changed')
    checkpoints = {leaf: local_checkpoint(live_root, leaf) for leaf in ('state', 'pending')} if live_root else {}
    if live_root and checkpoints['state'] is None:
        raise ValueError('local_state_missing')
    report = assess(marker, parse(values['rj/governor.json']), checkpoints, now, max_age)
    report.update(checked_at=now.isoformat(), files_verified=len(values), results_verified=len(values) - 3,
                  checksums_match_reviewed_inventory=bool(expected), files=inventory,
                  remote_writes=False, live_state_writes=False)
    return report


def write_report(path, report, live_root):
    resolved = path.resolve()
    if live_root and (resolved.is_relative_to(live_root.resolve()) or live_root.resolve().is_relative_to(resolved)):
        raise ValueError('report_overlaps_live_state')
    if path.is_symlink():
        raise ValueError('unsafe_report_path')
    # The monitoring destination is independent of publisher checkpoints.
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def static_status(report, health, now, max_age):
    # A completed poll with no eligible changes is not a stalled publication.
    # Source age remains visible; do not pretend an unchanged release was uploaded.
    alerts=report['alerts']
    if health.get('snapshot_id')!=report['public_snapshot_id']:
        alerts.append('static_local_public_mismatch')
    collected=stamp(health['collected_at']) if health.get('collected_at') else None
    verified=stamp(health['public_verified_at']) if health.get('public_verified_at') else None
    if not collected or collected>now or (now-collected).total_seconds()>max_age:
        alerts.append('static_collection_overdue')
    if not verified or verified>now or (now-verified).total_seconds()>max_age:
        alerts.append('static_public_verification_overdue')
    if health.get('status')=='failed':alerts.append('static_publication_failed')
    if health.get('review_required'):alerts.append('election_changes_awaiting_review')
    if (health.get('status') in {'published','unchanged'} and collected and verified
            and 0 <= (now-collected).total_seconds() <= max_age
            and 0 <= (now-verified).total_seconds() <= max_age
            and health.get('snapshot_id')==report['public_snapshot_id'] and health.get('eligible_changes')==0):
        if 'publication_generation_overdue' in alerts:alerts.remove('publication_generation_overdue')
    report.update(last_successful_publication_at=health.get('published_at'),last_collection_completed_at=health.get('collected_at'),
                  publication_time_note='Static publisher completion after full public verification.',
                  static_health=health,status='alert' if alerts else 'ok')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='https://afgnet.com.br')
    parser.add_argument('--live-root', type=Path)
    parser.add_argument('--max-age-seconds', type=int, default=900)
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--expected-inventory', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--static-health',type=Path)
    args = parser.parse_args()
    if args.max_age_seconds < 1:
        parser.error('max-age-seconds must be positive')
    if args.report and args.live_root and args.report.resolve().is_relative_to(args.live_root.resolve()):
        parser.error('report must be outside live state')
    try:
        expected = parse(args.expected_inventory.read_bytes()) if args.expected_inventory else None
        report = inspect(args.base_url, args.live_root, args.full, expected, max_age=args.max_age_seconds)
        if args.static_health:
            report=static_status(report,parse(args.static_health.read_bytes()),datetime.now(timezone.utc),args.max_age_seconds)
    except Exception as error:
        # No response bodies, arbitrary exception messages or credentials in logs.
        report = {'status': 'alert', 'alerts': ['publication_verification_failed'],
                  'error_type': type(error).__name__, 'checked_at': datetime.now(timezone.utc).isoformat(),
                  'last_successful_publication_at': None, 'remote_writes': False, 'live_state_writes': False}
        if isinstance(error, ValueError) and re.fullmatch('[a-z_]{1,80}', str(error)):
            report['error_code'] = str(error)
    if args.report:
        write_report(args.report, report, args.live_root)
    print(json.dumps(report, ensure_ascii=True, separators=(',', ':')))
    return 0 if report['status'] == 'ok' else 2


if __name__ == '__main__':
    raise SystemExit(main())
