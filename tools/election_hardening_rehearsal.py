"""Sustained loopback-only load/release/429 exercise; zero public/TSE/FTP access.

Serves the real frontend with explicitly invented fixtures. Production credentials
are neither loaded nor used. Request budgets and client population are bounded.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
import math
from pathlib import Path
import statistics
import sys
import time
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tests'))
from hardening_fixtures import FullSource
from collector.src.election_release import canonical
from collector.src.second_round_collection import discover, build_values
from collector.src.second_round_publish import describe, marker_for


def percentiles(values):
    if not values: return {'samples': 0}
    ordered = sorted(values)
    result = {'samples': len(values), 'p50': statistics.median(values), 'max': max(values)}
    for p, minimum in [(95, 20), (99, 100)]:
        if len(values) >= minimum: result['p' + str(p)] = ordered[math.ceil(len(ordered) * p / 100) - 1]
    return result


async def rehearsal(args):
    started, events, trace = time.monotonic(), [], []
    releases = {}
    current = None
    injected_429 = False
    async def source():
        nonlocal current
        generation = 1
        while time.monotonic() - started < args.duration + 5:
            client = FullSource(generation=generation, totalized=0 if generation == 1 else 50)
            values = build_values(client, discover(client))
            verified = describe(values)
            if verified['targets'] != 35: raise ValueError('rehearsal_fixture_inventory_mismatch')
            sid = verified['snapshot_id']; marker = marker_for(verified)
            releases[sid] = values
            current = (sid, marker)
            events.append({'snapshot_id': sid, 'source_observed_at_ms': time.time() * 1000,
                           'targets': verified['targets'], 'generation': generation})
            generation += 1
            await asyncio.sleep(args.change_every)
    async def handle(reader, writer):
        nonlocal injected_429
        begin = time.monotonic()
        try:
            raw = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), timeout=10)
            lines = raw.decode('iso-8859-1').split('\r\n')
            method, request_path, _ = lines[0].split(' ')
            headers = dict(row.split(': ', 1) for row in lines[1:] if ': ' in row)
            path = unquote(urlsplit(request_path).path)
            status, content_type, extra = 200, 'application/json', {}
            body = b''
            sid, marker = current
            if method != 'GET' or '..' in Path(path).parts: status = 400
            elif path == '/data/turnos/2/version.json':
                if headers.get('X-Rehearsal-Session') == '0' and not injected_429 and time.monotonic() - started > 15:
                    status = 429; extra['Retry-After'] = '3'; injected_429 = True
                else: body = marker
            elif path == '/data/turnos/2/status.json':
                stamp = datetime.now(timezone.utc).isoformat()
                body = canonical({'schema_version': 1, 'environment': 'oficial', 'round': 2,
                    'checked_at': stamp, 'last_source_success_at': stamp,
                    'last_publication_at': datetime.fromtimestamp(events[-1]['source_observed_at_ms'] / 1000, timezone.utc).isoformat(),
                    'last_official_change_at': stamp, 'snapshot_id': sid, 'source_stale_after_seconds': 180,
                    'state': 'awaiting_results' if len(events) == 1 else 'current'})
            elif path.startswith('/data/turnos/2/releases/'):
                rest = path.removeprefix('/data/turnos/2/releases/'); key, _, name = rest.partition('/')
                body = releases.get(key, {}).get(name)
                if body is None: status, body = 404, b''
                else: extra['Cache-Control'] = 'public, max-age=31536000, immutable'
            elif path.startswith('/municipal-2026/'):
                status = 404
            elif path.startswith('/eleicoes/'):
                relative = path.removeprefix('/eleicoes/') or 'index.html'
                file = (ROOT / 'web/public/eleicoes' / relative).resolve()
                if not file.is_relative_to(ROOT / 'web/public/eleicoes') or not file.is_file(): status = 404
                else:
                    body = file.read_bytes(); content_type = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
            else: status = 404
            if status == 200:
                etag = '"' + hashlib.sha256(body).hexdigest() + '"'; extra['ETag'] = etag
                if headers.get('If-None-Match') == etag: status, body = 304, b''
            extra.update({'Content-Type': content_type, 'Content-Length': str(len(body)), 'Connection': 'close'})
            response = 'HTTP/1.1 ' + str(status) + ' Rehearsal\r\n' + ''.join(k + ': ' + v + '\r\n' for k, v in extra.items()) + '\r\n'
            writer.write(response.encode() + body); await writer.drain()
            trace.append({'session': headers.get('X-Rehearsal-Session'), 'path': path, 'status': status,
                          'bytes': len(body), 'at_ms': time.time() * 1000, 'duration_ms': (time.monotonic() - begin) * 1000})
        except (OSError, ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError): pass
        finally:
            writer.close()
    source_task = asyncio.create_task(source()); await asyncio.sleep(.1)
    server = await asyncio.start_server(handle, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]; origin = 'http://127.0.0.1:' + str(port)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'origin.txt').write_text(origin)
    print(json.dumps({'loopback_origin': origin, 'users': args.users, 'duration': args.duration}), flush=True)
    try:
        proc = await asyncio.create_subprocess_exec('node', str(ROOT / 'tools/election_hardening_load.js'),
            origin, str(args.users), str(args.duration), str(args.output / 'load-clients.json'),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        if proc.returncode: raise RuntimeError(stderr.decode())
    finally:
        server.close(); await server.wait_closed()
        source_task.cancel(); await asyncio.gather(source_task, return_exceptions=True)
    clients = json.loads((args.output / 'load-clients.json').read_text())
    stamps = {e['snapshot_id']: e['source_observed_at_ms'] for e in events}
    delays = [(d['detected_at'] - stamps[d['snapshot_id']]) / 1000 for d in clients['detections']]
    requests = clients['requests']
    buckets = Counter(int((x['at_ms'] - events[0]['source_observed_at_ms']) / 1000) for x in trace)
    session_zero = [r for r in trace if r['session'] == '0' and r['path'].endswith('/version.json')]
    limits_ok = True
    for i, r in enumerate(session_zero[:-1]):
        if r['status'] == 429 and session_zero[i + 1]['at_ms'] - r['at_ms'] < 3000: limits_ok = False
    report = {'scope': 'isolated_loopback_synthetic_only', 'users': args.users,
        'duration_seconds': clients['duration_seconds'], 'release_changes': len(events),
        'target_counts': sorted(set(x['targets'] for x in events)),
        'requests': len(trace), 'peak_rps_one_second_bucket': max(buckets.values()),
        'average_rps': len(trace) / clients['duration_seconds'], 'http_statuses': dict(Counter(r['status'] for r in trace)),
        'intentional_429_injected': injected_429, 'retry_after_respected': limits_ok,
        'frontend_source_observation_to_data_loaded_seconds': percentiles(delays),
        'response_ms': percentiles([x['duration_ms'] for x in requests]),
        'client_errors': clients['errors'], 'client_network_requests': sum(s['network'] for s in clients['stats']),
        'client_cache_hits': sum(s['cacheHits'] for s in clients['stats']),
        'client_bytes': sum(s['bytes'] for s in clients['stats'])}
    (args.output / 'server-events.json').write_text(json.dumps({'events': events, 'trace': trace}, indent=2))
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--users', type=int, default=100)
    p.add_argument('--duration', type=int, default=360)
    p.add_argument('--change-every', type=int, default=10)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if not 1 <= args.users <= 1000 or not 20 <= args.duration <= 1800 or args.change_every < 5:
        p.error('Rehearsal exceeds limits')
    if args.duration / args.change_every > 55: p.error('At most 55 fixture generations per rehearsal')
    asyncio.run(rehearsal(args))


if __name__ == '__main__': main()
