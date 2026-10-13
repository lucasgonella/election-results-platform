/* Geography is illustrative; election classifications use only validated UF results. */
(function (root) {
    "use strict";
    function candidateColor(id) {
        const text = String(id ?? "");
        let seed = /^\d{1,4}$/.test(text) ? Number(text) : 0;
        if (!/^\d{1,4}$/.test(text)) for (const character of text) seed = (seed * 31 + character.charCodeAt(0)) >>> 0;
        const hue = (seed * 137.508) % 360 / 60, saturation = .55, lightness = .37;
        const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation, x = chroma * (1 - Math.abs(hue % 2 - 1)), m = lightness - chroma / 2;
        const parts = hue < 1 ? [chroma, x, 0] : hue < 2 ? [x, chroma, 0] : hue < 3 ? [0, chroma, x] : hue < 4 ? [0, x, chroma] : hue < 5 ? [x, 0, chroma] : [chroma, 0, x];
        let rgb = parts.map(value => value + m);
        const luminance = values => values.map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
        while (luminance(rgb) > .18) rgb = rgb.map(value => value * .94);
        return "#" + rgb.map(value => Math.round(value * 255).toString(16).padStart(2, "0")).join("");
    }
    const MODES = new Set(["leader", "share", "margin", "abstention", "compare"]);
    const numeric = value => typeof value === "number" || typeof value === "string" && /^\d+(?:\.\d+)?$/.test(value);
    const integer = value => numeric(value) && Number.isSafeInteger(Number(value)) && Number(value) >= 0 ? Number(value) : null;
    const percent = value => numeric(value) && Number.isFinite(Number(value)) && Number(value) >= 0 && Number(value) <= 100 ? Number(value) : null;
    const candidateId = candidate => String(candidate?.ballot_number ?? candidate?.tse_candidate_seq ?? "");
    const candidateName = candidate => candidate?.ballot_name || candidate?.name || "Candidatura sem nome informado";
    const numberFormat = new Intl.NumberFormat("pt-BR");
    const percentageFormat = new Intl.NumberFormat("pt-BR", {minimumFractionDigits: 2, maximumFractionDigits: 2});
    const number = value => value == null ? "—" : numberFormat.format(value);
    const percentage = value => value == null ? "—" : percentageFormat.format(value) + "%";
    const normalize = text => String(text ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
    function publicationKey(context) {
        const marker = context?.version;
        return JSON.stringify([Number(context?.round), context?.dataBase,
            typeof marker === "object" ? [marker?.snapshot_id, marker?.generated_at, marker?.activation_revision] : marker,
            context?.manifest?.generated_at]);
    }
    function abortError() { const error = new Error("A consulta foi substituída por uma publicação mais recente."); error.name = "AbortError"; return error; }
    function verifyResult(result, item, round) {
        if (!result || !item || Number(item.round) !== Number(round)
            || Number(result.election?.round) !== Number(round)
            || String(result.scope?.code).toLowerCase() !== String(item.scope).toLowerCase()
            || Number(result.office?.code) !== 1 || Number(item.office) !== 1
            || (item.election_code != null && String(result.election?.code) !== String(item.election_code))
            || !Array.isArray(result.candidates) || !result.snapshot) {
            throw new Error("map_result_context_mismatch");
        }
        for (const key of ["tse_idg", "captured_at"]) {
            if (item[key] != null && String(result.snapshot[key]) !== String(item[key])) throw new Error("map_result_snapshot_mismatch");
        }
        if (result.environment && result.environment !== "oficial") throw new Error("map_result_not_official");
        return result;
    }
    function summarize(result) {
        if (!result || !Array.isArray(result.candidates)) return {state: "unavailable", candidates: [], leader: null, second: null, valid: null, margin: null, abstention: null};
        const sections = result.snapshot?.sections || {};
        const totalized = integer(sections.totalized), total = integer(sections.total);
        const consolidation = result.snapshot?.totalization_final === true && total != null && total > 0 && totalized === total ? "consolidated" : "partial";
        const candidates = result.candidates.map(candidate => ({...candidate, id: candidateId(candidate), votes: integer(candidate.votes)}));
        const valid = integer(result.snapshot?.votes?.candidate_valid) ?? integer(result.snapshot?.votes?.valid);
        const sorted = candidates.slice().sort((a, b) => (b.votes ?? -1) - (a.votes ?? -1) || a.id.localeCompare(b.id));
        const leader = sorted[0] ?? null, second = sorted[1] ?? null;
        const candidateVotes = candidates.reduce((sum, candidate) => sum + (candidate.votes ?? 0), 0);
        const invalid = candidates.some(candidate => candidate.votes == null || !candidate.id)
            || new Set(candidates.map(candidate => candidate.id)).size !== candidates.length
            || (valid != null && candidateVotes > valid)
            || (total != null && totalized != null && totalized > total);

        const state = invalid ? "invalid" : !leader || leader.votes === 0 || totalized === 0 ? "waiting"
            : second && leader.votes === second.votes ? "tie" : consolidation;
        const denominator = valid != null && valid > 0 && candidateVotes <= valid ? valid : null;
        const margin = denominator && leader && second ? (leader.votes - second.votes) / denominator * 100 : null;
        const abstentions = integer(result.snapshot?.abstentions?.total);
        const electorate = integer(result.snapshot?.electorate?.totalized);
        const abstention = totalized != null && totalized > 0 && electorate != null && electorate > 0 && abstentions != null && abstentions <= electorate ? abstentions / electorate * 100 : null;
        return {state, consolidation, candidates: sorted, leader: ["partial", "consolidated"].includes(state) ? leader : null, second, valid: denominator,
            margin, abstention, sections: percent(sections.percentage), totalized, total,
            update: result.snapshot?.generated_at || result.snapshot?.captured_at, round: Number(result.election?.round)};
    }
    function shareFor(summary, id) {
        if (!summary || ["invalid", "waiting", "unavailable"].includes(summary.state)) return null;
        const candidate = summary.candidates.find(candidate => candidate.id === String(id));
        if (!candidate || candidate.votes == null) return null;
        if (summary.valid) return candidate.votes / summary.valid * 100;
        return percent(candidate.vote_percentage);
    }
    function difference(current, other, id) {
        const aCandidate = current?.candidates?.find(candidate => candidate.id === String(id));
        const bCandidate = other?.candidates?.find(candidate => candidate.id === String(id));
        const sameSequence = aCandidate?.tse_candidate_seq != null && bCandidate?.tse_candidate_seq != null && String(aCandidate.tse_candidate_seq) === String(bCandidate.tse_candidate_seq);
        const sameNamedCandidate = aCandidate && bCandidate && normalize(aCandidate.name || aCandidate.ballot_name)
            && normalize(aCandidate.name || aCandidate.ballot_name) === normalize(bCandidate.name || bCandidate.ballot_name)
            && normalize(aCandidate.party_acronym) === normalize(bCandidate.party_acronym);
        if (!sameSequence && !sameNamedCandidate) return null;
        const a = shareFor(current, id), b = shareFor(other, id);
        return a == null || b == null ? null : a - b;
    }
    function metric(summary, mode, id, other) {
        if (!summary || ["invalid", "waiting", "unavailable"].includes(summary.state)) return null;
        if (mode === "share") return shareFor(summary, id);
        if (mode === "margin") return summary.margin;
        if (mode === "abstention") return summary.abstention;
        if (mode === "compare") return difference(summary, other, id);
        return summary.leader?.id ?? null;
    }
    class PinnedContextLoader {
        constructor(read) { this.read = read; this.cache = new Map(); this.revision = 0; }
        reset(context) {
            this.controller?.abort(); this.controller = new AbortController(); this.revision++;
            this.cache.clear(); this.context = {...context};
            this.rows = new Map((context?.manifest?.results || []).filter(row => Number(row.office) === 1).map(row => [String(row.scope).toLowerCase(), {...row}]));
        }
        async get(scope) {
            scope = String(scope).toLowerCase();
            if (this.cache.has(scope)) return this.cache.get(scope);
            const item = this.rows.get(scope), revision = this.revision, round = this.context?.round;
            if (!item) throw new Error("map_scope_unavailable");
            const signal = this.controller.signal;
            const promise = Promise.resolve().then(() => {
                if (signal.aborted) throw abortError();
                return this.read(scope, 1, {signal});
            }).then(result => {
                if (signal.aborted || revision !== this.revision) throw abortError();
                return verifyResult(result, item, round);
            }).catch(error => { if (revision === this.revision && this.cache.get(scope) === promise) this.cache.delete(scope); if (signal.aborted || revision !== this.revision) throw abortError(); throw error; });
            this.cache.set(scope, promise);
            return promise;
        }
    }
    function hasPinnedContext(context) {
        const round = Number(context?.round), marker = context?.version, dataRoot = round === 2 ? "/data/turnos/2" : "/data";
        return [1, 2].includes(round) && marker?.environment === "oficial" && /^[a-f0-9]{32,64}$/.test(marker.snapshot_id || "")
            && context.dataBase === dataRoot + "/releases/" + marker.snapshot_id
            && (marker.round == null ? round === 1 : Number(marker.round) === round);
    }
    async function loadPinnedRound(round, fetcher, signal) {
        if (![1, 2].includes(Number(round))) throw new Error("map_round_invalid");
        const dataRoot = Number(round) === 2 ? "/data/turnos/2" : "/data";
        async function json(url) {
            if (signal?.aborted) throw abortError();
            const response = await fetcher(url, {cache: "no-store", signal});
            if (!response.ok) throw new Error("map_comparison_unavailable");
            const value = await response.json();
            if (signal?.aborted) throw abortError();
            return value;
        }
        const version = await json(dataRoot + "/version.json");
        if (version.environment !== "oficial" || !/^[a-f0-9]{32,64}$/.test(version.snapshot_id || "")
            || (version.round != null && Number(version.round) !== Number(round))
            || (Number(round) === 2 && Number(version.round) !== 2)) throw new Error("map_comparison_marker_invalid");
        const dataBase = dataRoot + "/releases/" + version.snapshot_id;
        const manifest = await json(dataBase + "/manifest.json");
        if (manifest.environment !== "oficial" || !Array.isArray(manifest.results) || !manifest.results.length
            || manifest.results.some(row => Number(row.round) !== Number(round))) throw new Error("map_comparison_manifest_invalid");
        const confirmed = await json(dataRoot + "/version.json");
        if (publicationKey({round, dataBase, version, manifest}) !== publicationKey({round, dataBase, version: confirmed, manifest})
            || confirmed.environment !== "oficial" || (Number(round) === 2 && Number(confirmed.round) !== 2)) throw new Error("map_comparison_changed");
        const read = async scope => {
            const item = manifest.results.find(row => String(row.scope).toLowerCase() === scope && Number(row.office) === 1);
            if (!item || !/^[a-z]{2}$/.test(scope) || item.path !== scope + "/president.json") throw new Error("map_comparison_scope_unavailable");
            return verifyResult(await json(dataBase + "/" + item.path), item, round);
        };
        return {round, version, manifest, dataBase, read};
    }
    const api = {summarize, shareFor, difference, metric, verifyResult, publicationKey, candidateId, candidateColor, hasPinnedContext, PinnedContextLoader, loadPinnedRound};
    if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
    root.ElectoralMap = api;
    if (!root.document) return;
    const document = root.document;
    const SVG_NS = "http://www.w3.org/2000/svg";
    const el = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; };
    const svgEl = (tag, attributes = {}) => { const node = document.createElementNS(SVG_NS, tag); for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value); return node; };
    const statusText = summary => summary?.state === "tie" ? `Empate · ${summary.consolidation === "consolidated" ? "totalização final" : "apuração parcial"}`
        : ({waiting: "Aguardando apuração", partial: "Apuração parcial", consolidated: "Totalização final TSE", unavailable: "Dados não publicados", invalid: "Dados incompatíveis"}[summary?.state] || "Dados não publicados");
    const date = value => { const parsed = new Date(value); return value && Number.isFinite(parsed.getTime()) ? parsed.toLocaleString("pt-BR", {timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"}) : "Não informada"; };
    function blend(hex, amount) {
        const channel = offset => Math.round(238 + (parseInt(hex.slice(offset, offset + 2), 16) - 238) * Math.max(.12, Math.min(1, amount))).toString(16).padStart(2, "0");
        return "#" + channel(1) + channel(3) + channel(5);
    }
    class ElectoralMapView {
        constructor(mount, geography, portal) {
            this.mount = mount; this.geography = geography; this.portal = portal;
            this.states = geography.states; this.paths = new Map(); this.summaries = new Map(); this.errors = new Set(); this.failures = new Set(); this.catalog = new Map(); this.colors = new Map();
            const params = new URLSearchParams(root.location.search);
            this.mode = MODES.has(params.get("mapa")) ? params.get("mapa") : "leader";
            this.region = ["n", "ne", "se", "s", "co"].includes(params.get("regiao")) ? params.get("regiao") : "";
            this.candidate = params.get("candidate") || ""; this.view = params.get("vista") === "table" ? "table" : "map";
            this.loader = new PinnedContextLoader((...args) => this.portal.loadResult(...args));
            this.build(); this.bind(); this.setContext(this.portal.getContext());
            document.addEventListener("election:context", event => this.setContext(event.detail || this.portal.getContext()));
        }
        build() {
            this.mount.classList.add("electoral-map");
            this.mount.innerHTML = `<section class="emap-section" aria-labelledby="emap-title">
                <div class="emap-heading"><div><p class="emap-eyebrow">TERRITÓRIO ELEITORAL</p><h2 id="emap-title">O voto em cada estado.</h2><p class="emap-intro">Explore os resultados presidenciais pelo Brasil. Uma leitura geográfica, sempre com a fonte à vista.</p></div><div class="emap-level" role="group" aria-label="Nível geográfico"><button type="button" aria-pressed="true">Estados</button><button type="button" disabled aria-describedby="emap-municipal-note">Municípios <span>Em espera</span></button></div></div>
                <details class="emap-filters" id="emap-filters" open><summary class="emap-filter-toggle">Filtros do mapa <span>Personalize a leitura</span></summary><div class="emap-toolbar"><label class="emap-search"><span>Encontrar um estado</span><input id="emap-search" type="search" placeholder="Nome ou sigla da UF" list="emap-state-list" autocomplete="off"><datalist id="emap-state-list"></datalist></label><label><span>Região</span><select id="emap-region"><option value="">Todo o Brasil</option><option value="n">Norte</option><option value="ne">Nordeste</option><option value="co">Centro-Oeste</option><option value="se">Sudeste</option><option value="s">Sul</option></select></label><label><span>Leitura do mapa</span><select id="emap-mode"><option value="leader">Mais votado na UF</option><option value="share">Percentual do candidato</option><option value="margin">Diferença entre os líderes</option><option value="abstention">Abstenção</option><option value="compare">Comparar turnos</option></select></label><label><span>Candidato</span><select id="emap-candidate"><option value="">Todos os candidatos</option></select></label><div class="emap-view-switch" role="group" aria-label="Forma de visualizar"><button id="emap-map-view" type="button" aria-pressed="true">Mapa</button><button id="emap-table-view" type="button" aria-pressed="false">Tabela</button></div></div></details>
                <div class="emap-status" id="emap-status" role="status" aria-live="polite">Aguardando a publicação oficial…</div>
                <div class="emap-workspace"><div class="emap-visual"><div id="emap-canvas" class="emap-canvas"><div class="emap-map-caption"><span>BRASIL</span><span id="emap-round-label"></span></div><svg id="emap-svg" viewBox="0 0 820 740" role="group" aria-label="Mapa interativo dos resultados presidenciais por unidade da federação" aria-describedby="emap-keyboard-help"></svg><div class="emap-zoom" role="group" aria-label="Navegação do mapa"><button id="emap-zoom-in" type="button" aria-label="Ampliar mapa">+</button><button id="emap-zoom-out" type="button" aria-label="Reduzir mapa">−</button><button id="emap-reset" type="button" aria-label="Redefinir visão do mapa">↺</button></div><p id="emap-keyboard-help" class="emap-sr">Use Tab para acessar o mapa, setas para navegar entre estados e Enter ou Espaço para selecionar. Use os botões para ampliar e reduzir.</p><div id="emap-tooltip" class="emap-tooltip" role="tooltip" hidden></div></div><div id="emap-table" class="emap-table-wrap" hidden></div><div id="emap-legend" class="emap-legend" aria-label="Legenda do mapa"></div><p id="emap-method" class="emap-method"></p></div><aside id="emap-detail" class="emap-detail" aria-label="Detalhes do estado selecionado"></aside></div>
                <div class="emap-footnotes"><p id="emap-municipal-note"><strong>Municípios em espera.</strong> O conjunto oficial publicado neste portal contém resultados nacionais e por UF. Resultados municipais serão exibidos quando houver uma publicação própria validada; dados estaduais nunca são usados como substitutos.</p><p>Resultados: <a href="https://resultados.tse.jus.br/" target="_blank" rel="noopener">TSE</a>. Limites: <a href="https://servicodados.ibge.gov.br/api/docs/malhas?versao=3" target="_blank" rel="noopener">IBGE</a>, malha simplificada. Projeto independente, sem projeções.</p></div></section>`;
            this.find = id => this.mount.querySelector("#" + id);
            if (root.matchMedia?.("(max-width: 600px)").matches) this.find("emap-filters").open = false;
            this.svg = this.find("emap-svg"); this.group = svgEl("g"); this.svg.append(this.group);
            this.pathLayer = svgEl("g"); this.labelLayer = svgEl("g", {"aria-hidden": "true"}); this.group.append(this.pathLayer, this.labelLayer);
            const list = this.find("emap-state-list");
            const callouts = {df: [570, 383], rn: [780, 220], pb: [780, 248], pe: [780, 275], al: [780, 301], se: [780, 328], es: [676, 468], rj: [655, 526]};
            for (const state of this.states) {
                const option = el("option"); option.value = state.name; option.label = state.scope.toUpperCase(); list.append(option);
                const path = svgEl("path", {d: state.d, "data-scope": state.scope, "data-ibge": state.ibge, class: "emap-state", role: "button", tabindex: "-1", "aria-label": state.name, "aria-pressed": "false", fill: "#d7dfe5", "fill-rule": "evenodd"});
                const title = svgEl("title"); title.textContent = state.name; path.append(title); this.pathLayer.append(path);
                const position = callouts[state.scope] || state.center;
                let callout;
                if (callouts[state.scope]) {
                    callout = svgEl("path", {d: `M${state.center[0]},${state.center[1]}L${position[0] - 12},${position[1]}`, class: "emap-callout", fill: "none"}); this.labelLayer.append(callout);
                }
                const label = svgEl("text", {x: position[0], y: position[1], class: callout ? "emap-state-label emap-callout-label" : "emap-state-label", "aria-hidden": "true"}); label.textContent = state.scope.toUpperCase(); this.labelLayer.append(label);
                this.paths.set(state.scope, {path, label, title, callout});
                path.addEventListener("click", () => { if (!this.dragged) this.select(state.scope); });
                path.addEventListener("keydown", event => this.onMapKey(event, state));
                path.addEventListener("pointerenter", event => this.tooltip(state, event));
                path.addEventListener("pointerleave", () => { this.find("emap-tooltip").hidden = true; });
                path.addEventListener("focus", () => { this.rovingScope = state.scope; this.updateTabindex(); });
            }
            this.rovingScope = "am"; this.updateTabindex(); this.viewport = [0, 0, 820, 740]; this.updateLabels();
            if (root.ResizeObserver) { this.resizeObserver = new root.ResizeObserver(() => this.updateLabels()); this.resizeObserver.observe(this.svg); }
        }
        updateTabindex() { for (const [scope, nodes] of this.paths) nodes.path.setAttribute("tabindex", scope === this.rovingScope ? "0" : "-1"); }
        bind() {
            this.find("emap-region").value = this.region; this.find("emap-mode").value = this.mode;
            this.find("emap-region").addEventListener("change", event => { this.region = event.target.value; this.fitRegion(); this.render(); this.updateUrl(); });
            this.find("emap-mode").addEventListener("change", async event => {
                this.mode = event.target.value;
                if (["share", "compare"].includes(this.mode) && !this.candidate && this.catalog.size) this.setCandidate(this.catalog.keys().next().value);
                this.render(); this.updateUrl(); if (this.mode === "compare") await this.loadComparison();
            });
            this.find("emap-candidate").addEventListener("change", event => this.setCandidate(event.target.value));
            const search = this.find("emap-search");
            const selectSearch = () => { const value = normalize(search.value); const match = this.states.find(state => normalize(state.name) === value || state.scope === value); if (match) { this.region = ""; this.find("emap-region").value = ""; this.select(match.scope); this.fitState(match); } };
            search.addEventListener("input", () => { this.query = normalize(search.value); this.paint(); });
            search.addEventListener("change", selectSearch); search.addEventListener("keydown", event => { if (event.key === "Enter") selectSearch(); if (event.key === "Escape") { search.value = ""; this.query = ""; this.paint(); } });
            this.find("emap-map-view").addEventListener("click", () => { this.view = "map"; this.render(); this.updateUrl(); });
            this.find("emap-table-view").addEventListener("click", () => { this.view = "table"; this.render(); this.updateUrl(); });
            this.find("emap-zoom-in").addEventListener("click", () => this.zoom(.72)); this.find("emap-zoom-out").addEventListener("click", () => this.zoom(1.38));
            this.find("emap-reset").addEventListener("click", () => { this.region = ""; this.query = ""; search.value = ""; this.find("emap-region").value = ""; this.viewport = [0, 0, 820, 740]; this.applyViewport(); this.render(); this.updateUrl(); });
            this.svg.addEventListener("wheel", event => { if (event.ctrlKey || event.metaKey) { event.preventDefault(); this.zoom(event.deltaY > 0 ? 1.12 : .88); } }, {passive: false});
            this.svg.addEventListener("pointerdown", event => {
                if (event.button !== 0) return; this.dragged = false; this.drag = {x: event.clientX, y: event.clientY, box: this.viewport.slice(), pointer: event.pointerId};
            });
            this.svg.addEventListener("pointermove", event => {
                if (!this.drag || this.drag.pointer !== event.pointerId) return;
                const dx = event.clientX - this.drag.x, dy = event.clientY - this.drag.y;
                if (Math.hypot(dx, dy) < 6 && !this.dragged) return;
                this.dragged = true; this.svg.setPointerCapture?.(event.pointerId); this.find("emap-tooltip").hidden = true;
                const scale = this.svg.clientWidth / this.drag.box[2]; this.viewport = [this.drag.box[0] - dx / scale, this.drag.box[1] - dy / scale, this.drag.box[2], this.drag.box[3]]; this.applyViewport();
            });
            const stopDrag = () => { this.drag = null; root.setTimeout(() => { this.dragged = false; }, 0); };
            this.svg.addEventListener("pointerup", stopDrag); this.svg.addEventListener("pointercancel", stopDrag);
        }
        async setContext(context) {
            if (!context) return;
            this.context = context; this.selected = this.states.some(state => state.scope === String(context.scope).toLowerCase()) ? String(context.scope).toLowerCase() : "";
            if (context.candidate != null) this.candidate = String(context.candidate);
            const key = publicationKey(context);
            if (key === this.key) { this.render(); return; }
            this.key = key; this.loader.reset(context); this.summaries.clear(); this.errors.clear(); this.failures.clear(); this.catalog.clear(); this.comparison = null; this.comparisonKey = null; this.comparisonController?.abort(); this.comparing = false; this.comparisonError = false;
            this.loading = true; this.render();
            const rows = context.manifest?.results;
            if (!context.version || context.manifest?.environment !== "oficial" || !Array.isArray(rows) || rows.some(row => Number(row.round) !== Number(context.round))) {
                this.loading = false; this.render(); return;
            }
            const pending = ["br", ...this.states.map(state => state.scope)];
            const worker = async () => {
                while (pending.length && key === this.key) {
                    const scope = pending.shift();
                    try { const result = await this.loader.get(scope); if (key !== this.key) return; this.summaries.set(scope, summarize(result)); }
                    catch (error) { if (error.name === "AbortError" || key !== this.key) return; this.errors.add(scope); if (error.message !== "map_scope_unavailable") this.failures.add(scope); }
                }
            };
            await Promise.all(Array.from({length: 4}, worker));
            if (key !== this.key) return;
            this.loading = false;
            const national = this.summaries.get("br");
            for (const summary of [national, ...this.summaries.values()].filter(Boolean)) for (const candidate of summary.candidates) if (!this.catalog.has(candidate.id)) this.catalog.set(candidate.id, candidate);
            const ordered = [...this.catalog.entries()].sort((a, b) => Number(a[0]) - Number(b[0]));
            this.catalog = new Map(ordered); this.colors.clear(); ordered.forEach(([id]) => this.colors.set(id, candidateColor(id)));
            if (this.candidate && !this.catalog.has(this.candidate)) { this.candidate = ""; this.portal.setCandidate?.(""); this.updateUrl(); }
            this.render(); if (this.mode === "compare") await this.loadComparison();
        }
        async loadComparison() {
            if (this.comparisonKey === this.key && this.comparison) return;
            if (this.comparing) return;
            const key = this.key; this.comparing = true; this.comparisonError = false; this.comparisonController?.abort(); this.comparisonController = new AbortController();
            this.render();
            try {
                if (!hasPinnedContext(this.context)) throw new Error("map_current_snapshot_not_pinned");
                // Comparison is explicit, and the other round has its own immutable pointer.
                const other = await loadPinnedRound(Number(this.context.round) === 2 ? 1 : 2, root.fetch.bind(root), this.comparisonController.signal);
                const pending = this.states.map(state => state.scope); const values = new Map();
                const worker = async () => { while (pending.length && key === this.key) { const scope = pending.shift(); try { values.set(scope, summarize(await other.read(scope))); } catch (error) { if (error.name === "AbortError") throw error; } } };
                await Promise.all(Array.from({length: 4}, worker));
                if (key === this.key) { this.comparison = values; this.comparisonKey = key; }
            } catch (error) { if (key === this.key && error.name !== "AbortError") this.comparisonError = true; }
            finally { if (key === this.key) { this.comparing = false; this.render(); } }
        }
        setCandidate(id) { this.candidate = String(id || ""); this.portal.setCandidate?.(this.candidate); this.render(); this.updateUrl(); }
        select(scope) {
            this.selected = scope; this.rovingScope = scope; this.updateTabindex(); this.render();
            Promise.resolve(this.portal.selectScope(scope, 1)).catch(() => { this.find("emap-status").textContent = "Não foi possível abrir o resultado deste estado. Tente novamente."; });
        }
        updateUrl() {
            const url = new URL(root.location.href);
            for (const [key, value] of [["mapa", this.mode === "leader" ? "" : this.mode], ["regiao", this.region], ["candidate", this.candidate], ["vista", this.view === "table" ? "table" : ""]]) {
                if (value) url.searchParams.set(key, value); else url.searchParams.delete(key);
            }
            root.history.replaceState(root.history.state, "", url);
        }
        visibleStates() { return this.states.filter(state => !this.region || state.region === this.region); }
        render() {
            this.find("emap-round-label").textContent = `${Number(this.context?.round) || 1}º TURNO`;
            const candidates = this.find("emap-candidate");
            const keys = [...this.catalog.keys()].join("|");
            if (keys !== this.catalogKeys) {
                candidates.replaceChildren(); const all = el("option", "", "Todos os candidatos"); all.value = ""; candidates.append(all);
                for (const [id, candidate] of this.catalog) { const option = el("option", "", `${candidateName(candidate)} · ${candidate.party_acronym || "Partido não informado"}`); option.value = id; candidates.append(option); }
                this.catalogKeys = keys;
            }
            candidates.value = this.candidate || "";
            this.find("emap-mode").value = this.mode;
            this.find("emap-canvas").hidden = this.view === "table"; this.find("emap-table").hidden = this.view !== "table";
            this.find("emap-map-view").setAttribute("aria-pressed", this.view === "map"); this.find("emap-table-view").setAttribute("aria-pressed", this.view === "table");
            const available = this.visibleStates().filter(state => this.summaries.has(state.scope)).length;
            const withVotes = this.visibleStates().filter(state => ["partial", "consolidated", "tie"].includes(this.summaries.get(state.scope)?.state)).length;
            const status = this.find("emap-status");
            status.textContent = this.loading ? "Carregando resultados do mesmo conjunto oficial…" : this.comparing ? "Conferindo a publicação independente do outro turno…"
                : this.mode === "compare" && this.comparisonError ? "Comparação em espera: os dois turnos precisam de publicações oficiais verificáveis. Nenhum resultado foi substituído."
                : ["share", "compare"].includes(this.mode) && !this.candidate ? "Escolha um candidato para visualizar seu percentual por estado."
                : !available && this.failures.size ? "Não foi possível carregar os resultados por UF. Os dados do mapa permanecem neutros."
                : !available ? "Aguardando resultados presidenciais oficiais por UF neste turno."
                : !withVotes ? `${available} UFs com candidaturas publicadas. Aguardando o início da apuração; o mapa permanece neutro.`
                : `${available} de ${this.visibleStates().length} UFs disponíveis · ${withVotes} com votos publicados. Liderança na UF não significa eleição.`;
            if (!this.loading && this.failures.size) {
                const retry = el("button", "emap-retry", "Tentar novamente"); retry.type = "button";
                retry.addEventListener("click", () => { this.key = null; this.setContext(this.portal.getContext()); });
                status.append(retry);
            }
            this.mount.setAttribute("aria-busy", this.loading || this.comparing ? "true" : "false");
            this.paint(); this.renderLegend(); this.renderDetail(); if (this.view === "table") this.renderTable(); this.renderMethod();
        }
        paint() {
            const visible = new Set(this.visibleStates().map(state => state.scope));
            for (const state of this.states) {
                const summary = this.summaries.get(state.scope), nodes = this.paths.get(state.scope), value = metric(summary, this.mode, this.candidate, this.comparison?.get(state.scope));
                const eligible = visible.has(state.scope) && (!this.query || normalize(state.name).includes(this.query) || state.scope.includes(this.query));
                let color = "#d7dfe5";
                if (this.mode === "leader" && value != null) color = this.colors.get(value) || "#526877";
                else if (value != null && typeof value === "number") color = this.mode === "compare" ? blend(value >= 0 ? "#2463a5" : "#b65338", Math.abs(value) / 30)
                    : blend(this.mode === "abstention" ? "#aa6a2b" : this.mode === "margin" ? "#227d74" : this.colors.get(this.candidate) || "#2463a5", value / 100);
                const candidateMatch = this.mode !== "leader" || !this.candidate || value === this.candidate || value == null;
                nodes.path.setAttribute("fill", color); nodes.path.style.opacity = eligible ? candidateMatch ? "1" : ".3" : ".15";
                nodes.path.dataset.status = summary?.state || "unavailable"; nodes.path.dataset.selected = state.scope === this.selected;
                nodes.path.dataset.consolidation = ["partial", "consolidated", "tie"].includes(summary?.state)
                    ? this.mode === "compare" && this.comparison?.get(state.scope)?.consolidation === "partial" ? "partial" : summary.consolidation : "";
                nodes.path.setAttribute("aria-pressed", state.scope === this.selected ? "true" : "false");
                const label = this.stateDescription(state, summary); nodes.path.setAttribute("aria-label", label); nodes.title.textContent = label;
                nodes.label.style.opacity = eligible ? "1" : ".25";
                nodes.label.setAttribute("fill", nodes.callout ? "var(--emap-text)" : this.mode === "leader" && value != null ? "#fff" : "#213c4a");
                if (nodes.callout) nodes.callout.style.opacity = eligible ? "1" : ".2";
            }
            if (this.selected && this.paths.has(this.selected)) {
                const selectedPath = this.paths.get(this.selected).path;
                if (this.pathLayer.lastChild !== selectedPath) {
                    const hadFocus = document.activeElement === selectedPath;
                    this.pathLayer.append(selectedPath);
                    if (hadFocus) selectedPath.focus({preventScroll: true});
                }
            }
        }
        stateDescription(state, summary) {
            return `${state.name}, ${Number(this.context?.round) || 1}º turno. ${statusText(summary)}.` + (summary?.leader ? ` Mais votado: ${candidateName(summary.leader)}, ${summary.leader.party_acronym || "partido não informado"}, ${number(summary.leader.votes)} votos, ${percentage(shareFor(summary, summary.leader.id))}.` : "") + (summary?.sections != null ? ` ${percentage(summary.sections)} das seções totalizadas.` : "");
        }
        renderLegend() {
            const legend = this.find("emap-legend");
            const previousDetails = legend.querySelector("details");
            if (previousDetails) this.otherCandidatesOpen = previousDetails.open;
            legend.replaceChildren();
            if (this.mode === "leader") {
                const counts = new Map(); for (const state of this.visibleStates()) { const id = this.summaries.get(state.scope)?.leader?.id; if (id) counts.set(id, (counts.get(id) || 0) + 1); }
                const visible = this.visibleStates().map(state => this.summaries.get(state.scope)).filter(Boolean);
                const noLeaderReason = !visible.length ? "dados ausentes"
                    : visible.every(summary => summary.state === "waiting") ? "aguardando apuração" : "sem liderança";
                const makeButton = ([id, candidate]) => {
                    const button = el("button", "emap-legend-item"); button.type = "button"; button.setAttribute("aria-pressed", this.candidate === id);
                    const swatch = el("span", "emap-swatch"); swatch.style.backgroundColor = this.colors.get(id); swatch.setAttribute("aria-hidden", "true");
                    const count = counts.get(id) || 0;
                    button.append(swatch, el("span", "", `${candidateName(candidate)} · ${candidate.party_acronym || "—"}`), el("strong", "", !counts.size ? `0 UFs · ${noLeaderReason}` : `${count} ${count === 1 ? "UF" : "UFs"}`));
                    button.setAttribute("aria-label", `${candidateName(candidate)}, ${candidate.party_acronym || "partido não informado"}: ${count} UFs com liderança${!counts.size ? ", " + noLeaderReason : ""}. Filtrar candidatura.`);
                    button.addEventListener("click", () => this.setCandidate(this.candidate === id ? "" : id));
                    return button;
                };
                const candidates = [...this.catalog.entries()];
                if (counts.size) {
                    const leaders = candidates.filter(([id]) => counts.has(id)).sort((a, b) => counts.get(b[0]) - counts.get(a[0]));
                    const others = candidates.filter(([id]) => !counts.has(id));
                    leaders.forEach(candidate => legend.append(makeButton(candidate)));
                    if (others.length) {
                        const details = el("details", "emap-other-candidates");
                        details.open = Boolean(this.otherCandidatesOpen || others.some(([id]) => id === this.candidate));
                        const summary = el("summary", "", "Outras candidaturas (sem liderança)"); summary.append(el("span", "", String(others.length)));
                        const list = el("div", "emap-other-candidate-list"); others.forEach(candidate => list.append(makeButton(candidate)));
                        details.append(summary, list); legend.append(details);
                    }
                } else {
                    candidates.forEach(candidate => legend.append(makeButton(candidate)));
                }
                if (!this.catalog.size) legend.append(el("span", "emap-legend-empty", "A legenda acompanha os candidatos oficialmente publicados."));
            } else {
                const scale = el("div", "emap-scale"), gradient = el("span", "emap-scale-gradient");
                const color = this.mode === "abstention" ? "#aa6a2b" : this.mode === "margin" ? "#227d74" : this.colors.get(this.candidate) || "#2463a5";
                gradient.style.background = this.mode === "compare" ? "linear-gradient(90deg,#b65338,#eee,#2463a5)" : `linear-gradient(90deg,#eee,${color})`;
                scale.append(el("span", "", this.mode === "compare" ? "−30 p.p." : "0%"), gradient, el("span", "", this.mode === "compare" ? "+30 p.p." : "100%")); legend.append(scale);
                if (this.candidate && ["share", "compare"].includes(this.mode)) legend.append(el("span", "emap-scale-candidate", candidateName(this.catalog.get(this.candidate))));
            }
            const neutral = el("span", "emap-neutral-legend"), swatch = el("span", "emap-swatch"); swatch.style.backgroundColor = "#d7dfe5"; neutral.append(swatch, el("span", "", "Neutro: sem votos válidos, empate ou dados ausentes")); legend.append(neutral);
            const partial = el("span", "emap-partial-legend", this.mode === "compare" ? "Contorno tracejado: pelo menos um turno parcial" : "Contorno tracejado: apuração parcial"); legend.append(partial);
        }
        renderMethod() {
            const selectedName = candidateName(this.catalog.get(this.candidate));
            const methods = {
                leader: "Critério: candidato com mais votos nominais válidos na UF. Empates e votação zerada não recebem uma liderança. Totalização final requer confirmação explícita do TSE e todas as seções totalizadas. O mapa não declara eleitos.",
                share: `Leitura: ${this.candidate ? selectedName : "candidato selecionado"}. Percentual = votos do candidato ÷ votos válidos nominais da UF × 100. Quando o denominador não está disponível, utiliza-se somente o percentual informado pelo TSE.`,
                margin: "Diferença percentual = (votos do primeiro − votos do segundo) ÷ votos válidos nominais da UF × 100. Diferença em votos também aparece no painel. Requer duas candidaturas e denominador oficial válido.",
                abstention: "Abstenção nas seções totalizadas = eleitores que não compareceram ÷ eleitorado das seções totalizadas × 100. Não representa as seções ainda não totalizadas.",
                compare: `Variação em pontos percentuais = percentual no ${Number(this.context?.round) || 1}º turno − percentual no ${Number(this.context?.round) === 2 ? 1 : 2}º turno, para a mesma candidatura e UF. Cada turno usa sua própria publicação validada. Valores parciais continuam parciais; a escala de cor satura em ±30 p.p.`
            };
            this.find("emap-method").textContent = methods[this.mode];
        }
        renderDetail() {
            const panel = this.find("emap-detail"); panel.replaceChildren(); const state = this.states.find(state => state.scope === this.selected);
            if (!state) {
                panel.append(el("p", "emap-eyebrow", "EXPLORE O TERRITÓRIO"), el("h3", "", "Cada estado tem uma história."), el("p", "emap-detail-copy", "Selecione uma UF no mapa ou na tabela para ver a votação, a diferença entre candidatos e a situação da apuração."));
                const list = el("div", "emap-region-cards");
                for (const [id, name] of [["n", "Norte"], ["ne", "Nordeste"], ["co", "Centro-Oeste"], ["se", "Sudeste"], ["s", "Sul"]]) {
                    const button = el("button", "emap-region-card"); button.type = "button"; button.setAttribute("aria-pressed", this.region === id); button.append(el("span", "", name), el("span", "", `${this.states.filter(state => state.region === id).length} UFs →`));
                    button.addEventListener("click", () => { this.region = this.region === id ? "" : id; this.find("emap-region").value = this.region; this.fitRegion(); this.render(); this.updateUrl(); }); list.append(button);
                }
                panel.append(list, el("p", "emap-detail-hint", "Use a tabela para uma leitura equivalente, com todos os valores disponíveis e navegação por teclado.")); return;
            }
            const summary = this.summaries.get(state.scope); const badge = el("span", "emap-status-badge", statusText(summary));
            badge.dataset.status = summary?.state || "unavailable";
            panel.append(el("p", "emap-eyebrow", state.regionName.toUpperCase()), el("h3", "", state.name), badge);
            const stats = el("dl", "emap-detail-stats"); const stat = (label, value) => { const item = el("div"); item.append(el("dt", "", label), el("dd", "", value)); stats.append(item); };
            stat("Seções totalizadas", percentage(summary?.sections)); stat("Votos válidos nominais", number(summary?.valid));
            panel.append(stats);
            if (summary?.leader) {
                panel.append(el("p", "emap-detail-label", summary.state === "consolidated" ? "MAIS VOTADO NA UF" : "LIDERANÇA PARCIAL NA UF"));
                const limit = summary.candidates.slice(0, 3);
                for (const candidate of limit) {
                    const button = el("button", "emap-candidate-row"); button.type = "button"; button.setAttribute("aria-pressed", this.candidate === candidate.id);
                    const top = el("span", "emap-candidate-row-top"); top.append(el("strong", "", candidateName(candidate)), el("strong", "", percentage(shareFor(summary, candidate.id))));
                    const caption = el("span", "emap-candidate-row-caption", `${candidate.party_acronym || "—"} · ${number(candidate.votes)} votos`);
                    const track = el("span", "emap-vote-track"), bar = el("span"); bar.style.width = `${shareFor(summary, candidate.id) || 0}%`; bar.style.backgroundColor = this.colors.get(candidate.id); track.append(bar); button.append(top, caption, track);
                    button.addEventListener("click", () => this.setCandidate(this.candidate === candidate.id ? "" : candidate.id)); panel.append(button);
                }
                if (summary.second) panel.append(el("p", "emap-margin-note", `Diferença: ${number(summary.leader.votes - summary.second.votes)} votos${summary.margin == null ? "" : ` · ${percentageFormat.format(summary.margin)} p.p.`}.`));
            } else panel.append(el("p", "emap-detail-copy", summary?.state === "tie" ? "Há empate entre os mais votados. Nenhuma liderança é atribuída no mapa." : summary?.state === "waiting" ? "Candidaturas publicadas. Aguardando o início da apuração; não há liderança a classificar." : this.failures.has(state.scope) ? "O resultado desta UF não pôde ser carregado ou não corresponde ao conjunto publicado. Use Tentar novamente; nenhum outro turno será exibido aqui." : "O resultado presidencial desta UF ainda não está disponível neste conjunto publicado."));
            if (summary?.abstention != null) panel.append(el("p", "emap-detail-hint", `Abstenção nas seções totalizadas: ${percentage(summary.abstention)}.`));
            if (this.mode === "compare") {
                const change = difference(summary, this.comparison?.get(state.scope), this.candidate);
                panel.append(el("p", "emap-margin-note", change == null ? "Comparação indisponível para esta candidatura e UF." : `Variação: ${change > 0 ? "+" : ""}${percentageFormat.format(change)} p.p. · ${statusText(this.comparison.get(state.scope))} no outro turno.`));
            }
            panel.append(el("p", "emap-detail-source", `Atualização TSE: ${date(summary?.update)} · ${Number(this.context?.round) || 1}º turno · UF IBGE ${state.ibge}`));
            const close = el("button", "emap-back", "← Visão do Brasil"); close.type = "button"; close.addEventListener("click", () => { this.selected = ""; this.viewport = [0, 0, 820, 740]; this.applyViewport(); Promise.resolve(this.portal.selectScope("br", 1)).catch(() => {}); this.render(); }); panel.append(close);
        }
        renderTable() {
            const wrapper = this.find("emap-table"); wrapper.replaceChildren(); const table = el("table"); const caption = el("caption", "emap-sr", `Resultados presidenciais por UF, ${Number(this.context?.round) || 1}º turno. Mesmos dados do mapa.`); table.append(caption);
            const head = el("thead"), headings = el("tr");
            const columns = ["UF / estado", "Mais votado", "Votos", "% válidos", "Seções", "Situação"];
            if (this.mode !== "leader") columns.push({share: "% do candidato", margin: "Diferença (p.p.)", abstention: "Abstenção", compare: "Variação (p.p.)"}[this.mode]);
            for (const label of columns) { const th = el("th", "", label); th.scope = "col"; headings.append(th); } head.append(headings); table.append(head);
            const body = el("tbody");
            for (const state of this.visibleStates()) {
                const summary = this.summaries.get(state.scope), row = el("tr"); row.dataset.selected = state.scope === this.selected;
                const name = el("th"); name.scope = "row"; const button = el("button", "emap-table-link", `${state.scope.toUpperCase()} · ${state.name}`); button.type = "button"; button.addEventListener("click", () => this.select(state.scope)); name.append(button); row.append(name);
                for (const value of [summary?.leader ? `${candidateName(summary.leader)} · ${summary.leader.party_acronym || "—"}` : "—", number(summary?.leader?.votes), percentage(summary?.leader ? shareFor(summary, summary.leader.id) : null), percentage(summary?.sections), statusText(summary)]) row.append(el("td", "", value));
                if (this.mode !== "leader") {
                    const value = metric(summary, this.mode, this.candidate, this.comparison?.get(state.scope));
                    row.append(el("td", "", value == null ? "—" : ["margin", "compare"].includes(this.mode) ? `${value > 0 && this.mode === "compare" ? "+" : ""}${percentageFormat.format(value)} p.p.` : percentage(value)));
                }
                body.append(row);
            }
            table.append(body); wrapper.append(table);
        }
        tooltip(state, event) {
            if (event.pointerType === "touch" || this.drag) return;
            const tooltip = this.find("emap-tooltip"); tooltip.replaceChildren(el("strong", "", state.name), el("span", "", this.stateDescription(state, this.summaries.get(state.scope)).replace(state.name + ", ", "")));
            const rect = this.find("emap-canvas").getBoundingClientRect(); tooltip.hidden = false;
            tooltip.style.left = Math.min(Math.max(12, event.clientX - rect.left + 12), Math.max(12, rect.width - 270)) + "px";
            tooltip.style.top = Math.min(Math.max(42, event.clientY - rect.top + 12), Math.max(42, rect.height - tooltip.offsetHeight - 12)) + "px";
        }
        onMapKey(event, state) {
            if (["Enter", " "].includes(event.key)) { event.preventDefault(); this.select(state.scope); return; }
            const directions = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]}; const direction = directions[event.key]; if (!direction) return;
            event.preventDefault();
            const next = this.visibleStates().filter(candidate => candidate.scope !== state.scope).map(candidate => { const dx = candidate.center[0] - state.center[0], dy = candidate.center[1] - state.center[1]; const forward = dx * direction[0] + dy * direction[1]; return {candidate, score: forward > 0 ? Math.hypot(dx, dy) + Math.abs(dx * direction[1] - dy * direction[0]) * 2 : Infinity}; }).sort((a, b) => a.score - b.score)[0];
            if (next && Number.isFinite(next.score)) { this.rovingScope = next.candidate.scope; this.updateTabindex(); this.paths.get(this.rovingScope).path.focus(); }
        }
        applyViewport() {
            this.viewport[2] = Math.max(90, Math.min(1000, this.viewport[2])); this.viewport[3] = this.viewport[2] * 740 / 820;
            this.viewport[0] = Math.max(-180, Math.min(820 - this.viewport[2] + 180, this.viewport[0])); this.viewport[1] = Math.max(-180, Math.min(740 - this.viewport[3] + 180, this.viewport[1]));
            this.svg.setAttribute("viewBox", this.viewport.map(value => Math.round(value * 100) / 100).join(" "));
            this.updateLabels();
            this.find("emap-zoom-out").disabled = this.viewport[2] >= 1000; this.find("emap-zoom-in").disabled = this.viewport[2] <= 90;
        }
        updateLabels() {
            const width = this.svg?.clientWidth;
            if (!width || !this.viewport) return;
            const desired = width < 500 ? 10 : 11;
            for (const nodes of this.paths.values()) nodes.label.style.fontSize = `${desired * this.viewport[2] / width}px`;
        }
        zoom(factor) { const [x, y, width, height] = this.viewport; const nextWidth = Math.max(90, Math.min(1000, width * factor)); this.viewport = [x + (width - nextWidth) / 2, y + (height - nextWidth * 740 / 820) / 2, nextWidth, nextWidth * 740 / 820]; this.applyViewport(); }
        fitState(state) { this.fitBounds(state.bounds, 1.8); }
        fitBounds(bounds, padding) { const [x0, y0, x1, y1] = bounds; const width = Math.max(90, (x1 - x0) * padding, (y1 - y0) * padding * 820 / 740), height = width * 740 / 820; this.viewport = [(x0 + x1 - width) / 2, (y0 + y1 - height) / 2, width, height]; this.applyViewport(); }
        fitRegion() {
            if (!this.region) { this.viewport = [0, 0, 820, 740]; this.applyViewport(); return; }
            const states = this.visibleStates(); this.fitBounds([Math.min(...states.map(state => state.bounds[0])), Math.min(...states.map(state => state.bounds[1])), Math.max(...states.map(state => state.bounds[2])), Math.max(...states.map(state => state.bounds[3]))], 1.2);
        }
    }
    function mount() {
        const target = document.getElementById("electoral-map-root");
        if (!target || target.dataset.mounted || !root.ElectionPortal || !root.ElectionGeography) return;
        target.dataset.mounted = "true"; root.ElectoralMap.view = new ElectoralMapView(target, root.ElectionGeography, root.ElectionPortal);
    }
    api.mount = mount;
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount); else mount();
    document.addEventListener("election:context", mount);
})(typeof window !== "undefined" ? window : globalThis);
