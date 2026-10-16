/* Shared reader for immutable election releases. No collection/publication effects. */
(function (root) {
    'use strict';
    function create(fetcher, options = {}) {
        const clock = options.clock || Date.now, sleep = options.sleep || (ms => new Promise(r => setTimeout(r, ms)));
        const random = options.random || Math.random;
        const memory = new Map(), inFlight = new Map(), bundles = new Map(), markers = new Map();
        let tail = Promise.resolve(), nextRequest = 0, blockedUntil = 0, failures = 0;
        let electionState = null, lastMarkerCheck = 0;
        let selectedBase = null;
        const stats = {network: 0, cacheHits: 0, bundleReuses: 0, deduplicated: 0, http429: 0, bytes: 0, markerDetectedAt: null};
        const immutable = url => /\/releases\/[a-f0-9]{64}\/[a-z/.-]+\.json$/.test(url);
        const eligible = url => /^\/data\/turnos\/2\/(?:version\.json|status\.json|releases\/[a-f0-9]{64}\/[a-z/.-]+\.json)$/.test(url);
        const retryAfter = value => {
            if (!value) return null;
            const seconds = /^\d+(?:\.\d+)?$/.test(value) ? Number(value) : (Date.parse(value) - clock()) / 1000;
            return Number.isFinite(seconds) && Number.isSafeInteger(Math.ceil(seconds * 1000)) ? Math.max(1, seconds) * 1000 : null;
        };
        const cache = async () => {
            try { return await root.caches?.open('election-immutable-v1'); } catch (_) { return null; }
        };
        async function discard(url) {
            memory.delete(url);
            try { await (await cache())?.delete(url); } catch (_) {}
        }
        async function forgetRelease(base) {
            for (const key of memory.keys()) if (key.startsWith(base + '/')) memory.delete(key);
            bundles.delete(base);
            try {
                const store = await cache();
                for (const request of await store?.keys() || []) {
                    if (new URL(request.url).pathname.startsWith(base + '/')) await store.delete(request);
                }
            } catch (_) {}
        }
        async function remembered(url) {
            let value = memory.get(url);
            if (!value) {
                const store = await cache(), response = await store?.match(url);
                if (response) {
                    value = {response, at: Number(response.headers.get('X-Election-Stored-At')) || 0};
                    memory.set(url, value);
                }
            }
            const ttl = url.endsWith('/status.json') ? 5000 : 2000;
            if (value && (immutable(url) || clock() - value.at < ttl)) {
                stats.cacheHits++; return value.response.clone();
            }
            return null;
        }
        async function remember(url, response) {
            const bytes = await response.arrayBuffer();
            if (bytes.byteLength > 4 * 1024 * 1024) throw new Error('election_response_too_large');
            JSON.parse(new TextDecoder().decode(bytes));
            stats.bytes += bytes.byteLength;
            const headers = new Headers(response.headers);
            headers.set('X-Election-Stored-At', String(clock()));
            headers.set('Cache-Control', immutable(url) ? 'public, max-age=31536000, immutable' : 'no-cache');
            const stored = new Response(bytes, {status: 200, headers});
            memory.set(url, {response: stored, at: clock()});
            // Three round-two generations are retained below; other readers
            // also have a fixed entry budget. Disk cache remains quota-bounded.
            if (memory.size > 80) memory.delete(memory.keys().next().value);
            const store = await cache();
            if (store) {
                try {
                    await store.put(url, stored.clone());
                    const keys = await store.keys();
                    for (const key of keys.slice(0, Math.max(0, keys.length - 160))) await store.delete(key);
                } catch (_) { /* quota/private browsing: bounded memory remains usable */ }
            }
            return stored.clone();
        }
        async function network(url) {
            for (let attempt = 0; attempt < 3; attempt++) {
                // One queue per page, plus cross-tab URL locks/cache below.
                // Public probing is bounded even when several components request data.
                const turn = tail.then(async () => {
                    let wait;
                    while ((wait = Math.max(nextRequest, blockedUntil) - clock()) > 0) await sleep(wait);
                    nextRequest = clock() + (options.spacingMs ?? 500) + random() * 100;
                });
                tail = turn.catch(() => {}); await turn;
                const controller = new AbortController();
                const timeout = setTimeout(() => controller.abort(), 20000);
                let response;
                try {
                    stats.network++;
                    if (url === '/data/turnos/2/version.json') lastMarkerCheck = clock();
                    const prior = memory.get(url)?.response;
                    const conditional = prior?.headers.get('ETag') && !immutable(url)
                        ? {'If-None-Match': prior.headers.get('ETag')} : {};
                    response = await fetcher(url, {cache: immutable(url) ? 'force-cache' : 'no-cache',
                        headers: conditional, credentials: 'same-origin', redirect: 'error', signal: controller.signal});
                    if (response.status === 304 && prior) return remember(url, prior.clone());
                } finally { clearTimeout(timeout); }
                if (response.status === 429) {
                    stats.http429++; failures++;
                    const minimum = retryAfter(response.headers.get('Retry-After')) || Math.min(60000, 1000 * 2 ** failures);
                    blockedUntil = Math.max(blockedUntil, clock() + minimum + random() * minimum * .2);
                    if (attempt < 2) continue;
                }
                if (!response.ok) return response;
                failures = 0;
                return remember(url, response);
            }
            throw new Error('election_rate_limited');
        }
        async function readNetwork(url) {
            const existing = await remembered(url);
            if (existing) return existing;
            const run = async () => (await remembered(url)) || network(url);
            return root.navigator?.locks?.request ? root.navigator.locks.request('election-read:' + url, run) : run();
        }
        async function portal(base, entry) {
            if (bundles.has(base)) stats.bundleReuses++;
            if (!bundles.has(base)) {
                const pending = (async () => {
                    if (!entry || !/^[a-f0-9]{64}$/.test(entry.sha256) || !Number.isInteger(entry.size)
                        || entry.size < 1 || entry.size > 4 * 1024 * 1024) throw new Error('invalid_portal_descriptor');
                    const response = await shared(base + '/portal.json');
                    if (!response.ok) throw new Error('portal_bundle_unavailable');
                    const bytes = await response.arrayBuffer();
                    const sum = Array.from(new Uint8Array(await root.crypto.subtle.digest('SHA-256', bytes)), x => x.toString(16).padStart(2, '0')).join('');
                    if (bytes.byteLength !== entry.size || sum !== entry.sha256) {
                        await discard(base + '/portal.json');
                        throw new Error('portal_bundle_integrity_error');
                    }
                    const bundle = JSON.parse(new TextDecoder().decode(bytes));
                    if (bundle.schema_version !== 1 || bundle.environment !== 'oficial' || bundle.round !== 2
                        || !bundle.files?.['manifest.json'] || !bundle.files?.['version.json']
                        || bundle.files['version.json'].round !== 2) throw new Error('invalid_portal_bundle');
                    return bundle.files;
                })();
                bundles.set(base, pending);
                if (bundles.size > 3) bundles.delete(bundles.keys().next().value);
                pending.catch(() => { if (bundles.get(base) === pending) bundles.delete(base); });
            }
            return bundles.get(base);
        }
        async function shared(url) {
            if (inFlight.has(url)) { stats.deduplicated++; return (await inFlight.get(url)).clone(); }
            const pending = readNetwork(url);
            inFlight.set(url, pending);
            try { return (await pending).clone(); }
            finally { if (inFlight.get(url) === pending) inFlight.delete(url); }
        }
        async function request(url, init = {}) {
            if (!eligible(url)) return fetcher(url, init);
            if (init.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
            let response;
            const match = url.match(/^(\/data\/turnos\/2\/releases\/[a-f0-9]{64})\/(.+)$/);
            const marker = match && markers.get(match[1]);
            if (marker?.portal && match[2] !== 'portal.json') {
                const files = await portal(match[1], marker.portal);
                if (!Object.hasOwn(files, match[2])) throw new Error('portal_missing_file');
                response = new Response(JSON.stringify(files[match[2]]), {headers: {'Content-Type': 'application/json'}});
            } else response = await shared(url);
            if (init.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
            if (url === '/data/turnos/2/version.json' && response.ok) {
                const value = await response.clone().json();
                if (value.environment !== 'oficial' || value.round !== 2 || !/^[a-f0-9]{64}$/.test(value.snapshot_id || '')) throw new Error('invalid_round2_marker');
                const base = '/data/turnos/2/releases/' + value.snapshot_id;
                if (selectedBase !== base) {
                    stats.markerDetectedAt = new Date(clock()).toISOString();
                    stats.markerSnapshotId = value.snapshot_id;
                    selectedBase = base;
                }
                markers.set(base, value);
                if (markers.size > 3) {
                    const old = markers.keys().next().value;
                    markers.delete(old); await forgetRelease(old);
                }
            }
            return response;
        }
        return {fetch: request, stats, retryAfter,
            setState: state => { electionState = state; },
            shouldPoll: () => clock() - lastMarkerCheck >= ({official_data_available: 15000,
                awaiting_official_data: 15000, counting_stable: 10000, counting_finished: 30000}[electionState] || 5000),
            paused: () => !!root.document?.hidden || clock() < blockedUntil};
    }
    root.LiveData = root.fetch ? create(root.fetch.bind(root)) : null;
    if (typeof module !== 'undefined' && module.exports) module.exports = {create};
})(typeof window !== 'undefined' ? window : globalThis);
