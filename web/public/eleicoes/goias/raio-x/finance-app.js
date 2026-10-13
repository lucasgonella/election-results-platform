/* The visual reader never modifies the published financial dataset. */
(function () {
  'use strict';
  const F = window.AFGFinance, $ = id => document.getElementById(id);
  const isCompact = () => matchMedia('(max-width: 680px)').matches;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]));
  const money = value => F.validAmount(value) ? new Intl.NumberFormat('pt-BR', {style: 'currency', currency: 'BRL', maximumFractionDigits: 2}).format(value) : 'Não informado';
  const number = value => F.validAmount(value) ? new Intl.NumberFormat('pt-BR').format(value) : 'Não informado';
  const shortMoney = value => F.validAmount(value) ? new Intl.NumberFormat('pt-BR', {style: 'currency', currency: 'BRL', notation: 'compact', maximumFractionDigits: 1}).format(value) : 'Não informado';
  const date = value => { const key = F.dateKey(value); return key ? key.split('-').reverse().join('/') : 'Data não informada'; };
  const sourceLink = value => { const url = F.safeSource(value); return url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Consultar registro / conjunto do TSE ↗</a>` : '<span class="source-warning">Fonte oficial verificável não informada</span>'; };
  const candidateRole = node => node.roles?.includes('candidate') || node.kind === 'candidate';
  const kindLabel = node => ({'candidate': 'Candidata/o', 'candidate-donor': 'Candidata/o + doadora/or', 'candidate-campaign': 'Candidata/o + campanha financiadora', 'donor': 'Pessoa doadora', 'organization': 'Organização', 'unknown': 'Identidade não confirmada', 'counterparty': 'Contraparte · tipo não informado'}[node.kind] || 'Campanha');
  const rolesHTML = node => (node.roles || []).filter(role => ['candidate', 'donor', 'campaign_financier'].includes(role)).map(role => `<span class="role-badge">${esc({candidate: 'Candidata/o', donor: 'Doadora/or por CPF confirmado', campaign_financier: 'Campanha financiadora'}[role])}</span>`).join('');
  const FIELD_IDS = {q: 'search', office: 'office', party: 'party', kind: 'entity-kind', type: 'connection-type', from: 'financier', to: 'recipient', min: 'min-value', max: 'max-value', start: 'start-date', end: 'end-date', direction: 'identity-direction'};
  let state = F.fromQuery(location.search), index = null, rows = [], contextRows = [], graphData = null, candidatePage = 0, tablePage = 0, detailPage = 0, selectedEdge = null;
  let transform = {scale: 1, x: 0, y: 0}, pointer = null, toastTimer = null, scheduledRender = null;
  const PAGE_SIZE = 20, TABLE_SIZE = 30, DETAIL_SIZE = 15, SVG_NS = 'http://www.w3.org/2000/svg';
  function announce(message) {
    $('toast').textContent = message; $('toast').hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, 3200);
  }
  function syncURL() {
    const query = F.toQuery(state);
    history.replaceState(null, '', `${location.pathname}${query ? '?' + query : ''}${location.hash}`);
  }
  function fillFilters() {
    for (const [key, id] of Object.entries(FIELD_IDS)) $(id).value = state[key] || '';
  }
  function filterValues() {
    for (const [key, id] of Object.entries(FIELD_IDS)) state[key] = $(id).value;
    const invalidValues = state.min !== '' && state.max !== '' && Number(state.min) > Number(state.max);
    const invalidDates = state.start && state.end && state.start > state.end;
    $('max-value').setCustomValidity(invalidValues ? 'O valor máximo deve ser maior ou igual ao mínimo.' : '');
    $('end-date').setCustomValidity(invalidDates ? 'A data final deve ser posterior ou igual à data inicial.' : '');
    return !invalidValues && !invalidDates;
  }
  function updateFilterCount() {
    $('filter-count').textContent = Object.keys(FIELD_IDS).filter(key => !!state[key]).length;
    document.querySelectorAll('[data-kind]').forEach(button => {
      if (button.tagName === 'BUTTON') button.setAttribute('aria-pressed', String(state.kind === button.dataset.kind));
    });
  }
  function renderCandidates() {
    if (!index) return;
    const candidates = F.filterCandidates(index, state);
    const pages = Math.max(1, Math.ceil(candidates.length / PAGE_SIZE));
    candidatePage = Math.min(candidatePage, pages - 1);
    const start = candidatePage * PAGE_SIZE;
    $('list-count').textContent = number(candidates.length);
    $('candidate-list').innerHTML = candidates.length ? candidates.slice(start, start + PAGE_SIZE).map(candidate => `<button type="button" class="candidate-button" data-candidate="${esc(candidate.id)}" aria-pressed="${state.selected === candidate.id}"><strong>${esc(candidate.name)}</strong><small>${esc(candidate.party || 'Partido não informado')} · ${esc(candidate.number || 'Número não informado')} · ${candidate.office === 'deputado federal' ? 'Federal' : 'Estadual'}</small><span class="candidate-amount">${shortMoney(candidate.revenue)} <small>receitas declaradas</small></span></button>`).join('') : '<div class="empty-list">Nenhuma candidatura corresponde à busca. O filtro de nome também pesquisa contrapartes nas relações.</div>';
    $('candidate-page').textContent = `${candidates.length ? start + 1 : 0}–${Math.min(start + PAGE_SIZE, candidates.length)} de ${number(candidates.length)}`;
    $('candidate-prev').disabled = candidatePage === 0; $('candidate-next').disabled = candidatePage >= pages - 1;
  }
  function selectNode(id, options = {}) {
    if (!index || !index.nodes.has(id)) return;
    id = index.aliases.get(id) || id;
    state.selected = id; selectedEdge = null; detailPage = 0; tablePage = 0;
    state.direction = ''; $('identity-direction').value = '';
    $('path-search').value = ''; $('path-options').textContent = ''; $('path-result').textContent = '';
    if (options.candidate) state.depth = 1;
    const returnToGraph = options.candidate && isCompact();
    if (returnToGraph) {
      $('filters-panel').classList.remove('is-open'); $('filters-toggle').setAttribute('aria-expanded', 'false');
    }
    render(); syncURL();
    if (returnToGraph) { $('graph-title').setAttribute('tabindex', '-1'); $('graph-title').focus({preventScroll: true}); }
    else if (options.restoreCandidateFocus) { Array.from($('candidate-list').querySelectorAll('[data-candidate]')).find(button => button.dataset.candidate === id)?.focus({preventScroll: true}); }
    if (options.focusDetail) { $('detail-title').setAttribute('tabindex', '-1'); $('detail-title').focus({preventScroll: true}); }
  }
  function selectEdge(id) {
    selectedEdge = F.aggregate(contextRows).find(edge => edge.id === id) || null;
    detailPage = 0; renderDetail(); highlightSelection();
  }
  function context() {
    rows = F.filterTransfers(index, state);
    const local = F.neighborhood(rows, state.selected, state.depth);
    contextRows = state.selected ? rows.filter(row => local.ids.has(row.from_id) && local.ids.has(row.to_id)) : rows;
    graphData = F.graphView(index, rows, state.selected, state.depth);
  }
  function render() {
    if (!index) return;
    context(); renderCandidates(); drawGraph(); renderTable(); renderDetail(); updateFilterCount(); renderView();
  }
  function recordHTML(row) {
    return `<div class="record"><strong>${esc(row.from_name || index.nodes.get(row.from_id).name)} → ${esc(row.to_name || index.nodes.get(row.to_id).name)}</strong><p>${money(row.amount)} · ${date(row.date)}</p><p>${esc(row.type || 'Categoria não informada')}</p><p>${row.from_role === 'campaign' ? 'Origem: campanha eleitoral; exibida junto da titularidade comprovada. Não é uma doação pessoal.' : row.from_role === 'person' ? 'Origem: pessoa física identificada na fonte.' : 'Origem: identidade pessoal não confirmada.'}</p><code>ID ${esc(row.source_record_id || row.id)} · ${esc(row.source_file || 'Fonte publicada')}${row.source_row ? ' · linha ' + esc(row.source_row) : ''}</code>${sourceLink(row.source_url)}</div>`;
  }
  function recordListHTML(records) {
    const pages = Math.max(1, Math.ceil(records.length / DETAIL_SIZE)); detailPage = Math.min(detailPage, pages - 1);
    return `<div class="record-list">${records.slice(detailPage * DETAIL_SIZE, (detailPage + 1) * DETAIL_SIZE).map(recordHTML).join('')}</div>${records.length > DETAIL_SIZE ? `<div class="pagination"><button type="button" data-detail-page="-1" ${detailPage === 0 ? 'disabled' : ''} aria-label="Registros anteriores">←</button><span>${detailPage + 1} / ${pages}</span><button type="button" data-detail-page="1" ${detailPage === pages - 1 ? 'disabled' : ''} aria-label="Próximos registros">→</button></div>` : ''}`;
  }
  function renderDetail() {
    const node = index.nodes.get(state.selected);
    $('clear-selection').disabled = !node && !selectedEdge;
    $('path-origin').textContent = node ? node.name : 'selecione uma entidade';
    $('path-search').disabled = !node;
    if (selectedEdge) {
      const origin = index.nodes.get(selectedEdge.from_id), target = index.nodes.get(selectedEdge.to_id);
      $('detail-title').textContent = 'Um vínculo, seus registros';
      $('detail-content').innerHTML = `<span class="entity-label">TRANSFERÊNCIA DIRETA DOCUMENTADA</span><p class="profile-meta">${esc(origin.name)} <b>→</b> ${esc(target.name)}</p><div class="profile-metrics"><div class="profile-metric"><small>${selectedEdge.missing ? 'Subtotal informado' : 'Soma dos registros'}</small><strong>${money(selectedEdge.total)}</strong></div><div class="profile-metric"><small>Registros agrupados</small><strong>${number(selectedEdge.rows.length)}</strong></div></div><p class="muted">${esc(selectedEdge.type)}</p>${selectedEdge.missing ? `<p class="subtotal-note">${selectedEdge.missing} registro(s) sem valor. A soma não é um total completo.</p>` : ''}${selectedEdge.reciprocal ? '<p class="muted">Há também registros no sentido oposto dentro dos filtros. Cada sentido permanece separado.</p>' : ''}<p class="filter-help">A seta representa o sentido declarado. A existência da relação não demonstra irregularidade.</p><h4>Datas, identificadores e evidências</h4>${recordListHTML(selectedEdge.rows)}`;
      return;
    }
    if (!node) {
      $('detail-title').textContent = 'Escolha um ponto da rede';
      $('detail-content').innerHTML = '<p class="muted">Selecione uma candidatura ou um vínculo para examinar os registros. Sem seleção, a rede mostra as maiores relações dentro dos filtros.</p><div class="context-illustration" aria-hidden="true"><span></span><i></i><span></span></div>';
      return;
    }
    const incoming = rows.filter(row => row.to_id === node.id), outgoing = rows.filter(row => row.from_id === node.id);
    const inbound = F.sumKnown(incoming), outbound = F.sumKnown(outgoing), peers = new Set([...incoming.map(row => row.from_id), ...outgoing.map(row => row.to_id)]);
    const candidates = candidateRole(node);
    $('detail-title').textContent = node.name;
    const roleMetrics = `<div class="profile-metric"><small>Repasses realizados nos filtros</small><strong>${money(outbound.total)}</strong></div><div class="profile-metric"><small>Recebido nos filtros</small><strong>${money(inbound.total)}</strong></div><div class="profile-metric"><small>Campanhas beneficiadas nos filtros</small><strong>${number(new Set(outgoing.map(row => row.to_campaign_id || row.candidate_id || row.to_id)).size)}</strong></div>`;
    const metrics = candidates ? `<div class="profile-metric"><small>Receita total declarada</small><strong>${money(node.revenue)}</strong></div><div class="profile-metric"><small>Despesa total declarada</small><strong>${money(node.expenses)}</strong></div><div class="profile-metric"><small>Votos publicados nesta base</small><strong>${number(node.votes)}</strong></div><div class="profile-metric"><small>Contrapartes nos filtros</small><strong>${number(peers.size)}</strong></div>` : `<div class="profile-metric"><small>Recebido nos filtros${inbound.missing ? ' · subtotal' : ''}</small><strong>${money(inbound.total)}</strong></div><div class="profile-metric"><small>Enviado nos filtros${outbound.missing ? ' · subtotal' : ''}</small><strong>${money(outbound.total)}</strong></div>`;
    const direct = [...incoming, ...outgoing.filter(row => row.from_id !== row.to_id)].sort((a, b) => (b.amount ?? -1) - (a.amount ?? -1));
    const topGroups = F.aggregate(incoming).sort((a, b) => (b.total ?? -1) - (a.total ?? -1)).slice(0, 5);
    $('detail-content').innerHTML = `<span class="entity-label">${esc(kindLabel(node).toLocaleUpperCase('pt-BR'))}</span>${node.candidacies?.length > 1 ? `<p class="profile-meta">${node.candidacies.map(c => `${esc(c.ballot_name || c.name)} · ${esc(c.office)} · ${esc(c.party)} · TSE ${esc(c.id)}`).join('<br>')}</p>` : ''}<p class="profile-meta">${candidates ? `${esc(node.office)} · ${esc(node.party || 'Partido não informado')} · ${esc(node.number || 'Número não informado')}<br>${esc(node.status || 'Situação não informada')}` : esc(kindLabel(node))}</p><p class="entity-id">ID interno: ${esc(node.id)}${node.candidate_ids?.length ? ' · candidatura TSE: ' + node.candidate_ids.map(esc).join(', ') : ''}</p>${node.aliases.length ? `<p class="filter-help">Outros nomes neste mesmo ID: ${node.aliases.map(esc).join(' · ')}. Os nomes originais são preservados em cada registro.</p>` : ''}<div class="role-badges">${rolesHTML(node)}</div>${node.civil_name ? `<p class="profile-meta">Nome civil: <strong>${esc(node.civil_name)}</strong></p>` : ''}${node.evidence?.length ? `<details class="identity-evidence"><summary>Campanhas e evidências da associação</summary>${node.candidate_ids?.length ? `<p>Registro oficial de candidatura: ${node.candidate_ids.map(esc).join(', ')}</p>${sourceLink(node.source_url)}` : ''}${(node.campaigns || []).map(campaign => `<p>${esc(campaign.name)}<br>CNPJ de campanha: ${esc(campaign.cnpj)}<br>Candidatura: ${campaign.candidate_ids.map(esc).join(', ')}</p>${sourceLink(campaign.evidence[0]?.source_url)}`).join('')}${node.roles.includes('donor') ? '<p>Identidade pessoal confirmada por igualdade de CPF completo nos arquivos oficiais, sem publicar o documento.</p>' : '<p>Repasses de campanha não são classificados como doações pessoais.</p>'}</details>` : ''}<div class="profile-metrics">${metrics}${roleMetrics}</div>${candidates ? '<p class="filter-help">Receitas e despesas são totais da candidatura na base, independentes dos filtros da rede. Votos ausentes não são zero.</p>' : ''}${inbound.missing || outbound.missing ? '<p class="subtotal-note">Há valores não informados neste contexto. Somas incluem apenas os registros com valor.</p>' : ''}${topGroups.length ? `<h4>Principais origens nos filtros</h4><div>${topGroups.map(group => `<div class="record"><button type="button" data-node="${esc(group.from_id)}">${esc(index.nodes.get(group.from_id).name)} →</button><p>${money(group.total)} · ${number(group.rows.length)} registro(s)</p></div>`).join('')}</div>` : ''}<h4>${number(direct.length)} registros diretos nos filtros</h4>${direct.length ? recordListHTML(direct) : '<p class="muted">Nenhuma transferência documentada neste contexto. Isso não equivale a ausência de atividade financeira.</p>'}`;
  }
  function renderTable() {
    const records = contextRows.slice().sort((a, b) => (b.amount ?? -1) - (a.amount ?? -1));
    const pages = Math.max(1, Math.ceil(records.length / TABLE_SIZE)); tablePage = Math.min(tablePage, pages - 1);
    const start = tablePage * TABLE_SIZE;
    $('transfer-table').innerHTML = records.length ? records.slice(start, start + TABLE_SIZE).map(row => `<tr><td>${esc(index.nodes.get(row.from_id).name)}<small>→ ${esc(index.nodes.get(row.to_id).name)}</small><small>${esc(row.type || 'Categoria não informada')}</small></td><td>${money(row.amount)}</td><td>${date(row.date)}</td><td><button type="button" data-record="${esc(row.id)}">Inspecionar</button></td></tr>`).join('') : '<tr><td colspan="4">Nenhuma transferência documentada corresponde ao contexto e aos filtros.</td></tr>';
    $('table-page').textContent = `${records.length ? start + 1 : 0}–${Math.min(start + TABLE_SIZE, records.length)} de ${number(records.length)}`;
    $('table-prev').disabled = tablePage === 0; $('table-next').disabled = tablePage === pages - 1;
  }
  function renderView() {
    const table = state.view === 'table';
    $('graph-container').hidden = table; $('table-container').hidden = !table;
    $('graph-view-button').setAttribute('aria-pressed', String(!table)); $('table-view-button').setAttribute('aria-pressed', String(table));
  }
  function svgElement(tag, attributes, parent) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    if (parent) parent.appendChild(node);
    return node;
  }
  function drawGraph() {
    const viewport = $('graph-viewport'); viewport.textContent = '';
    const center = index.nodes.get(state.selected), nodes = graphData.nodes;
    $('graph-title').textContent = center ? center.name : 'Panorama dos filtros';
    $('graph-depth').textContent = state.depth === 2 ? 'DIRETAS + SEGUNDO NÍVEL DOCUMENTADO' : 'CONEXÕES DIRETAS';
    $('expand-neighbors').disabled = !center || !contextRows.length;
    $('expand-neighbors').textContent = state.depth === 2 ? 'Recolher 2º nível' : 'Expandir 2º nível';
    $('graph-summary').textContent = `${number(nodes.length)} entidades · ${number(graphData.edges.length)} vínculos agrupados · ${number(contextRows.length)} registros no contexto${graphData.hiddenEdges || graphData.hiddenNodes ? `. Limite visual: ${number(graphData.hiddenNodes)} entidades e ${number(graphData.hiddenEdges)} vínculos fora do desenho. Consulte a tabela.` : '.'}`;
    const empty = !graphData.edges.length;
    $('graph-empty').hidden = !empty;
    $('export-graph').disabled = empty;
    if (empty) {
      $('graph-empty').querySelector('h4').textContent = index.data.transfers.length ? 'Sem relações neste contexto' : 'Aguardando relações documentadas';
      $('graph-empty').querySelector('p').textContent = index.data.transfers.length ? 'Selecione outra candidatura ou ajuste os filtros. Nenhuma conexão será presumida a partir de nomes iguais.' : 'A base ainda não contém transferências verificadas. Candidaturas e valores disponíveis continuam acessíveis.';
      applyTransform(); return;
    }
    const positioned = new Map(), x0 = 450, y0 = 305;
    if (center) positioned.set(center.id, {x: x0, y: y0});
    const other = nodes.filter(node => !center || node.id !== center.id);
    const direct = other.filter(node => node.distance <= 1), indirect = other.filter(node => node.distance > 1);
    const layoutRing = (items, radius, start = -Math.PI / 2) => items.forEach((node, i) => {
      const angle = start + 2 * Math.PI * i / Math.max(1, items.length);
      const ring = items.length > 22 ? radius + (i % 2 ? 34 : -34) : radius;
      positioned.set(node.id, {x: x0 + ring * Math.cos(angle), y: y0 + ring * .78 * Math.sin(angle)});
    });
    layoutRing(direct, indirect.length ? 176 : 235); layoutRing(indirect, 320, -Math.PI / 2 + .1);
    if (!center) { positioned.clear(); layoutRing(other, 245); }
    const maxVolume = Math.max(1, ...nodes.map(node => node.volume));
    const radiusFor = node => node.id === state.selected ? 31 : 8 + 16 * Math.sqrt(node.volume / maxVolume);
    const maxAmount = Math.max(1, ...graphData.edges.map(edge => edge.total ?? 0));
    const categories = Array.from(new Set(graphData.edges.map(edge => edge.type))).sort();
    const patterns = ['', '7 4', '2 4', '10 3 2 3'];
    const edgesGroup = svgElement('g', {'class': 'graph-edges'}, viewport);
    graphData.edges.forEach(edge => {
      const from = positioned.get(edge.from_id), to = positioned.get(edge.to_id), origin = nodes.find(node => node.id === edge.from_id), target = nodes.find(node => node.id === edge.to_id);
      if (!from || !to) return;
      const group = svgElement('g', {'class': 'graph-edge', 'data-edge': edge.id, role: 'button', tabindex: 0, 'aria-label': `${origin.name} para ${target.name}, ${money(edge.total)}, ${edge.rows.length} registros, ${edge.type}`}, edgesGroup);
      const dx = to.x - from.x, dy = to.y - from.y, length = Math.max(1, Math.hypot(dx, dy));
      const end = {x: to.x - dx / length * (radiusFor(target) + 7), y: to.y - dy / length * (radiusFor(target) + 7)};
      const start = {x: from.x + dx / length * (radiusFor(origin) + 3), y: from.y + dy / length * (radiusFor(origin) + 3)};
      let path;
      if (edge.from_id === edge.to_id) path = `M${from.x - 12},${from.y - radiusFor(origin)} C${from.x - 55},${from.y - 85} ${from.x + 55},${from.y - 85} ${from.x + 12},${from.y - radiusFor(origin)}`;
      else {
        const samePair = graphData.edges.filter(row => row.from_id === edge.from_id && row.to_id === edge.to_id);
        const rank = samePair.findIndex(row => row.id === edge.id);
        const curve = edge.reciprocal ? 22 + rank * 10 : (rank - (samePair.length - 1) / 2) * 22;
        const mid = {x: (start.x + end.x) / 2 - dy / length * curve, y: (start.y + end.y) / 2 + dx / length * curve};
        path = `M${start.x},${start.y} Q${mid.x},${mid.y} ${end.x},${end.y}`;
      }
      svgElement('path', {d: path, 'class': 'edge-hit'}, group);
      svgElement('path', {d: path, 'class': 'edge-line', 'stroke-width': 1 + 5 * Math.sqrt((edge.total ?? 0) / maxAmount), 'stroke-dasharray': patterns[categories.indexOf(edge.type) % patterns.length], 'marker-end': 'url(#flow-arrow)'}, group);
      svgElement('title', {}, group).textContent = `${edge.type} · ${edge.rows.length} registro(s)${edge.reciprocal ? ' · Também há repasses no sentido oposto' : ''}`;
    });
    const nodesGroup = svgElement('g', {'class': 'graph-nodes'}, viewport);
    nodes.forEach((node, i) => {
      const point = positioned.get(node.id); if (!point) return;
      const radius = radiusFor(node);
      const group = svgElement('g', {'class': 'graph-node', 'data-node': node.id, 'data-kind': node.kind, role: 'button', tabindex: 0, transform: `translate(${point.x},${point.y})`, 'aria-label': `${node.name}, ${kindLabel(node)}, volume ${money(node.volume)}`}, nodesGroup);
      svgElement('circle', {r: Math.max(radius, isCompact() ? 56 : 22), 'class': 'node-hit'}, group);
      svgElement('circle', {r: radius}, group);
      if (!candidateRole(node) || node.roles?.includes('donor') || node.roles?.includes('campaign_financier')) svgElement('circle', {r: radius + 4, 'class': 'node-outline'}, group);
      if (node.id === state.selected) { const initial = svgElement('text', {y: 4, 'text-anchor': 'middle', 'class': 'node-initial'}, group); initial.textContent = node.name.trim().split(/\s+/).slice(0, 2).map(value => value[0]).join(''); }
      if (i < (isCompact() ? 9 : 19) || node.id === state.selected) { const label = svgElement('text', {y: radius + (isCompact() ? 32 : 19), 'text-anchor': 'middle'}, group); const maxLength = isCompact() ? 17 : 23; label.textContent = node.name.length > maxLength ? node.name.slice(0, maxLength - 2) + '…' : node.name; }
      svgElement('title', {}, group).textContent = `${node.name}\nID: ${node.id}\n${kindLabel(node)}\nVolume documentado neste contexto: ${money(node.volume)}`;
    });
    transform = {scale: 1, x: 0, y: 0}; applyTransform(); highlightSelection();
  }
  function highlightSelection() {
    const peers = new Set([state.selected]);
    for (const edge of graphData?.edges || []) if (edge.from_id === state.selected || edge.to_id === state.selected) { peers.add(edge.from_id); peers.add(edge.to_id); }
    const edgeNodes = selectedEdge ? new Set([selectedEdge.from_id, selectedEdge.to_id]) : null;
    document.querySelectorAll('.graph-node').forEach(node => {
      node.classList.toggle('is-selected', node.dataset.node === state.selected || !!edgeNodes?.has(node.dataset.node));
      node.classList.toggle('is-dimmed', !!state.selected && !(edgeNodes || peers).has(node.dataset.node));
    });
    document.querySelectorAll('.graph-edge').forEach(element => {
      const edge = graphData.edges.find(row => row.id === element.dataset.edge);
      const related = edge.from_id === state.selected || edge.to_id === state.selected;
      element.classList.toggle('is-selected', !!selectedEdge && element.dataset.edge === selectedEdge.id);
      element.classList.toggle('is-related', !selectedEdge && related);
      element.classList.toggle('is-dimmed', selectedEdge ? element.dataset.edge !== selectedEdge.id : !!state.selected && !related);
    });
  }
  function applyTransform() { $('graph-viewport').setAttribute('transform', `translate(${transform.x} ${transform.y}) scale(${transform.scale})`); }
  function zoom(factor) {
    const scale = Math.min(4, Math.max(.45, transform.scale * factor)), ratio = scale / transform.scale;
    transform.x = 450 - (450 - transform.x) * ratio; transform.y = 305 - (305 - transform.y) * ratio; transform.scale = scale; applyTransform();
  }
  function exportSVG() {
    if (!graphData?.edges.length) return;
    const svg = $('graph').cloneNode(true), colors = getComputedStyle(document.documentElement);
    svg.setAttribute('xmlns', SVG_NS); svg.setAttribute('width', '1200'); svg.setAttribute('height', '860'); svg.setAttribute('viewBox', '0 0 900 645');
    svg.removeAttribute('aria-describedby'); svg.removeAttribute('class');
    const viewport = svg.querySelector('#graph-viewport'); viewport.setAttribute('transform', '');
    svg.querySelectorAll('.node-hit').forEach(node => node.remove());
    svg.querySelectorAll('[tabindex]').forEach(node => { node.removeAttribute('tabindex'); node.removeAttribute('role'); });
    const style = svgElement('style', {}, svg);
    style.textContent = `text{font-family:Arial,sans-serif;font-size:11px;fill:${colors.getPropertyValue('--ink')};paint-order:stroke;stroke:${colors.getPropertyValue('--paper')};stroke-width:3px}.graph-node circle{fill:${colors.getPropertyValue('--teal')};stroke:${colors.getPropertyValue('--paper')};stroke-width:3px}.graph-node[data-kind=counterparty] circle{fill:${colors.getPropertyValue('--gold')}}.graph-node[data-kind=candidate-donor] circle{fill:${colors.getPropertyValue('--identity-purple')}}.graph-node[data-kind=candidate-campaign] circle{fill:${colors.getPropertyValue('--teal')}}.node-outline{fill:none!important;stroke-dasharray:3 3}.edge-line{fill:none;stroke:${colors.getPropertyValue('--muted')};stroke-opacity:.6}.edge-hit{display:none}.node-initial{fill:${colors.getPropertyValue('--surface')};stroke:none;font-weight:bold}`;
    const bg = svgElement('rect', {width: 900, height: 645, fill: colors.getPropertyValue('--paper')}); svg.insertBefore(bg, svg.firstChild);
    const footer = svgElement('text', {x: 15, y: 632, 'font-size': 9}, svg); footer.textContent = `AFGNET · Goiás 2026 · Base ${date(index.data.generated_at)} · ${graphData.edges.length} vínculos / ${contextRows.length} registros · relação financeira não demonstra irregularidade`;
    const blob = new Blob([new XMLSerializer().serializeToString(svg)], {type: 'image/svg+xml;charset=utf-8'}), url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = 'raio-x-goias-2026.svg'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); announce('Imagem SVG exportada com a data e o limite da visualização.');
  }
  function renderPathOptions() {
    const q = F.normalize($('path-search').value);
    if (!index || !q) { $('path-options').textContent = ''; $('path-search').setAttribute('aria-expanded', 'false'); return; }
    const found = Array.from(index.nodes.values()).filter(node => node.id !== state.selected && F.normalize([node.name, node.civil_name, ...node.aliases].join(' ')).includes(q)).slice(0, 8);
    $('path-options').innerHTML = found.length ? found.map(node => `<button type="button" class="path-option" role="option" aria-selected="false" data-path-target="${esc(node.id)}">${esc(node.name)}<small>${esc(kindLabel(node))} · ID ${esc(node.id)}</small></button>`).join('') : '<p class="filter-help">Nenhuma entidade encontrada.</p>';
    $('path-search').setAttribute('aria-expanded', String(found.length > 0));
  }
  function inspectPath(targetID) {
    const target = index.nodes.get(targetID); if (!target) return;
    $('path-search').value = target.name; $('path-options').textContent = ''; $('path-search').setAttribute('aria-expanded', 'false');
    const result = F.findPath(rows, state.selected, targetID);
    if (result.status !== 'found') { $('path-result').innerHTML = `<p>${result.status === 'limit' ? 'A busca atingiu o limite de 5.000 entidades. Refine os filtros.' : 'Nenhum caminho direcionado documentado foi encontrado em até 4 etapas neste contexto.'}</p><p class="filter-help">Um nome em comum não comprova identidade. Somente identificadores oficiais completos podem confirmar uma pessoa; campanhas permanecem documentadas separadamente.</p>`; return; }
    $('path-result').innerHTML = `<p>${result.rows.length} etapa(s) documentada(s). ${result.rows.length > 1 ? 'Esta é uma relação indireta; não há transferência direta presumida entre os extremos. Valores não são somados como se fossem um único repasse, e o caminho não comprova circulação do mesmo recurso.' : 'Há um registro direto entre as entidades.'}</p>${result.rows.map((row, i) => `<div class="path-hop"><strong>${i + 1}. ${esc(row.from_name || index.nodes.get(row.from_id).name)} → ${esc(row.to_name || index.nodes.get(row.to_id).name)}</strong><p>${money(row.amount)} · ${date(row.date)}<br>${esc(row.type || 'Categoria não informada')}</p><code>ID ${esc(row.id)}</code><br>${sourceLink(row.source_url)}</div>`).join('')}`;
  }
  async function load() {
    $('metrics').setAttribute('aria-busy', 'true'); $('graph-container').setAttribute('aria-busy', 'true');
    try {
      /* Stable component root: immutable release HTML and JS must read the same ETL-owned dataset. */
      const response = await fetch('/eleicoes/goias/raio-x/data/go-2026.json', {cache: 'no-store'});
      if (!response.ok) throw new Error('A base não pôde ser consultada.');
      const data = F.validateData(await response.json()); index = F.buildIndex(data);
      state.selected = index.aliases.get(state.selected) || state.selected;
      if (!index.nodes.has(state.selected)) { state.selected = ''; state.direction = ''; }
      for (const [id, values] of [['party', new Set(data.candidates.map(row => row.party).filter(Boolean))], ['connection-type', new Set(data.transfers.map(row => row.type || 'Categoria não informada'))]]) {
        const select = $(id); Array.from(values).sort((a, b) => a.localeCompare(b, 'pt-BR')).forEach(value => { const option = document.createElement('option'); option.value = value; option.textContent = value; select.appendChild(option); });
      }
      for (const [key, id] of Object.entries(FIELD_IDS)) if (['office', 'party', 'kind', 'type', 'direction'].includes(key) && state[key] && !Array.from($(id).options).some(option => option.value === state[key])) state[key] = '';
      fillFilters();
      if (!state.selected) {
        const candidates = F.filterCandidates(index, state).slice().sort((a, b) => (b.revenue ?? -1) - (a.revenue ?? -1));
        state.selected = candidates.find(candidate => data.transfers.some(row => row.from_id === candidate.id || row.to_id === candidate.id))?.id || candidates[0]?.id || '';
      }
      const revenue = F.sumKnown(data.candidates, 'revenue'), expense = F.sumKnown(data.candidates, 'expenses');
      $('n-candidates').textContent = number(data.candidates.length); $('n-revenue').textContent = shortMoney(revenue.total); $('n-revenue').title = money(revenue.total); $('n-expense').textContent = shortMoney(expense.total); $('n-expense').title = money(expense.total); $('n-edges').textContent = number(data.transfers.length);
      $('revenue-note').textContent = revenue.missing ? `Subtotal · ${number(revenue.missing)} sem valor informado` : 'Soma dos totais por candidatura';
      $('expense-note').textContent = expense.missing ? `Subtotal · ${number(expense.missing)} sem valor informado` : 'Soma dos totais por candidatura';
      const generated = new Date(typeof data.generated_at === 'string' && data.generated_at ? data.generated_at : NaN);
      $('freshness').textContent = !Number.isNaN(generated.getTime()) ? `Base publicada em ${new Intl.DateTimeFormat('pt-BR', {dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Sao_Paulo'}).format(generated)} · Brasília` : 'Data da publicação não informada';
      const audit = data.identity_audit;
      $('identity-summary').textContent = audit ? `${number(audit.candidates_also_personal_donors)} candidatas/os também doadores por identificador pessoal confirmado · ${number(audit.candidates_with_financing_campaigns)} campanhas financiadoras · ${number(audit.inconclusive_donor_entities)} identidades de doadores sem correspondência confirmada com estas candidaturas · ${number(audit.identity_conflicts)} conflitos. Documentos pessoais não são publicados.` : 'Esta versão da base ainda não contém resolução oficial de identidade. Nomes não são usados para unir pessoas.';
      const invalidSources = data.transfers.filter(row => !F.safeSource(row.source_url)).length;
      $('notice').classList.remove('is-error'); $('notice').innerHTML = `<span class="notice-icon" aria-hidden="true">i</span><p>${data.transfers.length ? 'Base pública importada. Uma relação financeira não demonstra irregularidade; valores podem sofrer retificações.' : 'Candidaturas disponíveis. Transferências documentadas ainda não foram publicadas nesta base.'}${invalidSources ? ` ${number(invalidSources)} registro(s) sem URL oficial verificável; links não são exibidos nesses casos.` : ''}</p>`;
      document.querySelectorAll('.metric .skeleton').forEach(node => node.classList.remove('skeleton'));
      render(); syncURL();
    } catch (_) {
      index = null; $('freshness').textContent = 'Base indisponível neste momento'; $('notice').classList.add('is-error'); $('notice').innerHTML = '<span class="notice-icon" aria-hidden="true">i</span><p>Não foi possível validar a base financeira GO / 2026. Não exibimos dados incompletos ou registros fictícios. Tente novamente ou consulte as fontes oficiais.</p><button type="button" class="secondary-button" id="retry-load">Tentar novamente</button>';
      $('candidate-list').innerHTML = '<div class="empty-list">Aguardando uma base financeira válida.</div>'; $('graph-empty').hidden = false; $('graph-empty').querySelector('h4').textContent = 'Dados ainda indisponíveis'; $('graph-empty').querySelector('p').textContent = 'A exploração será liberada quando a base publicada puder ser validada.';
      $('graph-viewport').textContent = ''; $('graph-summary').textContent = 'Nenhum resultado financeiro exibido.'; $('export-graph').disabled = true; $('expand-neighbors').disabled = true;
      $('candidate-prev').disabled = true; $('candidate-next').disabled = true;
      document.querySelectorAll('.metric .skeleton').forEach(node => node.classList.remove('skeleton'));
    } finally { $('metrics').setAttribute('aria-busy', 'false'); $('graph-container').setAttribute('aria-busy', 'false'); }
  }
  const THEME_KEY = 'election-results:theme:v1', themeScheme = matchMedia('(prefers-color-scheme: dark)');
  let themePreference = null;
  try {
    const shared = localStorage.getItem(THEME_KEY), legacy = localStorage.getItem('afg-finance-theme');
    themePreference = shared === 'light' || shared === 'dark' ? shared : legacy === 'light' || legacy === 'dark' ? legacy : null;
    if (!shared && themePreference) localStorage.setItem(THEME_KEY, themePreference);
  } catch (_) { /* Theme remains usable without storage. */ }
  function setTheme(value, save = false) {
    const theme = value === 'dark' ? 'dark' : 'light';
    document.documentElement.dataset.theme = theme;
    $('theme-toggle').setAttribute('aria-pressed', String(theme === 'dark')); $('theme-toggle').setAttribute('aria-label', theme === 'dark' ? 'Ativar modo claro' : 'Ativar modo escuro');
    if (save) {
      themePreference = theme;
      try { localStorage.setItem(THEME_KEY, theme); } catch (_) { /* Preferences are optional. */ }
    }
  }
  setTheme(themePreference || (themeScheme.matches ? 'dark' : 'light'));
  $('theme-toggle').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark', true));
  window.addEventListener('storage', event => {
    if (event.key !== THEME_KEY) return;
    themePreference = event.newValue === 'light' || event.newValue === 'dark' ? event.newValue : null;
    setTheme(themePreference || (themeScheme.matches ? 'dark' : 'light'));
  });
  themeScheme.addEventListener('change', event => { if (!themePreference) setTheme(event.matches ? 'dark' : 'light'); });
  $('filters-form').addEventListener('submit', event => event.preventDefault());
  $('filters-form').addEventListener('input', () => {
    if (!filterValues()) return;
    candidatePage = 0; tablePage = 0; detailPage = 0; selectedEdge = null; $('path-result').textContent = '';
    clearTimeout(scheduledRender); scheduledRender = setTimeout(() => {
      const selected = index?.nodes.get(state.selected);
      if (selected && candidateRole(selected) && ((state.office && selected.office !== state.office) || (state.party && selected.party !== state.party))) state.selected = '';
      render(); syncURL();
    }, 140);
  });
  $('reset-filters').addEventListener('click', () => { const selected = state.selected; state = F.fromQuery(''); state.selected = selected; candidatePage = 0; tablePage = 0; detailPage = 0; selectedEdge = null; fillFilters(); $('path-result').textContent = ''; filterValues(); render(); syncURL(); });
  $('candidate-list').addEventListener('click', event => { const button = event.target.closest('[data-candidate]'); if (button) selectNode(button.dataset.candidate, {candidate: true, restoreCandidateFocus: event.detail === 0}); });
  $('candidate-prev').addEventListener('click', () => { candidatePage = Math.max(0, candidatePage - 1); renderCandidates(); $('candidate-list').scrollTop = 0; });
  $('candidate-next').addEventListener('click', () => { candidatePage += 1; renderCandidates(); $('candidate-list').scrollTop = 0; });
  $('table-prev').addEventListener('click', () => { tablePage = Math.max(0, tablePage - 1); renderTable(); });
  $('table-next').addEventListener('click', () => { tablePage += 1; renderTable(); });
  $('table-view-button').addEventListener('click', () => { state.view = 'table'; renderView(); syncURL(); });
  $('graph-view-button').addEventListener('click', () => { state.view = 'graph'; renderView(); syncURL(); });
  $('filters-toggle').addEventListener('click', () => { const open = $('filters-panel').classList.toggle('is-open'); $('filters-toggle').setAttribute('aria-expanded', String(open)); if (open) $('search').focus({preventScroll: true}); });
  $('expand-neighbors').addEventListener('click', () => { state.depth = state.depth === 2 ? 1 : 2; selectedEdge = null; tablePage = 0; render(); syncURL(); });
  $('clear-selection').addEventListener('click', () => { if (selectedEdge) { selectedEdge = null; renderDetail(); highlightSelection(); } else { state.selected = ''; state.direction = ''; $('identity-direction').value = ''; $('path-search').value = ''; $('path-result').textContent = ''; render(); syncURL(); } });
  $('guide-start').addEventListener('click', () => { $('workspace').scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start'}); if (matchMedia('(max-width: 680px)').matches) { $('filters-panel').classList.add('is-open'); $('filters-toggle').setAttribute('aria-expanded', 'true'); } $('search').focus({preventScroll: true}); });
  $('detail-content').addEventListener('click', event => {
    const node = event.target.closest('[data-node]'); if (node) { selectNode(node.dataset.node); return; }
    const page = event.target.closest('[data-detail-page]'); if (page) { detailPage += Number(page.dataset.detailPage); renderDetail(); }
  });
  $('transfer-table').addEventListener('click', event => { const button = event.target.closest('[data-record]'); if (!button) return; const row = contextRows.find(record => record.id === button.dataset.record); if (row) selectEdge(F.aggregate(contextRows).find(group => group.rows.some(record => record.id === row.id)).id); });
  document.querySelectorAll('button[data-kind]').forEach(button => button.addEventListener('click', () => { state.kind = state.kind === button.dataset.kind ? '' : button.dataset.kind; fillFilters(); selectedEdge = null; render(); syncURL(); }));
  $('path-search').addEventListener('input', renderPathOptions);
  $('path-search').addEventListener('keydown', event => { if (event.key === 'ArrowDown') { const option = $('path-options').querySelector('button'); if (option) { event.preventDefault(); option.focus(); } } if (event.key === 'Escape') { $('path-options').textContent = ''; $('path-search').setAttribute('aria-expanded', 'false'); } });
  $('path-options').addEventListener('keydown', event => { const options = Array.from($('path-options').querySelectorAll('button')), at = options.indexOf(document.activeElement); if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); options[(at + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length]?.focus(); } if (event.key === 'Escape') { $('path-search').focus(); $('path-options').textContent = ''; $('path-search').setAttribute('aria-expanded', 'false'); } });
  $('path-options').addEventListener('click', event => { const option = event.target.closest('[data-path-target]'); if (option) inspectPath(option.dataset.pathTarget); });
  $('zoom-in').addEventListener('click', () => zoom(1.2)); $('zoom-out').addEventListener('click', () => zoom(1 / 1.2));
  $('fit-graph').addEventListener('click', () => { transform = {scale: 1, x: 0, y: 0}; applyTransform(); });
  $('export-graph').addEventListener('click', exportSVG);
  $('graph').addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') { const target = event.target.closest('[data-node],[data-edge]'); if (!target) return; event.preventDefault(); if (target.dataset.node) selectNode(target.dataset.node, {focusDetail: true}); else selectEdge(target.dataset.edge); }
  });
  $('graph').addEventListener('click', event => { if (pointer?.moved) return; const target = event.target.closest('[data-node],[data-edge]'); if (target?.dataset.node) selectNode(target.dataset.node); else if (target?.dataset.edge) selectEdge(target.dataset.edge); });
  $('graph').addEventListener('wheel', event => { if (!event.ctrlKey && !event.metaKey) return; event.preventDefault(); zoom(event.deltaY < 0 ? 1.1 : 1 / 1.1); }, {passive: false});
  $('graph').addEventListener('pointerdown', event => {
    if (event.target.closest('[data-node],[data-edge]') || event.button > 0) return;
    pointer = {id: event.pointerId, x: event.clientX, y: event.clientY, tx: transform.x, ty: transform.y, moved: false}; $('graph').setPointerCapture(event.pointerId); $('graph').classList.add('is-panning');
  });
  $('graph').addEventListener('pointermove', event => {
    if (!pointer || pointer.id !== event.pointerId) return;
    const bounds = $('graph').getBoundingClientRect(), ratio = Math.max(900 / bounds.width, 620 / bounds.height);
    const dx = (event.clientX - pointer.x) * ratio, dy = (event.clientY - pointer.y) * ratio; pointer.moved = Math.hypot(dx, dy) > 3;
    transform.x = pointer.tx + dx; transform.y = pointer.ty + dy; applyTransform();
  });
  const finishPan = () => { $('graph').classList.remove('is-panning'); setTimeout(() => { pointer = null; }, 0); };
  $('graph').addEventListener('pointerup', finishPan); $('graph').addEventListener('pointercancel', finishPan);
  $('share-button').addEventListener('click', async () => { syncURL(); try { await navigator.clipboard.writeText(location.href); announce('Link copiado com os filtros e a entidade selecionada.'); } catch (_) { announce('Selecione e copie o endereço do navegador para compartilhar os filtros.'); } });
  $('notice').addEventListener('click', event => { if (event.target.closest('#retry-load')) load(); });
  window.addEventListener('popstate', () => { state = F.fromQuery(location.search); fillFilters(); selectedEdge = null; if (index && !index.nodes.has(state.selected)) state.selected = ''; render(); });
  fillFilters(); load();
})();
