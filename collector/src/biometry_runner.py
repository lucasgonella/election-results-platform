"""Isolated, resumable official BU collection for President/2026/round two."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import shutil
import signal
import threading
import time
from urllib.parse import urlsplit

import requests

from .biometry import ELECTION, SOURCE, UFS, aggregate, canonical, database, meta, now, set_meta, sha, store
from .second_round_publish import local_lock

CONFIG = 'https://resultados.tse.jus.br/oficial/comum/config/ele-c.json'
NATIONAL = 'https://resultados.tse.jus.br/oficial/ele2026/6258/dados/br/br-c0001-e006258-u.json'


class Throttled(RuntimeError):
    def __init__(self, seconds):
        super().__init__('biometry_source_rate_limited')
        self.seconds = seconds


class OfficialHTTP:
    def __init__(self, rps=4):
        # TSE documents 100 requests/IP/second. Keep this independent
        # collector below one quarter, leaving room for existing pipelines.
        if not 0 < rps <= 25:
            raise ValueError('biometry_invalid_request_rate')
        self.interval, self.next_request = 1 / rps, 0
        self.lock, self.local = threading.Lock(), threading.local()
        self.cooldown = 0

    def get(self, url, maximum=2 * 1024 * 1024):
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.netloc != 'resultados.tse.jus.br'
                or parsed.query or parsed.fragment or '..' in parsed.path.split('/')
                or not parsed.path.startswith('/oficial/')):
            raise ValueError('biometry_non_official_source')
        if not hasattr(self.local, 'session'):
            self.local.session = requests.Session()
        for attempt in range(3):
            with self.lock:
                if self.cooldown > time.time():
                    raise Throttled(self.cooldown - time.time())
                delay = max(0, self.next_request - time.monotonic())
                if delay:
                    time.sleep(delay)
                self.next_request = time.monotonic() + self.interval
            try:
                with self.local.session.get(url, timeout=(10, 30), allow_redirects=False, stream=True) as response:
                    if response.status_code == 429:
                        try:
                            seconds = max(600, int(response.headers.get('Retry-After', '600')))
                        except ValueError:
                            seconds = 600
                        self.cooldown = time.time() + seconds
                        raise Throttled(seconds)
                    if response.status_code in {408, 500, 502, 503, 504}:
                        response.raise_for_status()
                    if response.status_code != 200:
                        raise ValueError('biometry_official_http_' + str(response.status_code))
                    raw = bytearray()
                    for chunk in response.iter_content(65536):
                        raw.extend(chunk)
                        if len(raw) > maximum:
                            raise ValueError('biometry_oversized_official_file')
                    return bytes(raw)
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)

    def json(self, url, maximum=32 * 1024 * 1024):
        raw = self.get(url, maximum)
        value = json.loads(raw.decode('utf-8-sig'))
        if not isinstance(value, dict) or value.get('f') != 'o':
            raise ValueError('biometry_non_official_payload')
        return value, sha(raw)


def initialize(db, client):
    from .municipal_collection import election
    config, _ = client.json(CONFIG)
    selected = election(config, 2)
    if selected['code'] != ELECTION['code'] or int(selected['pleito']) != ELECTION['pleito']:
        raise ValueError('biometry_wrong_official_configuration')
    national, national_sha = client.json(NATIONAL)
    if (national.get('ele') != '6258' or national.get('t') != '2'
            or national.get('cdabr') != 'br' or national['carg'][0]['cd'] != '1'):
        raise ValueError('biometry_wrong_national_reference')
    inventories = {}
    for index, uf in enumerate(UFS):
        url = f'{SOURCE}/config/{uf}/{uf}-p003221-cs.json'
        value, fingerprint = client.json(url)
        if str(value.get('cdp')) != '3221' or len(value.get('abr', [])) != 1 or value['abr'][0]['cd'] != uf:
            raise ValueError('biometry_invalid_section_inventory')
        state = value['abr'][0]
        seen, count = set(), 0
        for municipality in state['mu']:
            city = municipality['cd']
            if not re.fullmatch(r'\d{5}', city) or not municipality.get('nm'):
                raise ValueError('biometry_invalid_municipality')
            for zone in municipality['zon']:
                if not re.fullmatch(r'\d{4}', zone['cd']):
                    raise ValueError('biometry_invalid_zone')
                for section in zone['sec']:
                    number = section['ns']
                    if not re.fullmatch(r'\d{4}', number):
                        raise ValueError('biometry_invalid_section')
                    # Aggregated sections have no independent BU. Their electors
                    # are already counted by the primary section's BU.
                    if section.get('nsp') and str(section['nsp']).zfill(4) != number:
                        continue
                    key = city, zone['cd'], number
                    if key in seen:
                        raise ValueError('biometry_duplicate_section_inventory')
                    seen.add(key)
                    stamp = sha(canonical(section))
                    db.execute('''INSERT INTO sections(uf,municipality,zone,section,name,stamp,priority)
                        VALUES(?,?,?,?,?,?,?) ON CONFLICT(uf,municipality,zone,section) DO UPDATE SET
                        name=excluded.name,stamp=excluded.stamp,
                        retry_at=CASE WHEN sections.stamp=excluded.stamp THEN sections.retry_at ELSE 0 END,
                        attempts=CASE WHEN sections.stamp=excluded.stamp THEN sections.attempts ELSE 0 END''',
                        (uf, city, zone['cd'], number, municipality['nm'], stamp, count * len(UFS) + index))
                    count += 1
        inventories[uf] = {'name': state.get('ds', uf.upper()), 'sections': count,
                           'url': url, 'sha256': fingerprint}
        db.commit()
    expected = int(national['s']['ts'])
    if sum(value['sections'] for value in inventories.values()) != expected:
        raise ValueError('biometry_section_inventory_does_not_match_president')
    if db.execute('SELECT COUNT(*) FROM sections').fetchone()[0] != expected:
        raise ValueError('biometry_stored_inventory_mismatch')
    set_meta(db, 'inventory', {'sections': expected, 'ufs': inventories,
             'national': {'sections': expected, 'attendance': int(national['e']['c']),
                          'url': NATIONAL, 'sha256': national_sha}})
    set_meta(db, 'inventory_checked_at', time.time())
    set_meta(db, 'last_source_success_at', now())
    db.commit()
    return expected


def fetch_bu(client, target):
    uf, city, zone, section = (target[key] for key in ('uf', 'municipality', 'zone', 'section'))
    root = f'{SOURCE}/dados/{uf}/{city}/{zone}/{section}'
    aux, _ = client.json(f'{root}/p003221-{uf}-m{city}-z{zone}-s{section}-aux.json')
    if aux.get('st') != 'Totalizada':
        raise ValueError('biometry_section_not_totalized')
    choices = []
    for item in aux.get('hashes', []):
        if item.get('st') != 'Totalizado':
            continue
        fingerprint = item.get('hash', '')
        if not re.fullmatch('[a-f0-9]{64,256}', fingerprint):
            raise ValueError('biometry_invalid_source_directory')
        for file in item.get('arq', []):
            if file.get('tp') in {'bu', 'busa'}:
                expected = f'o03221{uf}{city}{zone}{section}-' + file['tp'] + '.dat'
                if file.get('nm') != expected:
                    raise ValueError('biometry_wrong_bu_filename')
                choices.append(f'{root}/{fingerprint}/{expected}')
    if len(choices) != 1:
        raise ValueError('biometry_ambiguous_totalized_bu')
    return client.get(choices[0]), choices[0]


def guard_storage(state):
    if shutil.disk_usage(state).free < int(os.environ.get('BIOMETRY_MIN_FREE_BYTES', 2 * 1024 ** 3)):
        raise RuntimeError('biometry_storage_reserve')
    if sum(path.stat().st_size for path in Path(state).glob('biometry.sqlite3*')) > 1024 ** 3:
        raise RuntimeError('biometry_checkpoint_quota')


def collect(db, client, *, limit=64, workers=4):
    targets = [dict(row) for row in db.execute('''SELECT * FROM sections
        WHERE (collected_stamp IS NULL OR collected_stamp<>stamp) AND retry_at<=?
        ORDER BY attempts,priority LIMIT ?''', (time.time(), limit))]
    count = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(fetch_bu, client, target): target for target in targets}
        for future in as_completed(jobs):
            target = jobs[future]
            try:
                raw, url = future.result()
                store(db, target, raw, url)
                set_meta(db, 'last_source_success_at', now())
                db.commit()
                count += 1
            except Exception as error:
                code = str(error) if re.fullmatch('[a-z][a-z0-9_]{1,100}', str(error)) else type(error).__name__
                delay = error.seconds if isinstance(error, Throttled) else min(3600, 60 * 2 ** min(target['attempts'], 6))
                db.execute('''UPDATE sections SET attempts=attempts+1,error=?,retry_at=?
                    WHERE uf=? AND municipality=? AND zone=? AND section=?''',
                    (code, time.time() + delay, *(target[key] for key in ('uf', 'municipality', 'zone', 'section'))))
                db.commit()
                if isinstance(error, Throttled):
                    set_meta(db, 'retry_after', time.time() + delay)
                    db.commit()
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['collect', 'watch', 'export', 'status'])
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=128)
    parser.add_argument('--rps', type=float, default=4)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    if (not args.state.is_absolute() or args.state.is_symlink()
            or not 1 <= args.limit <= 10000 or not 1 <= args.workers <= 16):
        raise ValueError('biometry_invalid_state_or_limit')
    args.state.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    client = OfficialHTTP(args.rps)
    with local_lock(args.state):
        db = database(args.state)
        if args.operation == 'status':
            value = aggregate(db)
            print(json.dumps({'totals': value['totals'], 'complete': value['complete']}))
            return
        while not stop.is_set():
            try:
                guard_storage(args.state)
                remaining = max(0, meta(db, 'retry_after', 0) - time.time())
                if remaining:
                    if args.operation != 'watch':
                        raise RuntimeError('biometry_source_cooldown')
                    stop.wait(min(60, remaining))
                    continue
                if not meta(db, 'inventory') or time.time() - meta(db, 'inventory_checked_at', 0) > 86400:
                    initialize(db, client)
                if args.operation != 'export':
                    count = collect(db, client, limit=args.limit, workers=args.workers)
                    print(json.dumps({'event': 'biometry_collected', 'sections': count, 'at': now()}), flush=True)
                publish_due = args.publish and (args.operation != 'watch' or time.time() - max(
                    meta(db, 'last_published', 0), meta(db, 'last_publish_attempt', 0)) >= 600)
                if args.operation == 'export' or args.output or publish_due:
                    data = aggregate(db)
                    if args.output:
                        args.output.write_bytes(canonical(data))
                    if publish_due:
                        from .biometry_publish import publish
                        # A failed publication must not stall official BU collection.
                        # Persist attempt cadence before connecting, including across
                        # restarts; the publisher retains its own recovery journal.
                        set_meta(db, 'last_publish_attempt', time.time())
                        db.commit()
                        try:
                            receipt = publish(args.state, data)
                        except Exception as error:
                            if args.operation != 'watch':
                                raise
                            code = str(error) if re.fullmatch('[a-z][a-z0-9_]{1,100}', str(error)) else type(error).__name__
                            print(json.dumps({'event': 'biometry_publish_failed',
                                  'error_type': type(error).__name__, 'code': code,
                                  'retry_at': meta(db, 'last_publish_attempt') + 600,
                                  'at': now()}), flush=True)
                        else:
                            set_meta(db, 'last_published', time.time())
                            db.commit()
                            print(json.dumps(receipt), flush=True)
                if args.operation != 'watch':
                    break
                if not count:
                    stop.wait(60)
            except Exception as error:
                if args.operation != 'watch':
                    raise
                code = str(error) if re.fullmatch('[a-z][a-z0-9_]{1,100}', str(error)) else type(error).__name__
                print(json.dumps({'event': 'biometry_cycle_failed', 'error_type': type(error).__name__,
                                  'code': code, 'at': now()}), flush=True)
                stop.wait(60)
        db.close()


if __name__ == '__main__':
    main()
