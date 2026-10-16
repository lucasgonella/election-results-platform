/* Editorial overview and accessible table views consume the shared pinned context. */
(function () {
    "use strict";
    const api = window.ElectionPortal;
    if (!api) return;
    const $ = id => document.getElementById(id);
    const number = value => typeof value === "number" && Number.isFinite(value) ? new Intl.NumberFormat("pt-BR").format(value) : "Não informado";
    const percentage = value => typeof value === "number" && Number.isFinite(value)
        ? new Intl.NumberFormat("pt-BR", {maximumFractionDigits: 2, minimumFractionDigits: 2}).format(value) + "%" : "Não informado";
    const date = value => value && Number.isFinite(new Date(value).getTime())
        ? new Date(value).toLocaleString("pt-BR", {timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "short"}) : "Não informada";
    const normalize = text => String(text ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("pt-BR");
    let national = null, nationalPublication = "", raceKey = "", revision = 0, comparisonRevision = 0, context = api.getContext();
    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
    }
    function waiting(result) { return result?.election?.round === 2 && result?.snapshot?.sections?.totalized === 0; }
    function headline(result) {
        if (!result) return "Dados indisponíveis";
        if (waiting(result)) return "Aguardando apuração";
        const sections = result.snapshot?.sections;
        const final = result.snapshot?.totalization_final === true && sections?.total > 0
            && sections.totalized === sections.total;
        return final ? "Totalização final · TSE" : "Apuração parcial · TSE";
    }
    function scrollToResults() {
        $("resultados").scrollIntoView({behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"});
    }
    function text(id, value) { if ($(id)) $(id).textContent = value; }
    function updateRoundLinks() {
        for (const round of [1, 2]) {
            const link = $(round === 1 ? "round-first" : "round-second");
            const url = new URL(window.location.href);
            url.searchParams.set("turno", String(round));
            link.href = url.pathname + url.search + url.hash;
            link.setAttribute("aria-current", context.round === round ? "page" : "false");
        }
    }
    function overview() {
        const rows = context.manifest?.results || [];
        for (const [offices, key] of [[[3], "governors"], [[5], "senate"], [[6], "chamber"], [[7, 8], "assemblies"]]) {
            const selected = rows.filter(row => offices.includes(Number(row.office)));
            const count = new Set(selected.map(row => row.scope)).size;
            text("national-" + key, count ? String(count).padStart(2, "0") : "—");
            text("national-" + key + "-detail", count ? "UFs com dados neste turno" : !context.manifest
                ? "Aguardando publicação oficial" : context.round === 2 ? "Cargo sem disputa neste turno" : "Sem publicação disponível");
            const button = document.querySelector(`[data-national-office="${offices[0]}"]`);
            if (button) { button.disabled = !count; button.setAttribute("aria-label", `${button.querySelector('.national-label').textContent}: ${count ? count + ' UFs com dados' : 'sem dados neste turno'}`); }
        }
        text("national-freshness", context.version ? "Conjunto publicado · " + date(context.version.generated_at) : "Aguardando conjunto oficial");
        text("source-round", context.round + "º turno");
        text("source-generation", date(context.version?.generated_at));
        const row = context.manifest?.results?.find(item => item.scope === context.scope && Number(item.office) === Number(context.office));
        const link = $("source-result-link");
        if (row && context.dataBase) {
            link.href = context.dataBase + "/" + row.path;
            link.textContent = api.scopeName(context.scope) + " · " + row.office_name + " · JSON publicado";
        } else {
            link.removeAttribute("href");
            link.textContent = "Arquivo da seleção indisponível";
        }
        text("breadcrumb-scope", context.scope ? api.scopeName(context.scope) : "Todas as localidades");
        text("breadcrumb-office", context.result?.office?.name || "Resultados");
        const progress = $("sections-progress");
        const sections = context.result?.snapshot?.sections?.percentage;
        if (progress && typeof sections === "number") {
            progress.setAttribute("aria-valuenow", String(Math.max(0, Math.min(100, sections))));
            progress.setAttribute("aria-valuetext", waiting(context.result) ? "Aguardando apuração" : percentage(sections) + " das seções totalizadas");
        } else if (progress) {
            progress.removeAttribute("aria-valuenow");
            progress.setAttribute("aria-valuetext", context.status === "error" ? "Dados indisponíveis" : "Carregando resultados");
        }
        updateRoundLinks();
    }
    function markCandidate() {
        document.querySelectorAll("[data-race-candidate]").forEach(button => {
            const active = String(context.candidate || "") === button.dataset.raceCandidate;
            button.setAttribute("aria-pressed", String(active));
            button.closest(".race-card")?.classList.toggle("is-highlighted", active);
        });
        const candidates = context.result?.candidates || [];
        const page = api.getResultPage?.();
        document.querySelectorAll("#results .candidate").forEach((node, index) => {
            const candidate = page?.candidates?.[index] || candidates[index];
            if (candidate) {
                node.style.setProperty("--candidate-color", api.candidateColor(candidate.ballot_number));
                const active = Number(context.office) === 1 && String(candidate.ballot_number) === String(context.candidate || "");
                node.classList.toggle("is-highlighted", active);
            }
        });
    }
    function renderRace(result) {
        national = result;
        const key = `${context.round}|${context.version?.snapshot_id}|${result?.snapshot?.tse_idg}`;
        text("national-presidency", waiting(result) ? "Em espera" : percentage(result?.snapshot?.sections?.percentage));
        text("national-presidency-detail", waiting(result) ? "Cadastro oficial disponível" : "Seções totalizadas · Brasil");
        text("race-context", headline(result) + " · Brasil");
        if (raceKey === key) { markCandidate(); return; }
        raceKey = key;
        const root = $("presidential-race");
        root.replaceChildren();
        if (!result) { root.append(el("p", "empty", "A publicação deste turno ainda não fornece resultados nacionais.")); return; }
        const awaiting = waiting(result);
        const candidates = result.candidates.slice().sort((a, b) => (b.votes ?? -1) - (a.votes ?? -1)
            || (a.display_order ?? 0) - (b.display_order ?? 0));
        const extra = candidates.length > 2 ? el("details", "race-more") : null;
        if (extra) extra.append(el("summary", null, "Demais candidaturas · " + (candidates.length - 2)));
        candidates.forEach((candidate, index) => {
            const name = candidate.ballot_name || candidate.name;
            const card = el("article", "race-card");
            card.style.setProperty("--candidate-color", api.candidateColor(candidate.ballot_number));
            const top = el("div", "race-card-top");
            const initials = String(name).split(/\s+/).filter(Boolean).slice(0, 2).map(word => word[0]).join("");
            const avatar = el("span", "race-avatar", initials);
            avatar.setAttribute("aria-hidden", "true");
            const title = el("div", "race-title");
            title.append(el("h3", null, name), el("span", "race-party", `${candidate.party_acronym || 'Partido não informado'} · Nº ${candidate.ballot_number ?? '—'}`));
            top.append(avatar, title);
            const metrics = el("div", "race-metrics");
            const count = el("div"); count.append(el("strong", null, awaiting ? "—" : number(candidate.votes)), el("span", null, awaiting ? "votos ainda não apurados" : "votos"));
            metrics.append(count, el("strong", "race-percentage", awaiting ? "—" : percentage(candidate.vote_percentage)));
            const track = el("div", "race-bar-track");
            track.setAttribute("aria-hidden", "true");
            const bar = el("div", "race-bar");
            bar.style.width = (!awaiting && typeof candidate.vote_percentage === "number" ? Math.min(100, Math.max(0, candidate.vote_percentage)) : 0) + "%";
            track.append(bar);
            const status = el("p", "race-status", awaiting ? "Aguardando apuração" : candidate.result_status || "Situação ainda não definida");
            const button = el("button", "race-highlight", "Destacar no mapa");
            button.type = "button";
            button.dataset.raceCandidate = String(candidate.ballot_number);
            button.setAttribute("aria-label", "Destacar " + name + " no mapa");
            button.addEventListener("click", () => api.setCandidate(context.candidate === String(candidate.ballot_number) ? "" : candidate.ballot_number));
            card.append(top, metrics, track, status, button);
            (index < 2 ? root : extra || root).append(card);
        });
        if (extra) root.append(extra);
        if (context.candidate && !candidates.some(candidate => String(candidate.ballot_number) === String(context.candidate))) api.setCandidate("");
        markCandidate();
    }
    async function paint(next) {
        const currentRevision = ++revision;
        ++comparisonRevision;
        context = next || api.getContext();
        overview();
        renderTable();
        const ready = !!context.result;
        $("download-results").disabled = !ready;
        document.querySelectorAll('[data-dialog-open="compare-dialog"]').forEach(button => { button.disabled = !ready; });
        $("round-comparison").replaceChildren(el("p", "data-note", ready
            ? "Abra a comparação para verificar os turnos desta seleção."
            : context.status === "error" ? "A seleção está indisponível. Tente carregá-la novamente." : "Aguardando os resultados desta seleção…"));
        const publication = JSON.stringify([context.round, context.dataBase, context.version]);
        const unavailable = !ready || !context.manifest || !context.version;
        if (unavailable || publication !== nationalPublication) {
            national = null;
            nationalPublication = publication;
            raceKey = "";
            const failed = context.status === "error";
            text("national-presidency", "—");
            text("national-presidency-detail", failed ? "Consulta indisponível" : "Conferindo dados");
            text("race-context", failed ? "Resultados indisponíveis nesta consulta" : "Conferindo a seleção atual…");
            $("presidential-race").replaceChildren(el("p", failed ? "error" : "skeleton", failed
                ? "Tente novamente na área de resultados para conferir esta seleção."
                : "Aguardando os dados da seleção atual…"));
        }
        if ($("global-search-dialog").open) globalSearch();
        if (unavailable) return;
        if ($("compare-dialog").open) void compareRounds();
        try {
            const result = await api.loadResult("br", 1);
            if (currentRevision !== revision) return;
            renderRace(result);
            renderTable();
        } catch (_) {
            if (currentRevision !== revision) return;
            national = null;
            raceKey = "";
            text("national-presidency", "—");
            text("national-presidency-detail", "Consulta indisponível");
            text("race-context", "Não foi possível conferir a publicação presidencial");
            $("presidential-race").replaceChildren(el("p", "error", "A consulta ficará disponível após uma nova verificação. Nenhum valor foi estimado."));
        }
    }
    function renderTable() {
        markCandidate();
        const active = $("result-view")?.value === "table";
        $("results-table").hidden = !active || !context.result;
        $("results").hidden = active && !!context.result;
        if (!context.result) { $("results-table").replaceChildren(); return; }
        if (!active) return;
        const table = el("table", "data-table");
        table.append(el("caption", null, `${api.scopeName(context.scope)} · ${context.result.office.name} · ${context.round}º turno`));
        const head = el("thead"), row = el("tr");
        for (const label of ["Candidatura", "Partido", "Número", "Votos", "Percentual", "Situação TSE"]) {
            const th = el("th", null, label); th.scope = "col"; row.append(th);
        }
        head.append(row); table.append(head);
        const body = el("tbody");
        const page = api.getResultPage();
        for (const candidate of page.candidates) {
            const row = el("tr");
            const name = el("th", null, candidate.ballot_name || candidate.name); name.scope = "row"; row.append(name);
            for (const value of [candidate.party_acronym || "Não informado", candidate.ballot_number ?? "—",
                waiting(context.result) ? "Aguardando apuração" : number(candidate.votes),
                waiting(context.result) ? "—" : percentage(candidate.vote_percentage),
                waiting(context.result) ? "Aguardando apuração" : candidate.result_status || "Não definida"]) row.append(el("td", null, value));
            body.append(row);
        }
        table.append(body);
        const description = el("p", "data-note", `Exibindo ${page.candidates.length} de ${page.total} candidaturas filtradas. Página ${page.page}.`);
        $("results-table").replaceChildren(table, description);
    }
    function globalSearch() {
        const query = normalize($("global-search-input").value.trim());
        const root = $("global-search-results");
        root.replaceChildren();
        const options = [];
        const rows = context.manifest?.results || [];
        for (const scope of new Set(rows.map(row => row.scope))) {
            const name = api.scopeName(scope);
            if (!query || normalize(name + " " + scope).includes(query)) options.push({label: name, detail: "Localidade · Resultados oficiais", scope, office: 1});
        }
        if (query) for (const row of rows) {
            if (normalize(row.office_name + " " + api.scopeName(row.scope)).includes(query)) options.push({label: row.office_name + " · " + api.scopeName(row.scope), detail: "Cargo nesta localidade", scope: row.scope, office: row.office});
        }
        const loaded = [{result: context.result, scope: context.scope}, {result: national, scope: "br"}];
        const candidateKeys = new Set();
        if (query) for (const {result, scope} of loaded) for (const candidate of result?.candidates || []) {
            const name = candidate.ballot_name || candidate.name;
            const key = `${scope}|${result.office.code}|${candidate.tse_candidate_seq}`;
            if (!candidateKeys.has(key) && normalize([name, candidate.name, candidate.ballot_number, candidate.party_acronym].join(" ")).includes(query)) {
                candidateKeys.add(key);
                options.push({label: name, detail: `${result.office.name} · ${api.scopeName(scope)} · ${candidate.party_acronym || 'Sem partido informado'}`, scope, office: result.office.code, search: name});
            }
        }
        for (const option of options.slice(0, 24)) {
            const button = el("button", "global-search-result"); button.type = "button";
            button.append(el("strong", null, option.label), el("span", null, option.detail));
            button.addEventListener("click", async () => {
                $("global-search-dialog").close();
                const changed = await api.selectScope(option.scope, option.office);
                if (changed && option.search) { $("search").value = option.search; $("search").dispatchEvent(new Event("input")); }
                scrollToResults();
            });
            root.append(button);
        }
        if (!options.length) root.append(el("p", "empty", "Nenhum contexto carregado corresponde à busca. Tente o nome de uma UF ou outro cargo."));
        if (options.length > 24) root.append(el("p", "data-note", "Mostrando os primeiros 24 resultados. Refine sua busca."));
    }
    async function compareRounds() {
        const currentRevision = ++comparisonRevision;
        if (!context.result) return;
        const root = $("round-comparison"); root.replaceChildren(el("p", "skeleton", "Verificando as publicações de cada turno…"));
        const scope = context.scope || "br";
        const values = await Promise.allSettled([api.loadRoundResult(1, scope), api.loadRoundResult(2, scope)]);
        if (currentRevision !== comparisonRevision) return;
        root.replaceChildren();
        for (let index = 0; index < values.length; index++) {
            const item = values[index], result = item.status === "fulfilled" ? item.value?.result : null;
            const column = el("section", "comparison-column");
            column.append(el("h3", null, (index + 1) + "º turno · " + api.scopeName(scope)), el("p", "data-note", headline(result)));
            if (!result) column.append(el("p", "empty", item.status === "rejected" ? "Falha na verificação deste turno. Nenhum outro conjunto foi usado." : "Publicação oficial indisponível nesta localidade."));
            for (const candidate of result?.candidates || []) {
                const row = el("div", "comparison-row");
                row.append(el("strong", null, candidate.ballot_name || candidate.name), el("span", null, waiting(result) ? "Aguardando apuração" : number(candidate.votes) + " votos · " + percentage(candidate.vote_percentage)));
                column.append(row);
            }
            root.append(column);
        }
        const a = values[0].status === "fulfilled" ? values[0].value?.result : null;
        const b = values[1].status === "fulfilled" ? values[1].value?.result : null;
        if (a && b && !waiting(a) && !waiting(b) && a.snapshot.sections.totalized > 0 && b.snapshot.sections.totalized > 0) {
            const deltas = el("section", "comparison-deltas"); deltas.append(el("h3", null, "Variação descritiva · segundo menos primeiro turno"));
            for (const candidate of b.candidates) {
                const prior = a.candidates.find(value => String(value.ballot_number) === String(candidate.ballot_number)
                    && String(value.tse_candidate_seq) === String(candidate.tse_candidate_seq));
                if (!prior || typeof prior.vote_percentage !== "number" || typeof candidate.vote_percentage !== "number") continue;
                const delta = candidate.vote_percentage - prior.vote_percentage;
                deltas.append(el("p", null, `${candidate.ballot_name || candidate.name}: ${delta >= 0 ? '+' : ''}${new Intl.NumberFormat('pt-BR', {maximumFractionDigits: 2}).format(delta)} pontos percentuais`));
            }
            root.append(deltas);
        }
    }
    document.addEventListener("election:context", event => { void paint(event.detail); });
    document.addEventListener("election:error", () => { void paint(api.getContext()); });
    document.addEventListener("election:results", renderTable);
    $("result-view").addEventListener("change", renderTable);
    $("global-search-input").addEventListener("input", globalSearch);
    $("global-search-open").addEventListener("click", () => { $("global-search-dialog").showModal(); globalSearch(); $("global-search-input").focus(); });
    document.querySelectorAll('[data-dialog-open="compare-dialog"]').forEach(button => button.addEventListener("click", () => { void compareRounds(); }));
    $("presidential-focus").addEventListener("click", async () => { await api.selectScope("br", 1); scrollToResults(); });
    $("breadcrumb-brasil").addEventListener("click", () => api.selectScope("br", 1));
    document.querySelectorAll("[data-national-office]").forEach(button => button.addEventListener("click", async () => {
        const office = Number(button.dataset.nationalOffice);
        const options = context.manifest?.results.filter(row => office === 7 ? [7, 8].includes(Number(row.office)) : Number(row.office) === office) || [];
        const chosen = options.find(row => row.scope === context.scope) || options.find(row => row.scope === (office === 1 ? "br" : "go")) || options[0];
        if (chosen) { await api.selectScope(chosen.scope, chosen.office); scrollToResults(); }
    }));
    ["round-first", "round-second"].forEach(id => $(id).addEventListener("click", () => updateRoundLinks()));
    $("share-view").addEventListener("click", async () => {
        const url = window.location.href;
        try { await navigator.clipboard.writeText(url); text("portal-announcement", "Link desta visão copiado."); $("share-view").textContent = "Link copiado ✓"; }
        catch (_) { window.prompt("Copie o link desta visão", url); }
    });
    $("download-results").addEventListener("click", () => {
        const current = api.getContext();
        if (!context.result || current.result !== context.result || current.scope !== context.scope || current.office !== context.office) return;
        const rows = [["turno", "localidade", "cargo", "candidatura", "numero", "partido", "votos", "percentual_oficial", "situacao_tse", "geracao_fonte"]];
        for (const candidate of api.getCandidates()) rows.push([context.round, context.scope, context.result.office.name,
            candidate.ballot_name || candidate.name, candidate.ballot_number, candidate.party_acronym,
            waiting(context.result) ? null : candidate.votes, waiting(context.result) ? null : candidate.vote_percentage,
            waiting(context.result) ? "Aguardando apuração" : candidate.result_status, context.result.snapshot.generated_at]);
        const csv = "\ufeff" + rows.map(row => row.map(window.PortalBridge.csvCell).join(",")).join("\r\n");
        const blob = new Blob([csv], {type: "text/csv;charset=utf-8"}), url = URL.createObjectURL(blob);
        const link = el("a"); link.href = url; link.download = `eleicoes-2026-turno-${context.round}-${context.scope}-${context.office}.csv`; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    void paint(context);
})();
