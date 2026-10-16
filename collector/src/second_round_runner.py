"""Dedicated app01 second-round pipeline and operational CLI. Never uses a DB."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import time

from deploy.frontend import error_report
from .election_release import canonical, parse, tree
from .second_round_collection import AwaitingData, CachedClient, RateLimited, discover, build_values, write_values
from .second_round_publish import Publisher, STATE, connect, describe, load, local_lock, now, save
from .second_round_metrics import measure, policy, storage, history
from .election_release import digest


def credentials():
    directory = os.environ.get('CREDENTIALS_DIRECTORY')
    if directory:
        # Read systemd's protected ephemeral copy of the existing secret file.
        import shlex
        for line in (Path(directory) / 'ftp.env').read_text().splitlines():
            if not line.strip() or line.lstrip().startswith('#'): continue
            key, sep, value = line.partition('=')
            if key not in {'LOCAWEB_FTP_HOST', 'LOCAWEB_FTP_USER', 'LOCAWEB_FTP_PASSWORD', 'LOCAWEB_FTP_PORT'}: continue
            parts = shlex.split(value, comments=False)
            if sep and len(parts) == 1: os.environ[key] = parts[0]
    if os.environ.get('LOCAWEB_FTP_PORT', '21') != '21':
        raise ValueError('plain_ftp_port_21_required')


def proof(values, client):
    # Retain official source evidence outside the public package and bind hashes.
    return {'schema': 1, 'source': 'https://resultados.tse.jus.br', 'environment': 'oficial',
            'cycle': 'ele2026', 'round': 2, 'snapshot_id': describe(values)['snapshot_id'],
            'records': client.records, 'collected_at': now()}


def verify_proof(package):
    evidence = load(Path(package).parent / 'source-proof.json')
    if not evidence or evidence.get('source') != 'https://resultados.tse.jus.br' or evidence.get('round') != 2:
        raise ValueError('missing_official_second_round_proof')
    from .tse_client import TseFetchResult
    from .second_round_collection import official_url
    class Replay:
        def fetch_json(self, url):
            official_url(url)
            record = evidence['records'][url]
            if record['url'] != url or record['payload'].get('f') != 'o':
                raise ValueError('invalid_official_second_round_proof')
            if record.get('payload_sha256') and record['payload_sha256'] != digest(canonical(record['payload'])):
                raise ValueError('corrupt_official_second_round_proof')
            return TseFetchResult(url, 200, None, None, record['sha256'], record['payload'])
    replay = Replay()
    actual = tree(Path(package))
    expected = build_values(replay, discover(replay), include_portal='portal.json' in actual)
    if actual != expected or evidence['snapshot_id'] != describe(actual)['snapshot_id']:
        raise ValueError('second_round_source_package_mismatch')
    return describe(actual)


def cycle(state, *, dry_run=False, client=None, connector=connect):
    health_path = state / 'health.json'
    previous = load(health_path) or {}
    if previous.get('retry_after_epoch', 0) > time.time():
        return {**previous, 'status': 'backoff', 'checked_at': now()}
    transport = None
    client = client or CachedClient(state / 'http-cache')
    metrics = getattr(client, 'metrics', {})
    started, cycle_started_at = time.monotonic(), now()
    result = None
    observation, step = {}, 'storage'
    try:
        state.mkdir(parents=True, exist_ok=True)
        if not dry_run:
            step = 'recovery'
            transport = connector()
            publisher = Publisher(transport, state)
            publisher.metrics = metrics
            transport.metrics = metrics
            with measure(metrics, 'recovery'):
                publisher.recover()  # Pending work is always settled before new collection.
        storage(state)
        step = 'collection'
        with measure(metrics, 'collection'):
            plans = discover(client)
            values = build_values(client, plans)
            # Totalization may advance while UFs are read. Each response is an
            # official snapshot; changing election/target inventory is different
            # and must not activate a package assembled from two inventories.
            after = discover(client)
            before_targets = {(t.election_code, t.scope_code, t.office_code, t.url) for p in plans for t in p.targets}
            after_targets = {(t.election_code, t.scope_code, t.office_code, t.url) for p in after for t in p.targets}
            if before_targets != after_targets:
                raise ValueError('official_inventory_changed_during_collection')
        source_success_at = now()
        step = 'validation'
        with measure(metrics, 'validation'):
            verified = describe(values)
        fingerprint = digest(canonical({url: record['sha256'] for url, record in client.records.items()}))
        cadence = policy(values, previous, fingerprint)
        observation = {**cadence, 'last_source_success_at': source_success_at,
                       'observed_snapshot_id': verified['snapshot_id'],
                       'observed_snapshot_since': ((previous.get('observed_snapshot_since') or now())
                            if previous.get('observed_snapshot_id') == verified['snapshot_id'] else now()),
                       'official_generated_at': verified['descriptor']['generated_at']}
        checkpoint = load(state / 'checkpoint.json') or {}
        step = 'publication'
        with measure(metrics, 'publication'):
            if not dry_run and checkpoint.get('snapshot_id') == verified['snapshot_id']:
                # Keep verified values in memory: no duplicate package/proof/cycle.
                result = publisher.publish(values=values, baseline_checked=True)
            else:
                destination = state / 'cycles' / verified['snapshot_id'][:32] / 'package'
                with measure(metrics, 'snapshot'):
                    if destination.exists():
                        if tree(destination) != values: raise ValueError('round2_cycle_hash_collision')
                    else:
                        write_values(destination, values)
                        save(destination.parent / 'source-proof.json', proof(values, client))
                    verify_proof(destination)
                result = ({'status': 'verified_dry_run', 'snapshot_id': verified['snapshot_id']}
                          if dry_run else publisher.publish(destination, baseline_checked=True))
        result.update(collected_at=now(), round=2, failures=0,
                      last_source_success_at=source_success_at,
                      last_publication_at=(load(state / 'checkpoint.json') or {}).get('verified_at'),
                      last_activation_at=(load(state / 'checkpoint.json') or {}).get('activation_completed_at'),
                      https_marker_observed_at=(load(state / 'checkpoint.json') or {}).get('https_marker_observed_at'),
                      official_generated_at=verified['descriptor']['generated_at'],
                      publication_phase=verified['publication_phase'],
                      official_files_checked=len(client.records),
                      ea20_files_checked=sum(url.endswith('-u.json') for url in client.records),
                      **cadence, retry_after_epoch=time.time() + cadence['poll_after_seconds'])
        result.update(observation)
        save(health_path, result)
        return result
    except AwaitingData:
        result = {**previous, 'status': 'awaiting_official_round_two_data', 'round': 2, 'checked_at': now(),
                  'last_source_success_at': now(),
                  'election_state': previous.get('election_state', 'awaiting_official_data'),
                  'failures': 0, 'retry_after_epoch': time.time() + 120,
                  'official_files_checked': len(client.records),
                  'ea20_files_checked': sum(url.endswith('-u.json') for url in client.records)}
        if previous.get('publication_phase') == 'counting': result['status'] = 'official_data_temporarily_unavailable'
        save(health_path, result)
        return result
    except Exception as error:
        import ftplib
        if step == 'recovery' and transport is None and isinstance(error, (OSError, EOFError, ftplib.Error)):
            metrics['ftp_failures'] = metrics.get('ftp_failures', 0) + 1
        failures = previous.get('failures', 0) + 1
        delay = error.seconds if isinstance(error, RateLimited) else min(3600, 60 * 2 ** min(failures, 6))
        result = {**previous, **observation, 'status': 'rate_limited' if isinstance(error, RateLimited) else 'failed',
                  'round': 2, 'checked_at': now(), 'failures': failures,
                  'failure_stage': step,
                  'retry_after_epoch': time.time() + delay, **error_report(error)}
        import re
        if isinstance(error, (ValueError, RuntimeError)) and re.fullmatch('[a-z][a-z0-9_]{0,100}', str(error)):
            result['failure_code'] = str(error)
        save(health_path, result)
        if isinstance(error, RateLimited): return result
        raise
    finally:
        if result is not None:
            result.update(cycle_started_at=cycle_started_at, cycle_finished_at=now(),
                          cycle_seconds=round(time.monotonic() - started, 6), metrics=metrics,
                          http_429_total=previous.get('http_429_total', 0) + getattr(client, 'http_429', 0),
                          public_http_429_total=previous.get('public_http_429_total', 0) + metrics.get('public_http_429', 0),
                          ftp_failures_total=previous.get('ftp_failures_total', 0) + metrics.get('ftp_failures', 0),
                          failed_cycles_total=previous.get('failed_cycles_total', 0) + int(result.get('status') == 'failed'))
            save(health_path, result)
            history(state, result)
        if transport: transport.ftp.close()


def legacy_rollback(publisher, state):
    """Restore the legacy representation of the SAME currently verified results.

    This is a code-rollback compatibility operation, never an election rollback.
    It cannot substitute older votes, acquire another owner's lock or bypass proof.
    """
    publisher.recover()
    marker = publisher.marker()
    if not marker: raise ValueError('legacy_rollback_requires_verified_publication')
    remote, active = publisher.release(marker)
    if 'portal.json' not in remote: return {'status': 'already_legacy_compatible', 'snapshot_id': active['snapshot_id']}
    original = None
    for path in (state / 'journals').glob('*.json'):
        job = load(path)
        if job.get('snapshot_id') != active['snapshot_id']: continue
        candidate = Path(job['package'])
        if not candidate.resolve().is_relative_to((state / 'cycles').resolve()): continue
        if verify_proof(candidate)['snapshot_id'] == active['snapshot_id'] and tree(candidate) == remote:
            original = candidate; break
    if original is None: raise ValueError('legacy_rollback_requires_original_official_proof')
    values = {name: raw for name, raw in remote.items() if name != 'portal.json'}
    sid = describe(values)['snapshot_id']
    destination = state / 'cycles' / sid[:32] / 'package'
    if destination.exists():
        if tree(destination) != values: raise ValueError('round2_cycle_hash_collision')
    else:
        write_values(destination, values)
        evidence = load(original.parent / 'source-proof.json')
        save(destination.parent / 'source-proof.json', {**evidence, 'snapshot_id': sid,
             'derived_from_snapshot': active['snapshot_id']})
    verify_proof(destination)
    return publisher.publish(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['cycle', 'status', 'reconcile', 'recover', 'publish', 'verify', 'health', 'legacy-rollback'])
    parser.add_argument('--state', type=Path, default=Path(os.environ.get('ELECTION_ROUND2_STATE_DIR', STATE)))
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        if not args.state.is_absolute() or args.state.is_symlink(): raise ValueError('unsafe_round_two_state')
        if args.operation in {'verify', 'publish'} and not args.directory:
            raise ValueError('second_round_package_required')
        credentials()
        with local_lock(args.state):
            if args.operation == 'verify': result = verify_proof(args.directory)
            elif args.operation == 'health':
                result = load(args.state / 'health.json') or {}
                at = result.get('checked_at') or result.get('collected_at')
                if not at or (datetime.now(timezone.utc) - datetime.fromisoformat(at)).total_seconds() > 900:
                    raise RuntimeError('second_round_health_stale')
                if result.get('status') == 'failed': raise RuntimeError('second_round_health_failed')
            elif args.operation == 'cycle': result = cycle(args.state, dry_run=args.dry_run)
            else:
                transport = connect()
                try:
                    publisher = Publisher(transport, args.state)
                    if args.operation == 'legacy-rollback': result = legacy_rollback(publisher, args.state)
                    elif args.operation == 'publish':
                        verify_proof(args.directory)
                        result = publisher.publish(args.directory)
                    else: result = getattr(publisher, args.operation)()
                finally: transport.ftp.close()
        if args.operation != 'cycle' or result.get('status') != 'backoff':
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except Exception as error:
        if args.operation == 'cycle' and isinstance(error, RuntimeError) and str(error) == 'second_round_writer_busy':
            print(json.dumps({'status': 'writer_busy_cycle_deferred', 'round': 2}))
            return 0
        print(json.dumps({'status': 'failed', 'round': 2, **error_report(error)}, sort_keys=True))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
