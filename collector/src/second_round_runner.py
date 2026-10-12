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
from .second_round_collection import AwaitingData, CachedClient, RateLimited, collect, discover, build_values
from .second_round_publish import Publisher, STATE, connect, describe, load, local_lock, now, save


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
            return TseFetchResult(url, 200, None, None, record['sha256'], record['payload'])
    replay = Replay()
    expected = build_values(replay, discover(replay))
    actual = tree(Path(package))
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
    try:
        if not dry_run:
            transport = connector()
            publisher = Publisher(transport, state)
            publisher.recover()  # Pending work is always settled before new collection.
        destination = state / 'cycles' / secrets.token_hex(16) / 'package'
        values = collect(destination, client)
        save(destination.parent / 'source-proof.json', proof(values, client))
        verify_proof(destination)
        verified = describe(values)
        result = ({'status': 'verified_dry_run', 'snapshot_id': verified['snapshot_id']}
                  if dry_run else publisher.publish(destination))
        result.update(collected_at=now(), round=2, failures=0,
                      publication_phase=verified['publication_phase'],
                      official_files_checked=len(client.records),
                      ea20_files_checked=sum(url.endswith('-u.json') for url in client.records),
                      retry_after_epoch=time.time() + 300 if verified['publication_phase'] == 'candidate_roster' else 0)
        save(health_path, result)
        return result
    except AwaitingData:
        result = {'status': 'awaiting_official_round_two_data', 'round': 2, 'checked_at': now(),
                  'failures': 0, 'retry_after_epoch': time.time() + 300,
                  'official_files_checked': len(client.records),
                  'ea20_files_checked': sum(url.endswith('-u.json') for url in client.records)}
        save(health_path, result)
        return result
    except Exception as error:
        failures = previous.get('failures', 0) + 1
        delay = error.seconds if isinstance(error, RateLimited) else min(3600, 60 * 2 ** min(failures, 6))
        result = {'status': 'rate_limited' if isinstance(error, RateLimited) else 'failed',
                  'round': 2, 'checked_at': now(), 'failures': failures,
                  'retry_after_epoch': time.time() + delay, **error_report(error)}
        save(health_path, result)
        if isinstance(error, RateLimited): return result
        raise
    finally:
        if transport: transport.ftp.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['cycle', 'status', 'reconcile', 'recover', 'publish', 'verify', 'health'])
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
                    if args.operation == 'publish':
                        verify_proof(args.directory)
                        result = publisher.publish(args.directory)
                    else: result = getattr(publisher, args.operation)()
                finally: transport.ftp.close()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except Exception as error:
        print(json.dumps({'status': 'failed', 'round': 2, **error_report(error)}, sort_keys=True))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
