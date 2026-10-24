"""Run the real shared HTTP reader with synthetic transports, clocks and tabs."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const source = fs.readFileSync('web/public/eleicoes/live-data.js', 'utf8');
const first = '/data', second = '/data/turnos/2', sid = 'a'.repeat(64);
const clock = () => {let now = Date.UTC(2026, 9, 16); return {
  now: () => now, advance: ms => {now += ms;}, sleep: async ms => {now += ms;}
};};
function reader(fetcher, globals = {}, options = {}) {
  const context = {module: {exports: {}}, Response, Headers, TextDecoder, TextEncoder,
    Uint8Array, ArrayBuffer, AbortController, DOMException, URLSearchParams,
    setTimeout, clearTimeout, crypto: webcrypto, ...globals};
  vm.createContext(context); vm.runInContext(source, context);
  return context.module.exports.create(fetcher, {spacingMs: 0, random: () => 0, ...options});
}
function storage() {
  const values = new Map();
  return {getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, value)};
}
function caches() {
  const stores = new Map();
  return {stores, open: async name => {
    if (!stores.has(name)) stores.set(name, new Map());
    const entries = stores.get(name), key = request => typeof request === 'string'
      ? request : new URL(request.url).pathname;
    return {match: async url => entries.get(key(url))?.clone(),
      put: async (url, response) => {entries.set(key(url), response.clone());},
      delete: async url => entries.delete(key(url)),
      keys: async () => [...entries.keys()].map(url => ({url: 'https://fixture.invalid' + url}))};
  }};
}
function locks() {
  const tails = new Map();
  return {request: (name, run) => {
    const result = (tails.get(name) || Promise.resolve()).catch(() => {}).then(run);
    tails.set(name, result);
    return result.finally(() => {if (tails.get(name) === result) tails.delete(name);});
  }};
}
const options = time => ({clock: time.now, sleep: time.sleep});
const marker = round => ({environment: 'oficial', round, snapshot_id: sid, activation_revision: '1'});
const json = value => new Response(JSON.stringify(value), {headers: {ETag: '"fixture"'}});
'''


def run_node(script):
    node = shutil.which('node')
    assert node, 'Node is required for shared-reader contract tests'
    result = subprocess.run(
        [node, '-e', HARNESS + '\n(async () => {\n' + script
         + '\n})().catch(error => {console.error(error); process.exitCode = 1;});'],
        cwd=ROOT, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('search,default_poll', [('', True), ('?turno=1', False), ('?turno=2', True)])
def test_round_namespaces_caches_markers_and_polling_are_independent(search, default_poll):
    run_node(r'''
const time = clock(), disk = caches(), calls = [];
let firstMarker = marker(1);
const r = reader(async (url, init) => {
  calls.push({url, init});
  return json(url === first + '/version.json' ? firstMarker
    : url === second + '/version.json' ? marker(2) : {url});
}, {caches: disk, location: {search: SEARCH}}, options(time));
await Promise.all([r.fetch(first + '/version.json'), r.fetch(second + '/version.json')]);
assert.equal(disk.stores.size, 2);
r.setState('counting_finished', first); r.setState('counting_in_progress', second);
time.advance(6000);
assert.equal(r.shouldPoll(first + '/releases/' + sid), false);
assert.equal(r.shouldPoll(second + '/releases/' + sid), true);
assert.equal(r.shouldPoll(), DEFAULT_POLL); // Default follows the selected URL round.
firstMarker = {...firstMarker, snapshot_id: 'b'.repeat(64)};
await r.fetch(first + '/version.json');
assert.equal(r.shouldPoll(first + '/releases/' + sid), true);
assert.equal(r.stats.byRound[2].markerSnapshotId, sid);
assert.equal(r.stats.markerSnapshotId, sid); // Legacy status fields remain round two.
await Promise.all([r.fetch(first + '/manifest.json'), r.fetch(first + '/manifest.json')]);
assert.equal(calls.filter(row => row.url === first + '/manifest.json').length, 1);
await r.fetch(first + '/releases/' + 'c'.repeat(32) + '/ac/president.json');
assert.equal(calls.at(-1).init.cache, 'force-cache');
const before = calls.length;
const financialInit = {cache: 'reload'};
await r.fetch('/data/go-2026.json', financialInit);
assert.equal(calls.length, before + 1);
assert.equal(calls.at(-1).init, financialInit);
'''.replace('SEARCH', repr(search)).replace('DEFAULT_POLL', str(default_poll).lower()))


def test_first_round_legacy_marker_and_304_revalidation_remain_supported():
    run_node(r'''
const time = clock(), calls = [];
const r = reader(async (url, init) => {
  calls.push({url, init});
  if (calls.length === 2) {
    assert.equal(init.headers['If-None-Match'], '"fixture"');
    return new Response(null, {status: 304});
  }
  return json({generated_at: 'legacy'});
}, {}, options(time));
assert.equal((await (await r.fetch(first + '/version.json')).json()).generated_at, 'legacy');
time.advance(3000);
assert.equal((await (await r.fetch(first + '/version.json')).json()).generated_at, 'legacy');
assert.equal(r.stats.byRound[1].selectedBase, first);
assert.equal(r.stats.byRound[2].lastMarkerCheck, null);
assert.equal(calls.length, 2);
await assert.rejects(reader(async () => json({...marker(1), round: 2}), {}, options(time))
  .fetch(first + '/version.json'), /invalid_round1_marker/);
''')


def test_retry_after_seconds_dates_and_network_backoff_are_bounded():
    run_node(r'''
const time = clock(), start = time.now(), starts = [];
const r = reader(async () => {
  starts.push(time.now());
  if (starts.length === 1) return new Response('', {status: 429, headers: {'Retry-After': '120'}});
  if (starts.length === 2) return new Response('', {status: 503,
    headers: {'Retry-After': new Date(time.now() + 10000).toUTCString()}});
  return json({});
}, {}, options(time));
assert((await r.fetch(first + '/status.json')).ok);
assert.equal(starts.length, 3);
assert(starts[1] >= start + 120000);
assert(starts[2] >= starts[1] + 10000);
assert.equal(r.stats.retries, 2); assert.equal(r.stats.http429, 1);
assert.equal(r.retryAfter('7200'), 7200000);
assert.equal(r.retryAfter('invalid'), null);
const offlineStarts = [];
const recovering = reader(async () => {
  offlineStarts.push(time.now());
  if (offlineStarts.length < 3) throw new TypeError('synthetic offline');
  return json({recovered: true});
}, {}, options(time));
assert((await (await recovering.fetch(second + '/status.json')).json()).recovered);
assert(offlineStarts[1] - offlineStarts[0] >= 2000);
assert(offlineStarts[2] - offlineStarts[1] >= 4000);
let count = 0;
const exhausted = reader(async () => {count++; return new Response('', {status: 429});}, {}, options(time));
assert.equal((await exhausted.fetch(first + '/status.json')).status, 429);
assert.equal(count, 3); assert(exhausted.paused(first));
''')


def test_queue_limits_concurrent_slow_response_bodies():
    run_node(r'''
const time = clock(); let active = 0, peak = 0;
const r = reader(async () => {
  active++; peak = Math.max(peak, active);
  return new Response(new ReadableStream({start(controller) {
    setTimeout(() => {active--; controller.enqueue(new TextEncoder().encode('{}')); controller.close();}, 10);
  }}));
}, {}, options(time));
const paths = ['ac/president', 'go/governor', 'am/senator', 'br/president', 'manifest', 'alerts'];
await Promise.all(paths.map(path => r.fetch(first + '/' + path + '.json')));
assert.equal(peak, 1); assert.equal(active, 0); assert.equal(r.stats.network, paths.length);
''')


@pytest.mark.parametrize('phase', ['headers', 'body'])
def test_timeout_covers_headers_and_body_and_recovers(phase):
    run_node('const phase = ' + repr(phase) + ';' + r'''
const time = clock(); let count = 0, active = 0, peak = 0;
const r = reader(async (url, init) => {
  count++; active++; peak = Math.max(peak, active);
  if (count === 3) {active--; return json({ok: true});}
  if (phase === 'headers') return new Promise((_, reject) => {
    init.signal.addEventListener('abort', () => {active--; reject(new DOMException('Aborted', 'AbortError'));});
  });
  return new Response(new ReadableStream({cancel() {active--;}}));
}, {}, {...options(time), timeoutMs: 15});
assert((await (await r.fetch(first + '/status.json')).json()).ok);
assert.equal(count, 3); assert.equal(r.stats.timeouts, 2); assert.equal(peak, 1); assert.equal(active, 0);
''')


@pytest.mark.parametrize('status', [429, 503])
@pytest.mark.parametrize('header_kind', ['seconds', 'date'])
def test_retry_after_is_shared_at_headers_even_when_error_body_times_out(status, header_kind):
    run_node('const status = ' + str(status) + ', headerKind = ' + repr(header_kind) + ';' + r'''
const time = clock(), start = time.now(), minimum = start + 120000;
const shared = {localStorage: storage(), navigator: {locks: locks()}};
const starts = [], otherStarts = [];
let headersReady;
const headersReceived = new Promise(resolve => {headersReady = resolve;});
const a = reader(async () => {
  starts.push(time.now());
  if (starts.length === 1) {
    const response = new Response(new ReadableStream({cancel() {time.advance(15000);}}),
      {status, headers: {'Retry-After': headerKind === 'seconds' ? '120' : new Date(minimum).toUTCString()}});
    headersReady(); return response;
  }
  if (starts.length === 2) throw new TypeError('synthetic subsequent offline');
  return json({recovered: true});
}, shared, {...options(time), timeoutMs: 15});
const b = reader(async () => {otherStarts.push(time.now()); return json({});}, shared, options(time));
const pending = a.fetch(first + '/status.json');
await headersReceived;
await new Promise(setImmediate); // Headers handled, first body still unresolved.
const sharedWhileReadingBody = b.paused(second);
const other = b.fetch(second + '/status.json');
assert((await (await pending).json()).recovered); await other;
assert(sharedWhileReadingBody, 'Retry-After must be visible before consuming the body');
assert.equal(starts[1], minimum, 'Server deadline is measured at headers, not body failure');
assert.equal(starts[2] - starts[1], 4000, 'One failed response increments backoff only once');
assert(otherStarts[0] >= minimum, 'Another tab must observe the error-header cooldown');
assert.equal(a.stats.http429, status === 429 ? 1 : 0);
assert.equal(a.stats.timeouts, 1); assert.equal(a.stats.retries, 2);
''')


def test_one_consumer_abort_does_not_cancel_a_shared_transport():
    run_node(r'''
const time = clock(), consumer = new AbortController();
let resolveFetch, started, transportSignal, calls = 0;
const begun = new Promise(resolve => {started = resolve;});
const r = reader(async (url, init) => {
  calls++; transportSignal = init.signal; started();
  return new Promise(resolve => {resolveFetch = resolve;});
}, {}, options(time));
const canceled = r.fetch(first + '/status.json', {signal: consumer.signal});
const surviving = r.fetch(first + '/status.json');
await begun; consumer.abort();
await assert.rejects(canceled, error => error.name === 'AbortError');
assert.equal(transportSignal.aborted, false);
resolveFetch(json({survived: true}));
assert((await (await surviving).json()).survived);
assert.equal(calls, 1); assert.equal(r.stats.deduplicated, 1);
''')


def test_tabs_share_url_cache_and_transport_lock_through_slow_bodies():
    run_node(r'''
const time = clock(), shared = {caches: caches(), localStorage: storage(), navigator: {locks: locks()}};
let calls = 0, active = 0, peak = 0;
const fetcher = async url => {
  calls++; active++; peak = Math.max(peak, active);
  return new Response(new ReadableStream({start(controller) {
    setTimeout(() => {active--; controller.enqueue(new TextEncoder().encode(JSON.stringify(
      url.endsWith('/version.json') ? marker(1) : {}))); controller.close();}, 10);
  }}));
};
const a = reader(fetcher, shared, options(time)), b = reader(fetcher, shared, options(time));
await Promise.all([a.fetch(first + '/version.json'), b.fetch(first + '/version.json')]);
assert.equal(calls, 1); assert.equal(b.shouldPoll(first + '/releases/' + sid), false);
time.advance(2100);
await Promise.all([a.fetch(first + '/version.json'), b.fetch(first + '/version.json')]);
assert.equal(calls, 2); // Stale page memory must consult the fresh cross-tab cache.
await Promise.all([a.fetch(first + '/manifest.json'), b.fetch(second + '/status.json')]);
assert.equal(peak, 1); assert.equal(calls, 4);
''')


def test_cross_tab_cooldown_extends_during_sleep_and_expires_without_a_lock():
    run_node(r'''
const time = clock(), start = time.now(), signal = storage(), key = 'election-http-cooldown-v1';
let calls = 0, extended = false, sleeps = [];
const a = reader(async () => {calls++; return calls === 1
  ? new Response('', {status: 429, headers: {'Retry-After': '120'}}) : json({});},
  {localStorage: signal}, {...options(time), sleep: async ms => {
    sleeps.push(ms);
    if (!extended) {extended = true; signal.setItem(key, JSON.stringify({until: start + 180000}));}
    time.advance(ms);
  }});
const bStarts = [];
const b = reader(async () => {bStarts.push(time.now()); return json({});}, {localStorage: signal}, options(time));
await a.fetch(first + '/status.json');
assert(time.now() >= start + 180000); assert(sleeps.every(ms => ms <= 60000));
assert(sleeps.length <= 4); assert.equal(b.paused(second), false);
signal.setItem(key, JSON.stringify({until: time.now() + 125000}));
assert(b.paused(second)); const deadline = time.now() + 125000;
await b.fetch(second + '/status.json');
assert(bStarts[0] >= deadline); assert.equal(b.paused(second), false);
''')


def test_cache_storage_quota_and_locks_failures_keep_page_reader_usable():
    run_node(r'''
const time = clock(); let calls = 0;
const unavailable = () => {throw new Error('synthetic storage disabled');};
const r = reader(async () => {calls++; return json({ok: true});}, {
  localStorage: {getItem: unavailable, setItem: unavailable},
  navigator: {locks: {request: async () => unavailable()}},
  caches: {open: async () => ({match: unavailable, put: unavailable, keys: unavailable, delete: unavailable})}
}, options(time));
await Promise.all([r.fetch(first + '/status.json'), r.fetch(first + '/status.json')]);
assert.equal(calls, 1); time.advance(6000);
assert((await (await r.fetch(first + '/status.json')).json()).ok); assert.equal(calls, 2);
let failures = 0;
const broken = reader(async () => {failures++; throw new Error('offline');},
  {navigator: {locks: locks()}}, options(time));
await assert.rejects(broken.fetch(first + '/status.json'), /offline/);
assert.equal(failures, 3); // Callback failure must not invoke the fallback again.
''')


def test_announced_bundles_verify_hash_without_fallback_or_round_mixing():
    run_node(r'''
const time = clock(), rows = [], bundles = new Map(), markers = new Map();
for (const round of [1, 2]) {
  const base = round === 1 ? first : second;
  const files = {'version.json': marker(round), 'manifest.json': {round}, 'ac/president.json': {round}};
  const raw = JSON.stringify({schema_version: 1, environment: 'oficial', round, files});
  const hash = require('node:crypto').createHash('sha256').update(raw).digest('hex');
  bundles.set(base, raw); markers.set(base, {...marker(round), portal: {sha256: hash, size: Buffer.byteLength(raw)}});
}
let corrupt = true;
const r = reader(async (url, init) => {
  rows.push({url, init}); const base = url.startsWith(second + '/') ? second : first;
  if (url === base + '/version.json') return json(markers.get(base));
  assert(url.endsWith('/portal.json')); // Never fall back to individual JSONs.
  return new Response(corrupt && base === first ? '{}' : bundles.get(base));
}, {caches: caches()}, options(time));
await Promise.all([r.fetch(first + '/version.json'), r.fetch(second + '/version.json')]);
await assert.rejects(r.fetch(first + '/releases/' + sid + '/manifest.json'), /integrity/);
assert.equal((await (await r.fetch(second + '/releases/' + sid + '/ac/president.json')).json()).round, 2);
corrupt = false;
assert.equal((await (await r.fetch(first + '/releases/' + sid + '/manifest.json')).json()).round, 1);
assert.equal(rows.at(-1).init.cache, 'reload');
assert.equal(rows.filter(row => row.url.endsWith('/portal.json')).length, 3);
const invalid = reader(async url => json(url.endsWith('/version.json') ? {...marker(1), portal: null} : {}), {}, options(time));
await invalid.fetch(first + '/version.json');
await assert.rejects(invalid.fetch(first + '/releases/' + sid + '/manifest.json'), /invalid_portal_descriptor/);
''')
