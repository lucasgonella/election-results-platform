/* Shared, immutable publication context. No collection or publication side effects. */
(function (global) {
    "use strict";
    const scopes = new Set("br zz ac al ap am ba ce df es go ma mt ms mg pa pb pr pe pi rj rn rs ro rr sc sp se to".split(" "));
    const slugs = {1: "president", 3: "governor", 5: "senator", 6: "federal-deputy", 7: "state-deputy", 8: "district-deputy"};
    function finite(value) { return typeof value === "number" && Number.isFinite(value); }
    function rowFor(manifest, scope, office) {
        return manifest?.results?.find(row => row.scope === scope && Number(row.office) === Number(office));
    }
    function validateManifest(manifest, round) {
        if (!manifest || !Array.isArray(manifest.results) || !manifest.results.length
            || (round === 2 && manifest.environment !== "oficial")) throw new Error("invalid_public_manifest");
        const inventory = new Set();
        for (const row of manifest.results) {
            const office = Number(row.office);
            if (Number(row.round) !== round || !scopes.has(row.scope) || !slugs[office]
                || row.path !== `${row.scope}/${slugs[office]}.json` || inventory.has(row.path)) {
                throw new Error("mixed_or_invalid_manifest_inventory");
            }
            inventory.add(row.path);
        }
        return manifest;
    }
    function validateResult(result, row, round, environment) {
        if (!row || !result || result.election?.round !== round
            || result.scope?.code !== row.scope || Number(result.office?.code) !== Number(row.office)
            || Number(result.election?.code) !== Number(row.election_code)
            || (environment && result.environment !== environment)
            || !Array.isArray(result.candidates) || result.candidate_count !== result.candidates.length
            || !result.snapshot) throw new Error("result_identity_mismatch");
        for (const [field, key] of [["tse_idg", "tse_idg"], ["captured_at", "captured_at"]]) {
            if (row[key] != null && String(result.snapshot[field]) !== String(row[key])) {
                throw new Error("result_snapshot_mismatch");
            }
        }
        const identities = new Set();
        for (const candidate of result.candidates) {
            const id = String(candidate.tse_candidate_seq ?? "");
            if (!id || identities.has(id)
                || (candidate.votes != null && (!Number.isInteger(candidate.votes) || candidate.votes < 0))
                || (candidate.vote_percentage != null && (!finite(candidate.vote_percentage)
                    || candidate.vote_percentage < 0 || candidate.vote_percentage > 100))) {
                throw new Error("invalid_candidate_data");
            }
            identities.add(id);
        }
        return result;
    }
    function baseFor(version, round) {
        const root = round === 2 ? "/data/turnos/2" : "/data";
        if (!version || version.environment !== "oficial" || typeof version.snapshot_id !== "string"
            || !/^[a-f0-9]{64}$/.test(version.snapshot_id) || (round === 2 && version.round !== 2)) {
            throw new Error("unverified_round_marker");
        }
        return `${root}/releases/${version.snapshot_id}`;
    }
    function candidateColor(number) {
        if (global.ElectoralMap?.candidateColor) return global.ElectoralMap.candidateColor(number);
        const palette = ["#3168ab", "#bd3d66", "#148573", "#8c5ab3", "#b9692c", "#63771b", "#466a85", "#9b4850"];
        if (String(number) === "22") return palette[0];
        if (String(number) === "13") return palette[1];
        let hash = 0;
        for (const char of String(number)) hash = ((hash * 31) + char.charCodeAt(0)) >>> 0;
        return palette[hash % palette.length];
    }
    function csvCell(value) {
        let text = value == null ? "" : String(value);
        if (typeof value === "string" && /^[=+@\-\t\r]/.test(text)) text = "'" + text;
        return '"' + text.replaceAll('"', '""') + '"';
    }
    function createReader(getContext, fetcher = (global.LiveData?.fetch || global.fetch?.bind(global))) {
        const cache = new Map();
        let generation = null;
        return async function loadResult(scope, office = 1, options = {}) {
            const context = getContext();
            const row = rowFor(context.manifest, scope, office);
            if (!row) return null;
            const token = `${context.round}|${context.version?.snapshot_id || context.version?.generated_at || ""}|${context.dataBase}`;
            if (token !== generation) { cache.clear(); generation = token; }
            const key = token + "|" + row.path;
            if (options.signal?.aborted) throw new DOMException("Aborted", "AbortError");
            if (context.result?.scope?.code === scope && Number(context.result?.office?.code) === Number(office)) {
                return validateResult(context.result, row, context.round, context.manifest.environment);
            }
            if (!cache.has(key)) {
                const promise = (async () => {
                    const response = await fetcher(`${context.dataBase}/${row.path}`, {cache: "no-store", signal: options.signal});
                    if (!response.ok) throw new Error(`result_http_${response.status}`);
                    return validateResult(await response.json(), row, context.round, context.manifest.environment);
                })();
                cache.set(key, promise);
                promise.catch(() => { if (cache.get(key) === promise) cache.delete(key); });
            }
            return cache.get(key);
        };
    }
    function install(callbacks) {
        const api = {
            getContext: callbacks.getContext,
            scopeName: callbacks.scopeName,
            getCandidates: callbacks.getCandidates,
            getResultPage: callbacks.getResultPage,
            selectScope: callbacks.selectScope,
            setCandidate: callbacks.setCandidate,
            candidateColor,
            validateResult,
            loadResult: createReader(callbacks.getContext),
            async loadRoundResult(round, scope = "br", office = 1) {
                if (![1, 2].includes(round)) throw new Error("invalid_comparison_round");
                const namespace = round === 2 ? "/data/turnos/2" : "/data";
                const pointerResponse = await (global.LiveData?.fetch || global.fetch.bind(global))(namespace + "/version.json", {cache: "no-store"});
                if (!pointerResponse.ok) return null;
                const pointer = await pointerResponse.json();
                const base = baseFor(pointer, round);
                const manifestResponse = await (global.LiveData?.fetch || global.fetch.bind(global))(base + "/manifest.json", {cache: "no-store"});
                if (!manifestResponse.ok) throw new Error("comparison_manifest_unavailable");
                const manifest = validateManifest(await manifestResponse.json(), round);
                const row = rowFor(manifest, scope, office);
                if (!row) return null;
                const response = await (global.LiveData?.fetch || global.fetch.bind(global))(base + "/" + row.path, {cache: "no-store"});
                if (!response.ok) throw new Error("comparison_result_unavailable");
                const result = validateResult(await response.json(), row, round, manifest.environment);
                return {result, version: pointer, manifest, dataBase: base};
            }
        };
        global.ElectionPortal = api;
        return api;
    }
    const exports = {install, createReader, validateManifest, validateResult, baseFor, rowFor, candidateColor, csvCell, finite};
    global.PortalBridge = exports;
    if (typeof module !== "undefined" && module.exports) module.exports = exports;
})(typeof window !== "undefined" ? window : globalThis);
