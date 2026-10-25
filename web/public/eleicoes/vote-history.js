/* Official observed vote totals and publication times. No estimates or declarations. */
(function (root) {
    'use strict';
    const doc = root.document, panel = doc?.getElementById('vote-history');
    if (!panel) return;
    const $ = id => doc.getElementById(id);
    const number = value => new Intl.NumberFormat('pt-BR').format(value);
    const percent = value => new Intl.NumberFormat('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2}).format(value) + '%';
    const time = value => new Date(value).toLocaleTimeString('pt-BR', {timeZone: 'America/Sao_Paulo', hour12: false});
    const minute = value => new Date(value).toLocaleTimeString('pt-BR', {timeZone: 'America/Sao_Paulo', hour12: false, hour: '2-digit', minute: '2-digit'});
    const ns = 'http://www.w3.org/2000/svg';
    let history = null, busy = false, selected = null, following = true;
    function element(tag, attributes, text) {
        const node = doc.createElementNS(ns, tag);
        for (const [key, value] of Object.entries(attributes || {})) node.setAttribute(key, String(value));
        if (text != null) node.textContent = text;
        return node;
    }
    function validate(value) {
        if (!value || value.schema_version !== 1 || value.environment !== 'oficial' || value.round !== 2
            || value.scope !== 'br' || value.office !== 1 || !Array.isArray(value.candidates)
            || !value.candidates.length || value.candidates.length > 100 || !Array.isArray(value.points)
            || !value.points.length || value.points.length > 4096) throw new Error('invalid_vote_history');
        const ids = new Set();
        for (const candidate of value.candidates) {
            if (!/^[0-9]{1,20}$/.test(candidate.id) || ids.has(candidate.id)
                || typeof candidate.name !== 'string' || candidate.name.length > 160) throw new Error('invalid_history_candidate');
            ids.add(candidate.id);
        }
        let previous = -Infinity;
        for (const point of value.points) {
            const stamp = Date.parse(point.at);
            if (!Number.isFinite(stamp) || stamp < previous || !/^[a-f0-9]{64}$/.test(point.snapshot_id)
                || !point.votes || typeof point.votes !== 'object') throw new Error('invalid_history_point');
            for (const [id, votes] of Object.entries(point.votes)) {
                if (!ids.has(id) || !Number.isSafeInteger(votes) || votes < 0) throw new Error('invalid_history_vote');
            }
            if (!point.percentages || typeof point.percentages !== 'object') throw new Error('history_percentages_unavailable');
            for (const [id, value] of Object.entries(point.percentages)) {
                if (!ids.has(id) || !Number.isFinite(value) || value < 0 || value > 100) throw new Error('invalid_history_percentage');
            }
            if ([...ids].some(id => point.votes[id] != null && point.percentages[id] == null)) throw new Error('history_percentage_missing');
            previous = stamp;
        }
        return value;
    }
    function color(candidate) { return root.ElectionPortal?.candidateColor(candidate.number) || '#167c80'; }
    function showPoint(index) {
        if (!history) return;
        index = Math.max(0, Math.min(history.points.length - 1, index));
        const point = history.points[index];
        selected = point.at;
        following = index === history.points.length - 1;
        $('vote-history-position').value = String(index);
        const output = $('vote-history-readout');
        output.replaceChildren();
        const stamp = doc.createElement('strong'); stamp.textContent = time(point.at) + ' · Brasília'; output.append(stamp);
        for (const candidate of history.candidates) {
            const row = doc.createElement('span'); row.textContent = candidate.name + ': '
                + (point.percentages[candidate.id] == null ? 'Sem observação nesta parcial'
                    : percent(point.percentages[candidate.id]) + ' · ' + number(point.votes[candidate.id]) + ' votos');
            row.style.borderColor = color(candidate); output.append(row);
        }
        const crosshair = $('vote-history-crosshair');
        if (crosshair) {
            const svg = $('vote-history-svg');
            const x = Number(svg.dataset.left) + (Date.parse(point.at) - Number(svg.dataset.start))
                / Number(svg.dataset.span) * Number(svg.dataset.plot);
            crosshair.setAttribute('x1', String(x)); crosshair.setAttribute('x2', String(x));
        }
    }
    function table() {
        if (!history || !$('vote-history-table-details').open) return;
        const target = $('vote-history-table'); target.replaceChildren();
        const header = doc.createElement('tr');
        for (const text of ['Horário da publicação (Brasília)', ...history.candidates.map(c => c.name)]) {
            const cell = doc.createElement('th'); cell.scope = 'col'; cell.textContent = text; header.append(cell);
        }
        const head = doc.createElement('thead'); head.append(header); target.append(head);
        const body = doc.createElement('tbody');
        for (const point of history.points) {
            const row = doc.createElement('tr');
            for (const text of [time(point.at), ...history.candidates.map(c => point.percentages[c.id] == null ? '—'
                : percent(point.percentages[c.id]) + ' · ' + number(point.votes[c.id]) + ' votos')]) {
                const cell = doc.createElement('td'); cell.textContent = text; row.append(cell);
            }
            body.append(row);
        }
        target.append(body);
    }
    function draw() {
        if (!history) return;
        const svg = $('vote-history-svg'), width = Math.max(320, svg.clientWidth || 800), height = 320;
        const left = 66, right = width - 18, top = 20, bottom = height - 48;
        const stamps = history.points.map(point => Date.parse(point.at));
        const start = stamps[0], span = Math.max(1, stamps[stamps.length - 1] - start);
        const x = at => left + (Date.parse(at) - start) / span * (right - left);
        const y = value => bottom - value / 100 * (bottom - top);
        svg.setAttribute('viewBox', `0 0 ${width} ${height}`); svg.replaceChildren();
        Object.assign(svg.dataset, {left, start, span, plot: right - left});
        for (let tick = 0; tick <= 4; tick++) {
            const value = 100 * tick / 4, at = y(value);
            svg.append(element('line', {x1: left, x2: right, y1: at, y2: at, class: 'history-grid'}),
                element('text', {x: left - 9, y: at + 4, 'text-anchor': 'end', class: 'history-axis'}, value + '%'));
        }
        const ticks = width < 550 ? 2 : 4;
        for (let tick = 0; tick <= ticks; tick++) {
            const at = start + span * tick / ticks;
            svg.append(element('text', {x: left + (right - left) * tick / ticks, y: bottom + 25,
                'text-anchor': tick === 0 ? 'start' : tick === ticks ? 'end' : 'middle', class: 'history-axis'}, minute(at)));
        }
        const legend = $('vote-history-legend'); legend.replaceChildren();
        for (const candidate of history.candidates) {
            let path = '', prior = false;
            for (const point of history.points) {
                const value = point.percentages[candidate.id];
                if (value == null) { prior = false; continue; }
                path += prior ? ` L ${x(point.at)} ${y(value)}` : ` M ${x(point.at)} ${y(value)}`;
                prior = true;
            }
            svg.append(element('path', {d: path, stroke: color(candidate), fill: 'none', 'stroke-width': 3,
                'vector-effect': 'non-scaling-stroke'}));
            const last = history.points[history.points.length - 1];
            if (last.percentages[candidate.id] != null) svg.append(element('circle', {cx: x(last.at), cy: y(last.percentages[candidate.id]), r: 4, fill: color(candidate)}));
            const label = doc.createElement('span'); label.textContent = candidate.name
                + (last.percentages[candidate.id] == null ? '' : ' · ' + percent(last.percentages[candidate.id]));
            label.style.borderColor = color(candidate); legend.append(label);
        }
        svg.append(element('line', {id: 'vote-history-crosshair', y1: top, y2: bottom, class: 'history-cursor'}));
        const slider = $('vote-history-position'); slider.max = String(history.points.length - 1); slider.disabled = false;
        const index = following ? history.points.length - 1 : Math.max(0, history.points.findIndex(point => point.at === selected));
        showPoint(index); table();
        $('vote-history-status').textContent = history.points.length + ' parciais preservadas · última publicação às '
            + time(history.points[history.points.length - 1].at) + ' (Brasília)';
    }
    async function refresh() {
        const round = root.ElectionPortal?.getContext()?.round;
        panel.hidden = round !== 2;
        if (round !== 2 || busy || doc.hidden || root.LiveData?.paused('/data/turnos/2')) return;
        busy = true;
        try {
            const response = await root.LiveData.fetch('/data/turnos/2/status.json');
            if (!response.ok) throw new Error('history_unavailable');
            const value = await response.json();
            if (!value.vote_history) {
                if (!history) $('vote-history-status').textContent = 'Aguardando histórico de parciais oficiais.';
                return;
            }
            const next = validate(value.vote_history);
            if (next.generation !== history?.generation) { history = next; draw(); }
        } catch (_) {
            $('vote-history-status').textContent = history ? 'Histórico preservado · nova consulta em 30 segundos.' : 'Histórico temporariamente indisponível.';
        } finally { busy = false; }
    }
    $('vote-history-position').addEventListener('input', event => showPoint(Number(event.target.value)));
    $('vote-history-table-details').addEventListener('toggle', table);
    $('vote-history-svg').addEventListener('pointermove', event => {
        if (!history) return;
        const svg = event.currentTarget, rect = svg.getBoundingClientRect();
        const target = Number(svg.dataset.start) + Math.max(0, Math.min(1,
            (event.clientX - rect.left - Number(svg.dataset.left)) / Number(svg.dataset.plot))) * Number(svg.dataset.span);
        let index = 0;
        for (let i = 1; i < history.points.length; i++) {
            if (Math.abs(Date.parse(history.points[i].at) - target) < Math.abs(Date.parse(history.points[index].at) - target)) index = i;
        }
        showPoint(index);
    });
    if (root.ResizeObserver) new root.ResizeObserver(draw).observe(panel);
    doc.addEventListener('election:context', refresh);
    doc.addEventListener('visibilitychange', () => { if (!doc.hidden) refresh(); });
    root.setInterval(refresh, 30000);
    root.ElectionVoteHistory = {refresh, getData: () => history};
    refresh();
})(window);
