/* Shared, bounded HTTP reader for both election rounds. No publication effects. */
(function (root) {
    'use strict';
    function create(fetcher, options = {}) {
        const clock = options.clock || Date.now, sleep = options.sleep || (ms => new Promise(r => setTimeout(r, ms)));
        const random = options.random || Math.random;
        const memory = new Map(), inFlight = new Map(), bundles = new Map(), markers = new Map();
        const reload = new Set();
        let tail = Promise.resolve(), nextRequest = 0, blockedUntil = 0, failures = 0;
        const defaultNamespace = root.location
            ? (new URLSearchParams(root.location.search).get('turno') === '1' ? '/data' : '/data/turnos/2')
            : '/data/turnos/2'; // Preserve the standalone round-two reader API.
        const contexts = new Map(['/data', '/data/turnos/2'].map(base => [base,
            {round: base === '/data' ? 1 : 2, electionState: null, lastMarkerCheck: null,
                selectedBase: null, markerDetectedAt: null, markerSnapshotId: null}]));
        const stats = {network: 0, cacheHits: 0, bundleReuses: 0, deduplicated: 0, http429: 0,
            retries: 0, timeouts: 0, bytes: 0, markerDetectedAt: null,
            byRound: {1: contexts.get('/data'), 2: contexts.get('/data/turnos/2')}};
        const namespace = url => typeof url === 'string' && (url === '/data' || url.startsWith('/data/'))
            ? (url === '/data/turnos/2' || url.startsWith('/data/turnos/2/') ? '/data/turnos/2' : '/data')
            : defaultNamespace;
        const immutable = url => /\/releases\/[a-f0-9]{32,64}\//.test(url);
        // Never intercept finance, other rounds, traversal, or non-election JSONs.
        const eligible = url => typeof url === 'string' && /^\/data\/(?:turnos\/2\/)?(?:releases\/[a-f0-9]{32,64}\/)?(?:(?:version|status|manifest|alerts|portal)\.json|[a-z]{2}\/(?:president|governor|senator|federal-deputy|state-deputy|district-deputy)\.json)$/.test(url);
        const cooldownKey = 'election-http-cooldown-v1';
        const retryAfter = value => {
            if (!value) return null;
            value = String(value).trim();
            const ms = /^\d+(?:\.\d+)?$/.test(value) ? Math.ceil(Number(value) * 1000) : Date.parse(value) - clock();
            return Number.isSafeInteger(ms) ? Math.max(0, ms) : null;
        };
        const cache = async url => {
            try { return await root.caches?.open(namespace(url) === '/data' ? 'election-round1-v1' : 'election-immutable-v1'); }
            catch (_) { return null; }
        };
        function cooldown() {
            try {
                const value = JSON.parse(root.localStorage?.getItem(cooldownKey) || 'null');
                if (Number.isSafeInteger(value?.until)) blockedUntil = Math.max(blockedUntil, value.until);
            } catch (_) { /* Storage can be disabled or full. No persistent lock. */ }
            return blockedUntil;
        }
        function defer(response) {
            failures = Math.min(failures + 1, 6);
            const backoff = Math.min(60000, 1000 * 2 ** failures);
            const minimum = Math.max(retryAfter(response?.headers.get('Retry-After')) || 0, backoff);
            blockedUntil = Math.max(cooldown(), clock() + minimum + Math.floor(random() * Math.min(1000, minimum * .2)));
            try { root.localStorage?.setItem(cooldownKey, JSON.stringify({until: blockedUntil})); } catch (_) {}
        }
        async function locked(name, run) {
            // Rejected/unavailable Web Locks fall back to page-local serialization.
            // Errors inside the callback must never run the request a second time.
            let entered = false;
            try {
                if (root.navigator?.locks?.request) return await root.navigator.locks.request(name, () => {
                    entered = true; return run();
                });
            } catch (error) { if (entered) throw error; }
            return run();
        }
        async function discard(url) {
            memory.delete(url);
            // Cache API deletion cannot evict a corrupt native HTTP cache entry.
            reload.add(url);
            if (reload.size > 80) reload.delete(reload.values().next().value);
            try { await (await cache(url))?.delete(url); } catch (_) {}
        }
        async function forgetRelease(base) {
            for (const key of memory.keys()) if (key.startsWith(base + '/')) memory.delete(key);
            for (const key of reload) if (key.startsWith(base + '/')) reload.delete(key);
            bundles.delete(base);
            try {
                const store = await cache(base);
                for (const request of await store?.keys() || []) {
                    if (new URL(request.url).pathname.startsWith(base + '/')) await store.delete(request);
                }
            } catch (_) {}
        }
        async function remembered(url) {
            let value = memory.get(url);
            const ttl = url.endsWith('/status.json') ? 5000 : 2000;
            const fresh = candidate => candidate && (immutable(url)
                || (clock() >= candidate.at && clock() - candidate.at < ttl));
            if (!fresh(value)) {
                try {
                    const response = await (await cache(url))?.match(url);
                    if (response) {
                        value = {response, at: Number(response.headers.get('X-Election-Stored-At')) || 0};
                        memory.set(url, value);
                    }
                } catch (_) { /* A broken Cache API must not break network reads. */ }
            }
            if (fresh(value)) {
                stats.cacheHits++; return value.response.clone();
            }
            return null;
        }
        async function remember(url, response, bytes) {
            bytes = bytes || await response.arrayBuffer();
            if (bytes.byteLength > 4 * 1024 * 1024) throw new Error('election_response_too_large');
            JSON.parse(new TextDecoder().decode(bytes));
            stats.bytes += bytes.byteLength;
            const headers = new Headers(response.headers);
            headers.set('X-Election-Stored-At', String(clock()));
            headers.set('Cache-Control', immutable(url) ? 'public, max-age=31536000, immutable' : 'no-cache');
            const stored = new Response(bytes, {status: 200, headers});
            memory.set(url, {response: stored, at: clock()});
            // Three generations per round are retained below; other readers
            // also have a fixed entry budget. Disk cache remains quota-bounded.
            if (memory.size > 80) memory.delete(memory.keys().next().value);
            const store = await cache(url);
            if (store) {
                try {
                    await store.put(url, stored.clone());
                    const keys = await store.keys();
                    for (const key of keys.slice(0, Math.max(0, keys.length - 160))) await store.delete(key);
                } catch (_) { /* quota/private browsing: bounded memory remains usable */ }
            }
            return stored.clone();
        }
        async function attempt(url, onHeaders) {
            // The timeout covers headers AND body, with a bounded streaming read.
            const controller = new AbortController();
            let body, timedOut = false, timer;
            const deadline = new Promise((_, reject) => {
                timer = setTimeout(() => {
                    timedOut = true; stats.timeouts++; controller.abort();
                    if (body) Promise.resolve(body.cancel()).catch(() => {});
                    reject(new Error('election_request_timeout'));
                }, options.timeoutMs ?? 20000);
            });
            const reading = (async () => {
                stats.network++;
                if (url === namespace(url) + '/version.json') contexts.get(namespace(url)).lastMarkerCheck = clock();
                const prior = memory.get(url)?.response;
                const conditional = prior?.headers.get('ETag') && !immutable(url)
                    ? {'If-None-Match': prior.headers.get('ETag')} : {};
                const response = await fetcher(url, {cache: reload.has(url) ? 'reload' : immutable(url) ? 'force-cache' : 'no-cache',
                    headers: conditional, credentials: 'same-origin', redirect: 'error', signal: controller.signal});
                if (timedOut) { await response.body?.cancel(); throw new Error('election_request_timeout'); }
                onHeaders(response);
                if (response.status === 304 && prior) return {response: prior.clone(), bytes: await prior.clone().arrayBuffer()};
                const chunks = []; let size = 0;
                body = response.body?.getReader();
                if (body) {
                    while (true) {
                        const {done, value} = await body.read();
                        if (timedOut) throw new Error('election_request_timeout');
                        if (done) break;
                        size += value.byteLength;
                        if (size > 4 * 1024 * 1024) { await body.cancel(); throw new Error('election_response_too_large'); }
                        chunks.push(value);
                    }
                }
                const bytes = new Uint8Array(size); let offset = 0;
                for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
                return {response, bytes: bytes.buffer};
            })();
            try { return await Promise.race([reading, deadline]); }
            finally { clearTimeout(timer); }
        }
        async function network(url) {
            for (let count = 0; count < 3; count++) {
                // One active transport per page, including slow response bodies.
                // Web Locks enforce the same bound across participating tabs.
                const turn = tail.then(() => locked('election-http-request-v1', async () => {
                    let wait;
                    // Chunk long delays to avoid setTimeout overflow. Recheck after
                    // sleeping: another tab may have extended Retry-After meanwhile.
                    while ((wait = Math.max(nextRequest, cooldown()) - clock()) > 0) await sleep(Math.min(wait, 60000));
                    nextRequest = clock() + (options.spacingMs ?? 500) + random() * 100;
                    let deferred = false;
                    try {
                        const value = await attempt(url, response => {
                            if (response.status === 429 || response.status >= 500) {
                                // Publish the server's deadline immediately: an error
                                // body can fail or time out before it is consumed.
                                deferred = true;
                                if (response.status === 429) stats.http429++;
                                defer(response);
                            }
                        });
                        if (value.response.ok) failures = 0;
                        return value;
                    } catch (error) { if (!deferred) defer(); throw error; }
                }));
                tail = turn.catch(() => {});
                let value;
                try { value = await turn; }
                catch (error) {
                    if (count < 2 && error.message !== 'election_response_too_large') { stats.retries++; continue; }
                    throw error;
                }
                const {response, bytes} = value;
                if (response.status === 429 || response.status >= 500) {
                    if (count < 2) { stats.retries++; continue; }
                }
                if (!response.ok) return new Response(bytes.byteLength ? bytes : null,
                    {status: response.status, statusText: response.statusText, headers: response.headers});
                try {
                    const stored = await remember(url, response, bytes);
                    reload.delete(url);
                    return stored;
                } catch (error) {
                    if (immutable(url)) await discard(url);
                    throw error;
                }
            }
        }
        async function readNetwork(url) {
            const existing = await remembered(url);
            if (existing) return existing;
            const run = async () => (await remembered(url)) || network(url);
            return locked('election-read:' + url, run);
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
                    const round = contexts.get(namespace(base)).round;
                    if (bundle.schema_version !== 1 || bundle.environment !== 'oficial' || bundle.round !== round
                        || !bundle.files?.['manifest.json'] || !bundle.files?.['version.json']
                        || bundle.files['version.json'].round !== round) throw new Error('invalid_portal_bundle');
                    return bundle.files;
                })();
                bundles.set(base, pending);
                const sameRound = [...bundles.keys()].filter(key => namespace(key) === namespace(base));
                if (sameRound.length > 3) bundles.delete(sameRound[0]);
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
        async function read(url) {
            let response;
            const match = url.match(/^(\/data(?:\/turnos\/2)?\/releases\/[a-f0-9]{32,64})\/(.+)$/);
            const marker = match && markers.get(match[1]);
            if (marker && Object.hasOwn(marker, 'portal') && match[2] !== 'portal.json') {
                const files = await portal(match[1], marker.portal);
                if (!Object.hasOwn(files, match[2])) throw new Error('portal_missing_file');
                response = new Response(JSON.stringify(files[match[2]]), {headers: {'Content-Type': 'application/json'}});
            } else response = await shared(url);
            if (url === namespace(url) + '/version.json' && response.ok) {
                const value = await response.clone().json();
                const context = contexts.get(namespace(url));
                if (context.round === 2 && (value.environment !== 'oficial' || value.round !== 2
                    || !/^[a-f0-9]{64}$/.test(value.snapshot_id || ''))) throw new Error('invalid_round2_marker');
                if (context.round === 1 && (value.round != null && value.round !== 1
                    || value.snapshot_id != null && (typeof value.snapshot_id !== 'string'
                    || !/^[a-f0-9]{32,64}$/.test(value.snapshot_id)))) throw new Error('invalid_round1_marker');
                const checkedAt = Number(response.headers.get('X-Election-Stored-At'));
                if (Number.isFinite(checkedAt)) context.lastMarkerCheck = checkedAt;
                const base = value.snapshot_id ? namespace(url) + '/releases/' + value.snapshot_id : namespace(url);
                if (context.selectedBase !== base || context.activationRevision !== value.activation_revision) {
                    context.markerDetectedAt = new Date(clock()).toISOString();
                    context.markerSnapshotId = value.snapshot_id || null;
                    context.selectedBase = base; context.activationRevision = value.activation_revision;
                    // Existing round-two status consumers retain their public fields.
                    if (context.round === 2) {
                        stats.markerDetectedAt = context.markerDetectedAt;
                        stats.markerSnapshotId = context.markerSnapshotId;
                    }
                }
                if (value.snapshot_id) markers.set(base, value);
                const sameRound = [...markers.keys()].filter(key => namespace(key) === namespace(url));
                if (sameRound.length > 3) {
                    const old = sameRound[0];
                    markers.delete(old); await forgetRelease(old);
                }
            }
            return response;
        }
        async function request(url, init = {}) {
            if (!eligible(url) || init.method && init.method.toUpperCase() !== 'GET') return fetcher(url, init);
            const signal = init.signal;
            if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
            if (!signal) return read(url);
            let abort;
            const aborted = new Promise((_, reject) => {
                abort = () => reject(new DOMException('Aborted', 'AbortError'));
                signal.addEventListener('abort', abort, {once: true});
            });
            // A consumer's cancellation only ends its wait, never a shared fetch.
            try { return await Promise.race([read(url), aborted]); }
            finally { signal.removeEventListener('abort', abort); }
        }
        return {fetch: request, stats, retryAfter,
            setState: (state, base = defaultNamespace) => { contexts.get(namespace(base)).electionState = state; },
            // Consumers must process a marker already fetched by another view.
            shouldPoll: (knownBase, base = knownBase || defaultNamespace) => {
                const context = contexts.get(namespace(base));
                return !!(knownBase && context.selectedBase && knownBase !== context.selectedBase)
                    || context.lastMarkerCheck === null || clock() - context.lastMarkerCheck >= ({official_data_available: 15000,
                    awaiting_official_data: 15000, counting_stable: 10000, counting_finished: 30000}[context.electionState] || 5000);
            },
            paused: () => !!root.document?.hidden || clock() < cooldown()};
    }
    root.LiveData = root.fetch ? create(root.fetch.bind(root)) : null;
    if (typeof module !== 'undefined' && module.exports) module.exports = {create};
})(typeof window !== 'undefined' ? window : globalThis);
