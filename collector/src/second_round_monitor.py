"""Round-two monitoring, public freshness and deduplicated operational alerts."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .election_release import canonical, parse
from .second_round_publish import SITE, STATE, connect, load, now, save
from deploy.frontend import error_report


def age(stamp, epoch=None):
    if not stamp: return None
    return max(0, (datetime.now(timezone.utc).timestamp() if epoch is None else epoch) - datetime.fromisoformat(stamp).timestamp())


def assess(health, checkpoint, pending, marker, *, timer_active=True, epoch=None, storage=None):
    storage = storage or {}
    source_age = age(health.get('last_source_success_at') or health.get('collected_at'), epoch)
    phase = health.get('election_state', 'official_data_available' if checkpoint else 'awaiting_official_data')
    budget = 600 if phase in {'awaiting_official_data', 'official_data_available', 'counting_finished'} else 180
    pending_age = age(pending.get('created_at'), epoch) if pending else None
    reasons = []
    state = 'awaiting_results' if phase in {'awaiting_official_data', 'official_data_available'} else 'current'
    if pending:
        state = 'updating'
        if pending_age is None or pending_age > 600: reasons.append('recovery_required')
        if pending.get('phase') not in {'prepared', 'verified', 'committed'}: reasons.append('unknown_transaction')
    if not timer_active: reasons.append('collector_timer_inactive')
    if health.get('failure_code') in {'orphan_lock_without_trusted_journal', 'unknown_second_round_lock_owner'} and health.get('status') == 'failed':
        reasons.append('recovery_required')
    if health.get('status') == 'failed':
        if health.get('failure_code') == 'second_round_roster_change_requires_review': reasons.append('review_required')
        elif health.get('failures', 0) >= 2:
            reasons.append('publication_failed' if health.get('failure_stage') in {'publication', 'recovery'} else 'collector_failed')
    if checkpoint and not marker: reasons.append('publication_unavailable')
    if marker and checkpoint and marker.get('snapshot_id') != checkpoint.get('snapshot_id'):
        known = pending and marker.get('snapshot_id') == pending.get('snapshot_id')
        if not known: reasons.append('checkpoint_publication_inconsistency')
    if source_age is None:
        if health.get('status') not in {'awaiting_official_round_two_data'}: reasons.append('collection_unavailable')
    elif source_age > budget: reasons.append('collection_late')
    if (health.get('observed_snapshot_id') and health['observed_snapshot_id'] != checkpoint.get('snapshot_id')
            and (age(health.get('observed_snapshot_since') or health.get('last_official_change_at'), epoch) or 0) > 180):
        reasons.append('publication_late')
    if storage.get('alert'): reasons.append('storage_warning')
    if health.get('status') in {'failed', 'rate_limited', 'official_data_temporarily_unavailable'} and not reasons: state = 'retrying'
    if reasons: state = reasons[0]
    return {'schema_version': 1, 'round': 2, 'environment': 'oficial', 'checked_at': now(),
            'state': state, 'election_state': phase, 'reasons': sorted(set(reasons)),
            'last_source_success_at': health.get('last_source_success_at') or health.get('collected_at'),
            'last_official_change_at': health.get('last_official_change_at'),
            'official_generated_at': health.get('official_generated_at'),
            'last_publication_at': checkpoint.get('verified_at'),
            'last_activation_at': checkpoint.get('activation_completed_at'),
            'https_marker_observed_at': checkpoint.get('https_marker_observed_at'),
            'snapshot_id': marker.get('snapshot_id') if marker else None,
            'source_age_seconds': source_age, 'source_stale_after_seconds': budget,
            'snapshot_age_seconds': age(checkpoint.get('verified_at'), epoch),
            'cycle_seconds': health.get('cycle_seconds'), 'failures': health.get('failures', 0),
            'failed_cycles_total': health.get('failed_cycles_total', 0),
            'http_429_total': health.get('http_429_total', 0),
            'public_http_429_total': health.get('public_http_429_total', 0),
            'ftp_failures_total': health.get('ftp_failures_total', 0),
            'timer_active': timer_active, 'pending': bool(pending), 'pending_age_seconds': pending_age,
            'cycle_bytes': storage.get('cycle_bytes'), 'free_bytes': storage.get('free_bytes'),
            'cycle_count': storage.get('cycle_count'), 'storage_sampled_at': storage.get('checked_at'),
            'growth_bytes_per_hour': storage.get('growth_bytes_per_hour', 0),
            'metrics': health.get('metrics', {})}


def publish_status(transport, state, status, *, public_reader=None):
    """Auxiliary file only; durable journal owns any interrupted .upload."""
    path, journal = SITE + '/status.json', state / 'status-pending.json'
    pending = load(journal)
    if pending:
        raw = bytes.fromhex(pending['raw'])
        before = bytes.fromhex(pending['before']) if pending['before'] else None
        actual = transport.read(path, optional=True)
        if actual not in (before, raw): raise RuntimeError('unknown_public_status_change')
        temporary = transport.read(path + '.upload', optional=True)
        if temporary is not None:
            if temporary == raw:
                if actual != raw: transport.ftp.rename(path + '.upload', path)
            else:
                # Only the pre-recorded monitor operation owns this temporary.
                transport.ftp.delete(path + '.upload')
        if transport.read(path, optional=True) != raw: transport.put(path, raw, replace=True)
        if transport.read(path) != raw: raise RuntimeError('public_status_integrity_error')
        if public_reader and public_reader('status.json') != raw: raise RuntimeError('public_status_https_mismatch')
        save(journal, None)
    old = transport.read(path, optional=True)
    if transport.read(path + '.upload', optional=True) is not None: raise RuntimeError('unknown_public_status_temporary')
    raw = canonical(status)
    save(journal, {'raw': raw.hex(), 'before': old.hex() if old else None, 'created_at': now()})
    transport.put(path, raw, replace=True)
    if transport.read(path) != raw: raise RuntimeError('public_status_integrity_error')
    if public_reader and public_reader('status.json') != raw: raise RuntimeError('public_status_https_mismatch')
    save(journal, None)


def notify(status, *, test=False, opener=None):
    endpoint = os.environ.get('ELECTION_ROUND2_NTFY_URL')
    if not endpoint: return {'configured': False, 'sent': False}
    from urllib.parse import urlsplit
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('invalid_round2_notification_endpoint')
    title = 'Eleicoes 2026: teste operacional' if test else 'Eleicoes 2026: segundo turno'
    text = ('Ensaio controlado de alerta. Dados eleitorais preservados.' if test else
            'Estado: ' + status['state'] + '; motivos: ' + ', '.join(status['reasons']) +
            '; ultima consulta oficial: ' + str(status['last_source_success_at']))
    headers = {'Title': title, 'Tags': 'test_tube' if test else ('warning' if status['reasons'] else 'white_check_mark'), 'Content-Type': 'text/plain; charset=utf-8'}
    token = os.environ.get('ELECTION_ROUND2_NTFY_TOKEN')
    if token: headers['Authorization'] = 'Bearer ' + token
    if opener is None:
        from urllib.request import build_opener
        from deploy.frontend import NoRedirect
        opener = build_opener(NoRedirect).open
    with opener(Request(endpoint, data=text.encode(), headers=headers, method='POST'), timeout=15) as response:
        reply = json.loads(response.read(65536))
        if not reply.get('id'): raise RuntimeError('notification_unconfirmed')
        return {'configured': True, 'sent': True, 'message_id': reply['id']}


def run(state, output, *, timer_active=None, transport=None, public_reader=None, test_alert=False, transport_error=None):
    health, checkpoint = load(state / 'health.json') or {}, load(state / 'checkpoint.json') or {}
    pending = load(state / 'pending.json')
    if timer_active is None:
        timer_active = subprocess.run(['systemctl', 'is-active', '--quiet', 'election-round2.timer']).returncode == 0
    marker_error = None
    try:
        if public_reader is None:
            from .second_round_publish import http_read
            public_reader = http_read
        raw = public_reader('version.json')
        marker = parse(raw) if raw else None
        if marker and (marker.get('round') != 2 or marker.get('environment') != 'oficial'): raise ValueError('invalid_monitor_marker')
    except Exception as error:
        marker, marker_error = None, error_report(error)
    after_checkpoint = load(state / 'checkpoint.json') or {}
    if after_checkpoint != checkpoint:
        checkpoint, pending = after_checkpoint, load(state / 'pending.json')
        try:
            raw = public_reader('version.json')
            marker = parse(raw) if raw else None
        except Exception as error:
            marker, marker_error = None, error_report(error)
    measured_storage = load(state / 'storage.json') or {}
    import shutil
    measured_storage['free_bytes'] = shutil.disk_usage(state).free
    measured_storage['alert'] = (measured_storage.get('alert', False) or measured_storage['free_bytes'] <
        int(os.environ.get('ELECTION_ROUND2_MIN_FREE_BYTES', str(2 * 1024 ** 3))) * 1.5)
    status = assess(health, checkpoint, pending, marker, timer_active=timer_active, storage=measured_storage)
    if marker_error: status['public_read_error'] = marker_error
    if transport_error:
        status['ftp_error'] = transport_error
        status['reasons'].append('ftp_unavailable'); status['state'] = 'ftp_unavailable'
    # A public freshness document is an explicit contract. Operational fields
    # (including future diagnostics) belong only in the local Zabbix snapshot.
    public_keys = {'schema_version', 'round', 'environment', 'checked_at', 'state',
                   'election_state', 'snapshot_id', 'last_source_success_at',
                   'last_official_change_at', 'last_publication_at',
                   'last_activation_at', 'https_marker_observed_at',
                   'official_generated_at', 'source_stale_after_seconds'}
    public = {key: value for key, value in status.items() if key in public_keys}
    if transport is not None:
        try: publish_status(transport, state, public, public_reader=public_reader)
        except Exception as error:
            status['status_write_error'] = error_report(error)
            status['reasons'].append('public_status_unavailable')
    previous = load(state / 'monitor-alert.json') or {}
    signature = '|'.join(status['reasons'])
    streak = previous.get('streak', 0) + 1 if previous.get('signature') == signature else 1
    alert = {'signature': signature, 'streak': streak, 'sent_at': previous.get('sent_at') if previous.get('signature') == signature else None}
    try:
        if test_alert:
            status['notification'] = notify(status, test=True)
        elif signature and streak >= 2 and (not alert['sent_at'] or age(alert['sent_at']) > 3600):
            status['notification'] = notify(status)
            if status['notification']['sent']: alert['sent_at'] = now()
        elif not signature and previous.get('signature') and previous.get('sent_at'):
            status['notification'] = notify(status)
        else: status['notification'] = {'configured': bool(os.environ.get('ELECTION_ROUND2_NTFY_URL')), 'sent': False}
    except Exception as error:
        status['notification'] = {'configured': True, 'sent': False, **error_report(error)}
    save(state / 'monitor-alert.json', alert)
    # Public representation intentionally excludes notification routing/state and
    # internal paths, owners, exception messages and infrastructure endpoints.
    save(output, status, mode=0o644)  # Sanitized, read-only Zabbix snapshot.
    return status


def main():
    from .second_round_runner import credentials
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state', type=Path, default=Path(STATE))
    p.add_argument('--output', type=Path, default=Path('/var/lib/election-round2-monitor/status.json'))
    p.add_argument('--test-alert', action='store_true')
    args = p.parse_args()
    args.state.mkdir(parents=True, exist_ok=True)
    with (args.state / 'monitor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        credentials()
        transport, failure = None, None
        try: transport = connect()
        except Exception as error: failure = error_report(error)
        try: status = run(args.state, args.output, transport=transport, transport_error=failure, test_alert=args.test_alert)
        finally:
            if transport: transport.ftp.close()
    print(json.dumps({key: value for key, value in status.items() if key != 'metrics'}, sort_keys=True))
    return 0


if __name__ == '__main__': raise SystemExit(main())
