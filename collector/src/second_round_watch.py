"""Conditional official-file observer; uses the existing single writer and recovery."""
import json
from pathlib import Path
import re
import signal
import threading
import time

from .election_release import canonical, digest
from .second_round_collection import AwaitingData, CachedClient, RateLimited
from .second_round_publish import load, local_lock, now, save
from deploy.frontend import error_report

CONFIG = 'https://resultados.tse.jus.br/oficial/comum/config/ele-c.json'
INDEX = re.compile(r'https://resultados\.tse\.jus\.br/oficial/ele2026/(\d+)/dados/br/br-e\d{6}-ab\.json')


def watch_urls(state):
    checkpoint = load(state / 'checkpoint.json') or {}
    sid = checkpoint.get('snapshot_id', '')
    urls = {CONFIG}
    if re.fullmatch('[a-f0-9]{64}', sid):
        proof = load(state / 'cycles' / sid[:32] / 'source-proof.json') or {}
        if proof.get('round') == 2 and proof.get('snapshot_id') == sid:
            urls.update(url for url in proof.get('records', {}) if INDEX.fullmatch(url))
    return sorted(urls)


def watch(state):
    from .second_round_runner import cycle
    stop = threading.Event()
    for kind in (signal.SIGTERM, signal.SIGINT):
        signal.signal(kind, lambda *_: stop.set())
    client = CachedClient(state / 'watch-http-cache')
    previous = load(state / 'watch-state.json') or {}
    signature, last_full, failures = previous.get('signature'), 0.0, 0
    while not stop.is_set():
        try:
            health = load(state / 'health.json') or {}
            if health.get('status') == 'rate_limited' and health.get('retry_after_epoch', 0) > time.time():
                stop.wait(min(60, health['retry_after_epoch'] - time.time()))
                continue
            urls = watch_urls(state)
            for url in urls:
                payload = client.fetch_json(url).payload
                match = INDEX.fullmatch(url)
                if match and (payload.get('t') != '2' or payload.get('ele') != match.group(1)):
                    raise ValueError('invalid_official_watch_index')
            current = digest(canonical({url: client.records[url]['payload_sha256'] for url in urls}))
            if stop.is_set(): break
            changed = current != signature
            health = load(state / 'health.json') or {}
            due = time.time() >= health.get('retry_after_epoch', 0)
            # A real source change may shorten healthy cadence, never an error
            # backoff/Retry-After. Recovery still precedes every publication.
            healthy = health.get('status') in {'published', 'unchanged'} and not health.get('failures')
            if (changed and healthy) or (due and time.monotonic() - last_full >= 30) or not health:
                try:
                    with local_lock(state):
                        result = cycle(state, source_changed=changed)
                    print(json.dumps({'event': 'official_cycle', 'status': result.get('status'),
                                      'snapshot_id': result.get('snapshot_id'), 'checked_at': now()}), flush=True)
                    signature = current
                    last_full = time.monotonic()
                except RuntimeError as error:
                    if str(error) != 'second_round_writer_busy': raise
            if changed:
                save(state / 'watch-state.json', {'signature': signature, 'checked_at': now(),
                     'mode': 'conditional_http_observer', 'interval_seconds': 2})
            failures = 0
            stop.wait(2)
        except RateLimited as error:
            print(json.dumps({'event': 'official_observer_rate_limited', 'retry_seconds': error.seconds}), flush=True)
            stop.wait(error.seconds)
        except Exception as error:
            failures += 1
            print(json.dumps({'event': 'official_observer_error', **error_report(error)}), flush=True)
            stop.wait(60 if isinstance(error, AwaitingData) else min(60, 2 ** min(failures, 6)))
    client.session.close()
    return 0
