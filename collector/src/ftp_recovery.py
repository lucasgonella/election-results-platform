"""Offline, selective recovery into a complete release and matching checkpoint.

No collection, network, key loading or live mutations during prepare/verify.
Queue is a separate, gated operation for the future authorized cutover.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import secrets
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

from .ftp_delivery import canonical, freeze, key_from_file

META = {'manifest.json', 'version.json', 'alerts.json'}
STATE = META | {'target-state.json', 'state-meta.json'}
UFS = 'ac al ap am ba ce df es go ma mt ms mg pa pb pr pe pi rj rn rs ro rr sc sp se to'.split()


def targets():
    out = {f'{uf}/president.json': (uf, 1) for uf in UFS + ['br', 'zz']}
    for uf in UFS:
        for office, slug in [(3, 'governor'), (5, 'senator'), (6, 'federal-deputy'),
                             (8 if uf == 'df' else 7, 'district-deputy' if uf == 'df' else 'state-deputy')]:
            out[f'{uf}/{slug}.json'] = (uf, office)
    return out


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def stamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})', value):
        raise ValueError('invalid_timestamp')
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def tree(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError('unsafe_input')
    values = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('symlink')
        if path.is_file():
            raw = path.read_bytes()
            if len(raw) > 16777216:
                raise ValueError('file_too_large')
            values[path.relative_to(root).as_posix()] = raw
    return values


def hashes(values):
    return {name: digest(raw) for name, raw in values.items()}


def parse(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('duplicate_json_key')
            out[key] = value
        return out
    def constant(_):
        raise ValueError('invalid_json_number')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def source(payload):
    snapshot = dict(payload['snapshot'])
    snapshot.pop('captured_at', None)
    snapshot['tse_idg'] = str(snapshot['tse_idg'])
    return [snapshot, payload['candidates'], payload['office']]


def candidates(payload):
    values = payload.get('candidates')
    if not isinstance(values, list) or type(payload.get('candidate_count')) is not int or payload['candidate_count'] != len(values):
        raise ValueError('invalid_candidate_count')
    out = {}
    for candidate in values:
        seq = candidate.get('tse_candidate_seq')
        if type(seq) not in (str, int) or not re.fullmatch(r'[0-9]{1,20}', str(seq)) or str(seq) in out:
            raise ValueError('invalid_candidate_identity')
        if type(candidate.get('votes')) is not int or candidate['votes'] < 0 or type(candidate.get('elected')) is not bool:
            raise ValueError('invalid_candidate_result')
        percent = candidate.get('vote_percentage')
        if type(percent) not in (int, float, str):
            raise ValueError('invalid_candidate_percentage')
        try:
            numeric = Decimal(str(percent))
            if not numeric.is_finite() or not 0 <= numeric <= 100:
                raise ValueError('invalid_candidate_percentage')
        except InvalidOperation:
            raise ValueError('invalid_candidate_percentage') from None
        status = candidate.get('result_status')
        # The existing parser uses elected=true for candidates advancing to
        # the second round too; the explicit status decides the alert kind.
        advances = isinstance(status, str) and status.strip().startswith('2') and 'turno' in status.casefold()
        if not isinstance(status, str) or candidate['elected'] != (status.casefold().startswith('eleito') or advances):
            raise ValueError('inconsistent_candidate_status')
        out[str(seq)] = candidate
    return out


def entries(manifest):
    rows = manifest.get('results')
    if manifest.get('result_count') != 137 or not isinstance(rows, list) or len(rows) != 137:
        raise ValueError('invalid_manifest')
    out = {}
    for row in rows:
        name = row.get('path')
        if name not in targets() or name in out:
            raise ValueError('invalid_manifest')
        out[name] = row
    if set(out) != set(targets()):
        raise ValueError('invalid_manifest')
    return out


def validate_result(name, payload, entry, environment, round_number):
    scope, office = targets()[name]
    snapshot = payload['snapshot']
    if (payload.get('schema_version') != 1 or payload.get('environment') != environment
            or payload['scope']['code'] != scope or payload['office']['code'] != office
            or entry['scope'] != scope or entry['office'] != office
            or type(payload['election']['code']) is not int or payload['election']['code'] < 1
            or type(payload['election']['round']) is not int or payload['election']['round'] != round_number
            or any(entry[field] != value for field, value in {
                'election_code': payload['election']['code'], 'round': payload['election']['round'],
                'tse_idg': snapshot['tse_idg'], 'captured_at': snapshot['captured_at'],
                'candidate_count': payload['candidate_count']}.items())):
        raise ValueError('invalid_result_identity')
    if type(snapshot['tse_idg']) not in (int, str) or not re.fullmatch(r'[0-9]{1,20}', str(snapshot['tse_idg'])):
        raise ValueError('invalid_source_id')
    stamp(snapshot['generated_at']); stamp(snapshot['captured_at'])
    if snapshot.get('totalization_final') is not None and type(snapshot['totalization_final']) is not bool:
        raise ValueError('invalid_totalization_flag')
    candidates(payload)


def validate_release(values, environment, round_number):
    if set(values) != set(targets()) | META:
        raise ValueError('incomplete_release')
    version, manifest, alerts = (parse(values[name]) for name in ('version.json', 'manifest.json', 'alerts.json'))
    stamp(version['generated_at'])
    if version['environment'] != environment or any(meta.get('generated_at') != version['generated_at'] or meta.get('environment') != environment for meta in (manifest, alerts)):
        raise ValueError('metadata_mismatch')
    rows = entries(manifest)
    for name, entry in rows.items():
        validate_result(name, parse(values[name]), entry, environment, round_number)
    total = sum(parse(values[name])['candidate_count'] for name in targets())
    if manifest.get('candidate_count') != total:
        raise ValueError('aggregate_candidate_count_mismatch')
    if not isinstance(alerts.get('alerts'), list) or ('alert_count' in alerts and alerts['alert_count'] != len(alerts['alerts'])):
        raise ValueError('invalid_alerts')
    return rows


def transition(name, old, new):
    if old['election'] != new['election'] or old['scope'] != new['scope'] or old['office']['code'] != new['office']['code']:
        raise ValueError('election_transition_requires_review')
    before, after = old['snapshot'], new['snapshot']
    if before.get('totalization_final') is True and after.get('totalization_final') is not True:
        raise ValueError('totalization_reopened_requires_review')
    a, b = stamp(before['generated_at']), stamp(after['generated_at'])
    if b < a or (b == a and source(old) != source(new)):
        raise ValueError('result_regression')
    oldc, newc = candidates(old), candidates(new)
    changes = []
    for seq in sorted(set(oldc) - set(newc)):
        prior = oldc[seq]
        if prior['result_status'].casefold().startswith('eleito'):
            raise ValueError('elected_revocation_requires_review')
        changes.append({'kind': 'removed', 'candidate_id': seq, 'before': prior['result_status'],
                        'before_votes': prior['votes'], 'candidate_status': prior.get('candidate_status')})
    for seq in sorted(set(newc) - set(oldc)):
        changes.append({'kind': 'added', 'candidate_id': seq, 'after': newc[seq]['result_status']})
    for seq, item in newc.items():
        if seq not in oldc:
            continue
        prior = oldc[seq]
        if prior['result_status'].casefold().startswith('eleito') and not item['result_status'].casefold().startswith('eleito'):
            raise ValueError('elected_revocation_requires_review')
        if prior['result_status'] != item['result_status']:
            changes.append({'kind': 'status', 'candidate_id': seq, 'before': prior['result_status'], 'after': item['result_status']})
    return changes


def alert_bundle(values, environment, generation):
    # Reuse the existing electoral contract; excluded stage alerts never leak.
    from .live_static import elected_alerts
    alerts = [alert for name in targets() for alert in elected_alerts(parse(values[name]))]
    return {'schema_version': 1, 'environment': environment, 'generated_at': generation, 'alerts': alerts}


def prepare(baseline: Path, marker: Path, stage: Path, state: Path, pending: Path,
            output: Path, include: list[str]):
    if marker.is_symlink() or output.exists():
        raise ValueError('unsafe_output_or_marker')
    roots = [p.resolve() for p in (baseline, stage, state, pending)]
    if any(output.resolve().is_relative_to(root) or root.is_relative_to(output.resolve()) for root in roots):
        raise ValueError('output_overlaps_input')
    original = {label: tree(path) for label, path in [('baseline', baseline), ('stage', stage), ('state', state), ('pending', pending)]}
    marker_raw = marker.read_bytes(); selected_marker = parse(marker_raw)
    sid = selected_marker.get('snapshot_id')
    if not isinstance(sid, str) or not re.fullmatch('[a-f0-9]{64}', sid):
        raise ValueError('invalid_baseline_marker')
    environment = selected_marker['environment']
    if environment not in {'oficial', 'fixture'}:
        raise ValueError('unauthorized_environment')
    round_number = parse(original['baseline']['manifest.json'])['results'][0]['round']
    if type(round_number) is not int or round_number not in (1, 2):
        raise ValueError('unauthorized_round')
    base_rows = validate_release(original['baseline'], environment, round_number)
    base_version = parse(original['baseline']['version.json'])
    if any(selected_marker.get(k) != base_version[k] for k in ('environment', 'generated_at')):
        raise ValueError('baseline_marker_mismatch')
    if set(original['state']) != STATE or set(original['pending']) != STATE:
        raise ValueError('invalid_checkpoint')
    if entries(parse(original['state']['manifest.json'])) != base_rows:
        raise ValueError('state_baseline_mismatch')
    stage_rows = entries(parse(original['stage']['manifest.json']))
    if not META <= original['stage'].keys() or not original['stage'].keys() <= set(targets()) | META:
        raise ValueError('invalid_stage_files')
    stage_version = parse(original['stage']['version.json'])
    generation = stage_version['generated_at']
    if stamp(generation) <= stamp(selected_marker['generated_at']):
        raise ValueError('stale_version')
    for name in META:
        meta = parse(original['stage'][name])
        if meta.get('generated_at') != generation or meta.get('environment') != environment:
            raise ValueError('metadata_mismatch')
    for name in original['stage'].keys() - META:
        validate_result(name, parse(original['stage'][name]), stage_rows[name], environment, round_number)
    if entries(parse(original['pending']['manifest.json'])) != stage_rows:
        raise ValueError('pending_stage_mismatch')
    if not include or len(set(include)) != len(include) or any(name not in targets() or name not in original['stage'] for name in include):
        raise ValueError('invalid_selection')
    if any(name.startswith('am/') for name in include):
        raise ValueError('amazonas_requires_review')
    result = dict(original['baseline']); rows = dict(base_rows); transitions = {}
    for name in include:
        transitions[name] = transition(name, parse(result[name]), parse(original['stage'][name]))
        result[name] = original['stage'][name]; rows[name] = stage_rows[name]
    manifest = parse(original['baseline']['manifest.json']) | {
        'generated_at': generation, 'results': [rows[name] for name in base_rows],
        'candidate_count': sum(parse(result[name])['candidate_count'] for name in targets())}
    result['manifest.json'] = canonical(manifest)
    # A stage cannot prescribe a snapshot/delivery ID or activation revision.
    if set(stage_version) - {'schema_version', 'environment', 'generated_at'}:
        raise ValueError('unexpected_version_fields')
    result['version.json'] = canonical(stage_version)
    result['alerts.json'] = canonical(alert_bundle(result, environment, generation))
    validate_release(result, environment, round_number)
    checkpoint = {name: result[name] for name in META}
    cache = parse(original['state']['target-state.json']); next_cache = parse(original['pending']['target-state.json'])
    selected_cache = {value.get('path'): (url, value) for url, value in next_cache.items() if value.get('path') in include}
    if set(selected_cache) != set(include) or sum(value.get('path') in include for value in next_cache.values()) != len(include):
        raise ValueError('pending_cache_mismatch')
    for name, (url, value) in selected_cache.items():
        if url not in cache or cache[url].get('path') != name or value.get('tse_idg') != rows[name]['tse_idg']:
            raise ValueError('pending_cache_mismatch')
        cache[url] = value
    checkpoint['target-state.json'] = canonical(cache)
    checkpoint['state-meta.json'] = original['state']['state-meta.json']
    # Prevent acknowledging unselected global parser/bootstrap changes.
    if original['state']['state-meta.json'] != original['pending']['state-meta.json']:
        raise ValueError('checkpoint_schema_requires_review')
    for label, path in [('baseline', baseline), ('stage', stage), ('state', state), ('pending', pending)]:
        if tree(path) != original[label]:
            raise ValueError('input_changed')
    if marker.read_bytes() != marker_raw:
        raise ValueError('baseline_changed')
    plan = {'schema_version': 1, 'base_snapshot_id': sid, 'marker_sha256': digest(marker_raw),
            'selected': sorted(include), 'retained_stage_targets': sorted(original['stage'].keys() - META - set(include)),
            'candidate_transitions': transitions, 'input_hashes': {label: hashes(value) for label, value in original.items()},
            'candidate_review_required': sorted(name for name, items in transitions.items() if any(item['kind'] in {'removed', 'added'} for item in items)),
            'candidate_hashes': hashes(result), 'checkpoint_hashes': hashes(checkpoint),
            'remote_writes_authorized': False, 'ftp_isolation_approved': False}
    output.mkdir(parents=True, exist_ok=False)
    for directory, values in [('candidate', result), ('checkpoint', checkpoint)]:
        for name, raw in values.items():
            path = output/directory/name; path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(raw)
    (output/'recovery-plan.json').write_bytes(canonical(plan))
    return plan


def assert_recovery_resolved(queue_root: Path):
    if (queue_root/'recovery-hold.json').exists():
        raise ValueError('recovery_residual_targets_require_review')


def verify(package: Path):
    plan = parse((package/'recovery-plan.json').read_bytes())
    candidate, checkpoint = tree(package/'candidate'), tree(package/'checkpoint')
    if hashes(candidate) != plan['candidate_hashes'] or hashes(checkpoint) != plan['checkpoint_hashes']:
        raise ValueError('recovery_package_changed')
    if set(checkpoint) != STATE or not isinstance(plan.get('base_snapshot_id'), str) or not re.fullmatch('[a-f0-9]{64}', plan['base_snapshot_id']):
        raise ValueError('invalid_recovery_plan')
    version = parse(candidate['version.json']); rows = entries(parse(candidate['manifest.json']))
    validate_release(candidate, version['environment'], next(iter(rows.values()))['round'])
    if any(checkpoint[name] != candidate[name] for name in META):
        raise ValueError('checkpoint_mismatch')
    return plan


def queue(root: Path, package: Path, reviewed_plan_sha256: str):
    # This operation is NOT part of offline preparation or incident inspection.
    from .ftp_safety import validate_runner_environment
    validate_runner_environment(os.environ)
    if root.resolve() != Path(os.environ['LIVE_PUBLISH_STATE_DIR']).resolve():
        raise ValueError('live_root_mismatch')
    plan = verify(package)
    if not re.fullmatch('[a-f0-9]{64}', reviewed_plan_sha256) or digest((package/'recovery-plan.json').read_bytes()) != reviewed_plan_sha256:
        raise ValueError('specific_recovery_plan_review_required')
    from .ftp_baseline import lock
    from .ftp_live_runner import save
    q = root/'ftp-queue'
    if not q.is_dir() or q.is_symlink():
        raise ValueError('baseline_adoption_required')
    with lock(q/'runner.lock'):
        if (q/'current.json').exists():
            raise ValueError('delivery_in_flight')
        assert_recovery_resolved(q)
        if parse((q/'confirmed.json').read_bytes()).get('snapshot_id') != plan['base_snapshot_id']:
            raise ValueError('baseline_conflict')
        for name in ('state', 'pending', 'stage'):
            if hashes(tree(root/name)) != plan['input_hashes'][name]:
                raise ValueError('live_changed_requires_new_plan')
        delivery = freeze(package/'candidate', q/'deliveries', key_from_file(os.environ['ELECTION_HMAC_KEY_FILE']), plan['base_snapshot_id'])
        frozen = q/('state-'+delivery.name)
        if frozen.exists():
            raise ValueError('orphan_state_requires_review')
        shutil.copytree(package/'checkpoint', frozen)
        if plan['retained_stage_targets']:
            save(q/'recovery-hold.json', {'delivery_id': delivery.name,
                 'retained_stage_targets': plan['retained_stage_targets'],
                 'input_hashes': {name: plan['input_hashes'][name] for name in ('pending', 'stage')},
                 'reason': 'retained_targets_require_supervised_reconciliation'})
        save(q/'current.json', {'id': delivery.name, 'recovery_plan_sha256': digest((package/'recovery-plan.json').read_bytes())})
        return {'status': 'queued', 'delivery_id': delivery.name}


def verify_public(delivery: Path, control_url: str, receipt: dict, opener=None):
    """Read all 137 public results before acknowledging supervised recovery.

    Uses frozen descriptor hashes, no upload or HMAC in GETs. Redirects are
    refused; selection is checked both before and after the immutable reads.
    """
    parsed = urlsplit(control_url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('https_required')
    raw = (delivery/'delivery.json').read_bytes()
    if digest(raw) != delivery.name:
        raise ValueError('delivery_changed')
    descriptor = parse(raw)
    if set(descriptor['files']) != set(targets()) | META:
        raise ValueError('complete_recovery_required')
    if receipt.get('status') != 'published' or receipt.get('delivery_id') != delivery.name or receipt.get('snapshot_id') != delivery.name:
        raise ValueError('invalid_receipt')
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = opener or build_opener(NoRedirect)
    base = f'{parsed.scheme}://{parsed.netloc}/data'
    def read(relative, limit):
        request = Request(base+'/'+relative+'?recovery='+delivery.name+'&nonce='+secrets.token_hex(8),
                          headers={'Accept': 'application/json', 'Cache-Control': 'no-cache'}, method='GET')
        with opener.open(request, timeout=30) as response:
            if response.status != 200 or response.geturl() != request.full_url:
                raise ValueError('unexpected_public_response')
            value = response.read(limit+1)
        if len(value) > limit:
            raise ValueError('public_file_too_large')
        return value
    before = parse(read('version.json', 65536))
    if before.get('snapshot_id') != delivery.name or before.get('delivery_id') != delivery.name:
        raise ValueError('public_selection_mismatch')
    for name, entry in descriptor['files'].items():
        value = read('releases/'+delivery.name+'/'+name, entry['size'])
        if len(value) != entry['size'] or digest(value) != entry['sha256']:
            raise ValueError('public_checksum_mismatch')
    after = parse(read('version.json', 65536))
    if after != before:
        raise ValueError('public_selection_changed')
    return {'status': 'verified', 'snapshot_id': delivery.name, 'results': 137, 'files': 140}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    prep = sub.add_parser('prepare')
    for name in ('baseline', 'marker', 'stage', 'state', 'pending', 'output'):
        prep.add_argument('--'+name, type=Path, required=True)
    prep.add_argument('--include', action='append', required=True)
    check = sub.add_parser('verify'); check.add_argument('--package', type=Path, required=True)
    queued = sub.add_parser('queue'); queued.add_argument('--package', type=Path, required=True); queued.add_argument('--root', type=Path, required=True)
    queued.add_argument('--reviewed-plan-sha256', required=True)
    args = vars(parser.parse_args()); operation = args.pop('operation')
    try:
        value = prepare(**args) if operation == 'prepare' else verify(**args) if operation == 'verify' else queue(**args)
        print(json.dumps({'status': 'prepared' if operation == 'prepare' else 'verified' if operation == 'verify' else value['status'],
                          'base_snapshot_id': value.get('base_snapshot_id'), 'selected': value.get('selected'), 'delivery_id': value.get('delivery_id')}))
    except (ValueError, KeyError, OSError, TypeError) as error:
        code = str(error) if isinstance(error, ValueError) and re.fullmatch('[a-z_]+', str(error)) else type(error).__name__
        print(json.dumps({'status': 'failed', 'reason': code}));raise SystemExit(1)


if __name__ == '__main__':
    main()
