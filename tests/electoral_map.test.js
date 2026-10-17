/* Offline synthetic fixtures: never operational election results. */
const test = require("node:test");
const assert = require("node:assert/strict");
const map = require("../web/public/eleicoes/electoral-map.js");
const geography = require("../web/public/eleicoes/brazil-states.js");
const marker = (round = 1, id = "a".repeat(64)) => ({environment: "oficial", snapshot_id: id, round, generated_at: "synthetic-version", activation_revision: "1"});
const item = (round = 1, scope = "ac") => ({round, scope, office: 1, path: scope + "/president.json", election_code: 999, tse_idg: "synthetic-id", captured_at: "synthetic-time"});
const context = (round = 1, id = "a".repeat(64)) => ({round, version: marker(round, id), manifest: {environment: "oficial", results: [item(round)], generated_at: "synthetic-version"}, dataBase: (round === 2 ? "/data/turnos/2" : "/data") + "/releases/" + id});
function result(round = 1, scope = "ac") {
    return {environment: "oficial", election: {round, code: 999}, scope: {code: scope}, office: {code: 1},
        snapshot: {tse_idg: "synthetic-id", captured_at: "synthetic-time", sections: {total: 100, totalized: 40, percentage: 40}, votes: {candidate_valid: 1000, valid: 1000}, electorate: {totalized: 1200}, abstentions: {total: 200}},
        candidates: [{ballot_number: "11", name: "CANDIDATURA SINTÉTICA A", votes: 600, vote_percentage: 60}, {ballot_number: "22", name: "CANDIDATURA SINTÉTICA B", votes: 400, vote_percentage: 40}]};
}
function fakePublication(round = 2, options = {}) {
    const version = marker(round), manifest = {environment: "oficial", results: [item(round)]};
    const root = round === 2 ? "/data/turnos/2" : "/data";
    const urls = []; let versionReads = 0;
    return {urls, fetch: async url => {
        urls.push(url);
        if (url === root + "/version.json") { versionReads++; return {ok: true, json: async () => options.change && versionReads > 1 ? {...version, activation_revision: "2"} : version}; }
        if (url === root + "/releases/" + version.snapshot_id + "/manifest.json") return {ok: true, json: async () => options.mixed ? {...manifest, results: [item(1)]} : options.path ? {...manifest, results: [{...item(round), path: options.path}]} : manifest};
        if (url === root + "/releases/" + version.snapshot_id + "/ac/president.json") return {ok: true, json: async () => result(round)};
        return {ok: false};
    }};
}

test("all 27 official IBGE UFs have unique polygons, proper scope/code and finite projected geometry", () => {
    const expected = {ro: "11", ac: "12", am: "13", rr: "14", pa: "15", ap: "16", to: "17", ma: "21", pi: "22", ce: "23", rn: "24", pb: "25", pe: "26", al: "27", se: "28", ba: "29", mg: "31", es: "32", rj: "33", sp: "35", pr: "41", sc: "42", rs: "43", ms: "50", mt: "51", go: "52", df: "53"};
    assert.equal(geography.states.length, 27);
    assert.equal(new Set(geography.states.map(state => state.scope)).size, 27);
    for (const state of geography.states) {
        assert.equal(state.ibge, expected[state.scope]);
        assert.match(state.d, /^M[0-9.,LZM-]+$/); assert.ok(state.d.endsWith("Z"));
        assert.ok(state.center.every(Number.isFinite)); assert.ok(state.bounds.every(Number.isFinite));
        assert.ok(state.center[0] >= state.bounds[0] && state.center[0] <= state.bounds[2]);
        assert.ok(state.center[1] >= state.bounds[1] && state.center[1] <= state.bounds[3]);
        assert.ok(["n", "ne", "se", "s", "co"].includes(state.region));
    }
    assert.equal(geography.sourceSha256, "07c671aa87aa1ab296c446de6294df9827112782537b996c0a160284907e7c0f");
});

test("the leader is always a voting leader; explicit official finality and full section counts are required", () => {
    const fixture = result();
    let summary = map.summarize(fixture); assert.equal(summary.state, "partial"); assert.equal(summary.leader.id, "11");
    fixture.snapshot.sections.percentage = 100; assert.equal(map.summarize(fixture).state, "partial");
    fixture.snapshot.sections.totalized = 100; assert.equal(map.summarize(fixture).state, "partial");
    fixture.snapshot.totalization_final = false; assert.equal(map.summarize(fixture).state, "partial");
    fixture.snapshot.totalization_final = null; assert.equal(map.summarize(fixture).state, "partial");
    fixture.snapshot.totalization_final = true; assert.equal(map.summarize(fixture).state, "consolidated");
    fixture.snapshot.sections.total = null; assert.equal(map.summarize(fixture).state, "partial");
    fixture.candidates[0].elected = true; assert.equal(map.summarize(fixture).state, "partial");
});

test("candidate rosters and zero voting remain neutral with no artificial leader or share", () => {
    const fixture = result(2); fixture.candidates.forEach(candidate => { candidate.votes = 0; candidate.vote_percentage = 0; });
    fixture.snapshot.sections.totalized = 0; fixture.snapshot.votes.candidate_valid = 0;
    const summary = map.summarize(fixture);
    assert.equal(summary.state, "waiting"); assert.equal(summary.leader, null);
    for (const mode of ["leader", "share", "margin", "abstention", "compare"]) assert.equal(map.metric(summary, mode, "11", summary), null);
});

test("ties are neutral for leadership and retain the documented zero margin", () => {
    const fixture = result(); fixture.candidates.forEach(candidate => candidate.votes = 500);
    const summary = map.summarize(fixture); assert.equal(summary.state, "tie"); assert.equal(summary.leader, null);
    assert.equal(summary.consolidation, "partial");
    fixture.snapshot.sections.totalized = 100; fixture.snapshot.totalization_final = true;
    assert.equal(map.summarize(fixture).state, "tie"); assert.equal(map.summarize(fixture).consolidation, "consolidated");
    assert.equal(map.metric(summary, "leader"), null); assert.equal(summary.margin, 0); assert.equal(map.shareFor(summary, "11"), 50);
});

test("the share, vote margin and abstention use separate official denominators", () => {
    const summary = map.summarize(result());
    assert.equal(map.shareFor(summary, "11"), 60); assert.equal(map.metric(summary, "margin"), 20);
    assert.ok(Math.abs(map.metric(summary, "abstention") - 200 / 1200 * 100) < 1e-12);
    assert.equal(map.shareFor(summary, "candidate-that-is-absent"), null);
    const noDenominator = result(); delete noDenominator.snapshot.votes;
    assert.equal(map.shareFor(map.summarize(noDenominator), "11"), 60); assert.equal(map.summarize(noDenominator).margin, null);
    delete noDenominator.candidates[0].vote_percentage; assert.equal(map.shareFor(map.summarize(noDenominator), "11"), null);
});

test("invalid values and contradictory totals cannot create an apparent leader", () => {
    for (const mutate of [
        fixture => fixture.candidates[0].votes = null,
        fixture => fixture.candidates[0].votes = -1,
        fixture => fixture.candidates[0].votes = NaN,
        fixture => fixture.candidates[0].votes = 1.1,
        fixture => fixture.candidates[0].votes = false,
        fixture => fixture.candidates[0].votes = "   ",
        fixture => fixture.snapshot.votes.candidate_valid = 0,
        fixture => fixture.snapshot.sections.totalized = 101,
        fixture => fixture.candidates[1].ballot_number = "11"
    ]) { const fixture = result(); mutate(fixture); const summary = map.summarize(fixture); assert.equal(summary.state, "invalid"); assert.equal(summary.leader, null); assert.equal(map.metric(summary, "share", "11"), null); }
    const fixture = result(); fixture.snapshot.electorate.totalized = null;
    assert.equal(map.summarize(fixture).abstention, null);
});

test("comparison is a derived share difference for a present candidature in both rounds", () => {
    const current = result(2), other = result(1); current.candidates[0].votes = 700; current.candidates[1].votes = 300;
    assert.equal(map.difference(map.summarize(current), map.summarize(other), "11"), 10);
    other.candidates[0].name = "OUTRA PESSOA COM O MESMO NÚMERO"; assert.equal(map.difference(map.summarize(current), map.summarize(other), "11"), null);
    other.candidates[0].ballot_number = "33"; assert.equal(map.difference(map.summarize(current), map.summarize(other), "11"), null);
});

test("the result must match round, UF, office, election and both pinned snapshot identifiers", () => {
    assert.equal(map.verifyResult(result(), item(), 1).scope.code, "ac");
    for (const mutate of [
        fixture => fixture.election.round = 2,
        fixture => fixture.scope.code = "go",
        fixture => fixture.office.code = 3,
        fixture => fixture.election.code = 998,
        fixture => fixture.snapshot.tse_idg = "changed",
        fixture => fixture.snapshot.captured_at = "changed",
        fixture => fixture.environment = "simulado"
    ]) { const fixture = result(); mutate(fixture); assert.throws(() => map.verifyResult(fixture, item(), 1), /map_result_/); }
    assert.throws(() => map.verifyResult(result(2), item(1), 2), /mismatch/);
});

test("immutable comparison context must belong to the selected round, with no legacy fallback", () => {
    assert.equal(map.hasPinnedContext(context(1)), true); assert.equal(map.hasPinnedContext(context(2)), true);
    assert.equal(map.hasPinnedContext({...context(2), dataBase: context(1).dataBase}), false);
    assert.equal(map.hasPinnedContext({...context(2), version: {...marker(2), round: 1}}), false);
    assert.equal(map.hasPinnedContext({...context(1), dataBase: "/data"}), false);
});

test("state loads are cached only within one publication and failed reads can be retried", async () => {
    let calls = 0, fail = true;
    const loader = new map.PinnedContextLoader(async () => { calls++; if (fail) throw new Error("network"); return result(); });
    loader.reset(context()); await assert.rejects(loader.get("ac"), /network/); fail = false;
    const values = await Promise.all([loader.get("ac"), loader.get("ac")]); assert.equal(values.length, 2); assert.equal(calls, 2);
    await loader.get("ac"); assert.equal(calls, 2);
    loader.reset(context(1, "b".repeat(64))); await loader.get("ac"); assert.equal(calls, 3);
});

test("a turn change aborts old requests and rejects late responses, even if transport ignores AbortSignal", async () => {
    let finish, signal;
    const loader = new map.PinnedContextLoader((scope, office, options) => { signal = options.signal; return new Promise(resolve => { finish = resolve; }); });
    loader.reset(context(1)); const pending = loader.get("ac"); await Promise.resolve();
    loader.reset(context(2)); assert.equal(signal.aborted, true); finish(result(1));
    await assert.rejects(pending, error => error.name === "AbortError");
    assert.equal(loader.cache.size, 0);
});

test("round two comparison reader uses its independent marker and immutable root exclusively", async () => {
    const fake = fakePublication(2); const reader = await map.loadPinnedRound(2, fake.fetch); const data = await reader.read("ac");
    assert.equal(data.election.round, 2); assert.equal(fake.urls.filter(url => url.endsWith("version.json")).length, 2);
    assert.ok(fake.urls.every(url => url.startsWith("/data/turnos/2/")));
});

test("comparison defaults to the shared HTTP reader and reuses parallel component reads", async () => {
    const originalLiveData = global.LiveData, originalFetch = global.fetch;
    try {
        const {create} = require("../web/public/eleicoes/live-data.js");
        const fake = fakePublication(2); let time = 10000;
        const shared = create(async url => {
            const response = await fake.fetch(url);
            return new Response(response.ok ? JSON.stringify(await response.json()) : "", {status: response.ok ? 200 : 404});
        }, {clock: () => time, sleep: async ms => {time += ms;}, spacingMs: 0, random: () => 0});
        global.LiveData = shared;
        global.fetch = () => {throw new Error("comparison_bypassed_shared_reader");};
        const root = "/data/turnos/2", base = root + "/releases/" + marker(2).snapshot_id;
        const [a, b] = await Promise.all([map.loadPinnedRound(2), map.loadPinnedRound(2), shared.fetch(root + "/version.json")]);
        const values = await Promise.all([a.read("ac"), b.read("ac"), shared.fetch(base + "/ac/president.json")]);
        assert.equal(values[0].election.round, 2); assert.equal(values[1].election.round, 2);
        assert.deepEqual(fake.urls, [root + "/version.json", base + "/manifest.json", base + "/ac/president.json"]);
        assert.equal(shared.stats.network, 3);
    } finally {global.LiveData = originalLiveData; global.fetch = originalFetch;}
});

test("comparison retains injected fetchers and the fallback without LiveData", async () => {
    const originalLiveData = global.LiveData, originalFetch = global.fetch;
    try {
        global.LiveData = {fetch: () => {throw new Error("unexpected_shared_reader");}};
        global.fetch = () => {throw new Error("unexpected_native_fetch");};
        const injected = fakePublication(2), a = await map.loadPinnedRound(2, injected.fetch);
        assert.equal((await a.read("ac")).election.round, 2);
        global.LiveData = null;
        const fallback = fakePublication(1); global.fetch = fallback.fetch;
        const b = await map.loadPinnedRound(1);
        assert.equal((await b.read("ac")).election.round, 1);
        assert.ok(fallback.urls.every(url => url.startsWith("/data/") && !url.startsWith("/data/turnos/")));
    } finally {global.LiveData = originalLiveData; global.fetch = originalFetch;}
});

test("comparison rejects a changed activation, a mixed-turn manifest and an unsafe path", async () => {
    for (const options of [{change: true}, {mixed: true}]) { const fake = fakePublication(2, options); await assert.rejects(map.loadPinnedRound(2, fake.fetch), /map_comparison_/); }
    const fake = fakePublication(2, {path: "../ac/president.json"}); const reader = await map.loadPinnedRound(2, fake.fetch);
    const before = fake.urls.length; await assert.rejects(reader.read("ac"), /scope_unavailable/); assert.equal(fake.urls.length, before);
});

test("aborted comparison performs no requests", async () => {
    const controller = new AbortController(); controller.abort(); let calls = 0;
    await assert.rejects(map.loadPinnedRound(2, async () => { calls++; }, controller.signal), error => error.name === "AbortError"); assert.equal(calls, 0);
});

test("candidate colors are stable across UFs/turns and readable with white labels", () => {
    const colors = new Set();
    for (const id of ["11", "13", "15", "18", "22", "30", "40", "45", "50", "70"]) {
        const color = map.candidateColor(id); assert.match(color, /^#[0-9a-f]{6}$/); assert.equal(color, map.candidateColor(id)); colors.add(color);
        const rgb = [1, 3, 5].map(index => parseInt(color.slice(index, index + 2), 16) / 255);
        const linear = rgb.map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
        const luminance = linear.reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
        assert.ok(1.05 / (luminance + .05) >= 4.5, `label contrast for ${id}`);
    }
    assert.equal(colors.size, 10);
});
