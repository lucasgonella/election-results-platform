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
  const rolesHTML = node => (node.roles || []).filter(role => ['candidate', 'donor', 'campaign_financier'].includes(role)).map(role => `<span class="role-badge">${esc({candidate: 'Candidata/o', donor: candidateRole(node) ? 'Doadora/or por CPF confirmado' : 'Pessoa doadora', campaign_financier: 'Campanha financiadora'}[role])}</span>`).join('');
  const FIELD_IDS = {q: 'search', office: 'office', party: 'party', kind: 'entity-kind', type: 'connection-type', from: 'financier', to: 'recipient', min: 'min-value', max: 'max-value', start: 'start-date', end: 'end-date', direction: 'identity-direction'};
  let state = F.fromQuery(location.search), index = null, rows = [], contextRows = [], graphData = null, directCoverage = null, candidatePage = 0, tablePage = 0, detailPage = 0, selectedEdge = null;
  let transform = {scale: 1, x: 0, y: 0}, toastTimer = null, scheduledRender = null;
  let positioned = new Map(), hoveredID = '', cameraFrame = null, firstFrame = true, suppressClickUntil = 0;
  const activePointers = new Map(), layoutCache = new Map(); let gesture = null;
  let navigation = [{key: 0, selected: '', query: ''}], navigationAt = 0, navigationKey = 0, cameraTimer = null;
  const PAGE_SIZE = 20, TABLE_SIZE = 30, DETAIL_SIZE = 15, SVG_NS = 'http://www.w3.org/2000/svg';
  function announce(message) {
    $('toast').textContent = message; $('toast').hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, 3200);
  }
  function syncURL(push = false) {
    const query = F.toQuery(state);
    if (push && navigation[navigationAt].selected !== state.selected) {
      navigation = navigation.slice(0, navigationAt + 1);
      navigation.push({key: ++navigationKey}); navigationAt++;
    } else push = false;
    navigation[navigationAt] = {...navigation[navigationAt], selected: state.selected, query};
    const snapshot = {raiox: {key: navigation[navigationAt].key, camera: {...transform}, positions: [...positioned]}};
    history[push ? 'pushState' : 'replaceState'](snapshot, '', `${location.pathname}${query ? '?' + query : ''}${location.hash}`);
    renderNavigation();
  }
  function renderNavigation() {
    $('navigation-back').disabled = navigationAt === 0;
    $('navigation-forward').disabled = navigationAt >= navigation.length - 1;
    $('navigation-trail').innerHTML = navigation.slice(Math.max(0, navigationAt - 3), navigationAt + 1).map(entry => {
      const name = index?.nodes.get(entry.selected)?.name || 'Visão geral';
      return `<button type="button" data-navigation="${entry.key}" ${entry.key === navigation[navigationAt].key ? 'aria-current="step" disabled' : ''}>${esc(name)}</button>`;
    }).join('<span aria-hidden="true">→</span>');
  }
  function rememberCamera() {
    clearTimeout(cameraTimer);
    cameraTimer = setTimeout(() => { if (index) syncURL(); }, 250);
  }
  function fillFilters() {
    for (const [key, id] of Object.entries(FIELD_IDS)) $(id).value = state[key] || '';
  }
  function filterValues() {
    for (const [key, id] of Object.entries(FIELD_IDS)) state[key] = $(id).value;
    for (const key of ['q', 'from', 'to']) {
      if (F.personalDocumentInput(state[key])) {
        state[key] = ''; $(FIELD_IDS[key]).value = '';
        announce('Busca por CPF indisponível. Pesquise pelo nome; o documento não será incluído no link.');
      }
    }
    const invalidValues = state.min !== '' && state.max !== '' && Number(state.min) > Number(state.max);
    const invalidDates = state.start && state.end && state.start > state.end;
    $('max-value').setCustomValidity(invalidValues ? 'O valor máximo deve ser maior ou igual ao mínimo.' : '');
    $('end-date').setCustomValidity(invalidDates ? 'A data final deve ser posterior ou igual à data inicial.' : '');
    return !invalidValues && !invalidDates;
  }
  function updateFilterCount() {
    $('filter-count').textContent = Object.keys(FIELD_IDS).filter(key => key !== 'q' && !!state[key]).length;
    document.querySelectorAll('[data-kind]').forEach(button => {
      if (button.tagName === 'BUTTON') button.setAttribute('aria-pressed', String(state.kind === button.dataset.kind));
    });
  }
  function renderCandidates() {
    if (!index) return;
    const result = F.searchEntities(index, state, {limit: PAGE_SIZE, offset: candidatePage * PAGE_SIZE});
    const pages = Math.max(1, Math.ceil(result.total / PAGE_SIZE));
    candidatePage = Math.floor(result.offset / PAGE_SIZE);
    $('list-count').textContent = number(result.total);
    $('candidate-list').innerHTML = result.total ? result.items.map(node => {
      const candidate = candidateRole(node);
      const summary = candidate ? `${node.party || 'Partido não informado'} · ${node.number || 'Número não informado'} · ${node.office === 'deputado federal' ? 'Federal' : 'Estadual'}` : 'Registro de origem na base oficial';
      return `<button type="button" class="candidate-button" data-candidate="${esc(node.id)}" aria-pressed="${state.selected === node.id}" aria-label="${esc(node.name)}, ${esc(kindLabel(node))}, registro ${esc(node.id)}"><strong>${esc(node.name)}</strong><span class="search-role">${esc(kindLabel(node))}</span><small>${esc(summary)}</small>${node.civil_name && node.civil_name !== node.name ? `<small>Nome civil: ${esc(node.civil_name)}</small>` : ''}<small class="search-identity">Registro ${esc(node.id.slice(-8))}</small>${candidate ? `<span class="candidate-amount">${shortMoney(node.revenue)} <small>receitas declaradas</small></span>` : ''}</button>`;
    }).join('') : '<div class="empty-list">Nenhuma entidade corresponde à busca. Experimente outro nome ou ajuste cargo, partido e tipo. Nomes iguais continuam separados por identidade oficial.</div>';
    $('candidate-page').textContent = `${result.total ? result.offset + 1 : 0}–${Math.min(result.offset + PAGE_SIZE, result.total)} de ${number(result.total)}`;
    $('candidate-prev').disabled = candidatePage === 0; $('candidate-next').disabled = candidatePage >= pages - 1;
  }
  function selectNode(id, options = {}) {
    if (!index) return;
    id = F.resolveSelection(index, id); if (!id) { announce('A entidade não está disponível nesta base.'); return; }
    syncURL(); // Save the previous camera before changing the exploration root.
    state.selected = id; state.q = ''; state.depth = 1; $('search').value = '';
    selectedEdge = null; detailPage = 0; tablePage = 0;
    $('path-search').value = ''; $('path-options').textContent = ''; $('path-result').textContent = '';
    const returnToGraph = options.candidate && isCompact();
    if (returnToGraph) {
      $('filters-panel').classList.remove('is-open'); $('filters-toggle').setAttribute('aria-expanded', 'false');
    }
    render(); centerSelection(); syncURL(true);
    if (returnToGraph) { $('graph-title').setAttribute('tabindex', '-1'); $('graph-title').focus({preventScroll: true}); }
    else if (options.restoreCandidateFocus) { Array.from($('candidate-list').querySelectorAll('[data-candidate]')).find(button => button.dataset.candidate === id)?.focus({preventScroll: true}); }
    if (options.focusDetail) { $('detail-title').setAttribute('tabindex', '-1'); $('detail-title').focus({preventScroll: true}); }
  }
  function selectEdge(id) {
    selectedEdge = F.aggregate(contextRows).find(edge => edge.id === id) || null;
    detailPage = 0; renderDetail(); highlightSelection();
  }
  function context() {
    const filters = F.explicitFinanceFilters(state);
    rows = F.filterTransfers(index, {...filters, selected: state.selected});
    directCoverage = state.selected ? F.getExplorationConnections(index, state.selected, filters, state.depth) : null;
    contextRows = directCoverage ? directCoverage.records : rows;
    graphData = F.graphView(index, contextRows, state.selected, state.depth, isCompact() ? {nodes: 36, edges: 65} : {});
  }
  function goGeneral(options = {}) {
    if (!index) return;
    syncURL();
    state.selected = ''; state.depth = 1;
    selectedEdge = null; detailPage = 0; tablePage = 0; hoveredID = '';
    $('path-search').value = ''; $('path-options').textContent = ''; $('path-result').textContent = '';
    hideTooltip(); render();
    if (options.fit) fitGraph();
    syncURL(true);
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
    $('identity-direction').disabled = !node;
    if (selectedEdge) {
      const origin = index.nodes.get(selectedEdge.from_id), target = index.nodes.get(selectedEdge.to_id);
      $('detail-title').textContent = 'Um vínculo, seus registros';
      $('detail-content').innerHTML = `<span class="entity-label">TRANSFERÊNCIA DIRETA DOCUMENTADA</span><p class="profile-meta">${esc(origin.name)} <b>→</b> ${esc(target.name)}</p><div class="profile-metrics"><div class="profile-metric"><small>${selectedEdge.missing ? 'Subtotal informado' : 'Soma dos registros'}</small><strong>${money(selectedEdge.total)}</strong></div><div class="profile-metric"><small>Registros agrupados</small><strong>${number(selectedEdge.rows.length)}</strong></div></div><p class="muted">${esc(selectedEdge.type)}</p>${selectedEdge.missing ? `<p class="subtotal-note">${selectedEdge.missing} registro(s) sem valor. A soma não é um total completo.</p>` : ''}${selectedEdge.reciprocal ? '<p class="muted">Há também registros no sentido oposto dentro dos filtros. Cada sentido permanece separado.</p>' : ''}<p class="filter-help">A seta representa o sentido declarado. A existência da relação não demonstra irregularidade.</p><h4>Datas, identificadores e evidências</h4>${recordListHTML(selectedEdge.rows)}`;
      return;
    }
    if (!node) {
      $('detail-title').textContent = 'Visão geral';
      $('detail-content').innerHTML = '<p class="muted">Explore a rede sem uma pessoa selecionada. Passe o mouse para ver um resumo; clique em uma pessoa ou vínculo para abrir os registros.</p><p class="filter-help">A busca inclui candidaturas, doadores e campanhas de toda a base, inclusive entidades fora do limite visual. Pessoas com nomes iguais permanecem separadas.</p><div class="context-illustration" aria-hidden="true"><span></span><i></i><span></span></div><p class="filter-help">Ctrl + rolagem aproxima o ponto sob o cursor. Arraste para mover; use Ajustar à tela para reenquadrar. A tabela mantém todos os registros dos filtros.</p>';
      return;
    }
    const incoming = rows.filter(row => row.to_id === node.id), outgoing = rows.filter(row => row.from_id === node.id);
    const inbound = F.sumKnown(incoming), outbound = F.sumKnown(outgoing), peers = new Set([...incoming.map(row => row.from_id), ...outgoing.map(row => row.to_id)]);
    const candidates = candidateRole(node);
    $('detail-title').textContent = node.name;
    const roleMetrics = `<div class="profile-metric"><small>Repasses realizados nos filtros${outbound.missing ? ' · subtotal' : ''}</small><strong>${money(outbound.total)}</strong></div><div class="profile-metric"><small>Recebido nos filtros${inbound.missing ? ' · subtotal' : ''}</small><strong>${money(inbound.total)}</strong></div><div class="profile-metric"><small>Campanhas beneficiadas nos filtros</small><strong>${number(new Set(outgoing.map(row => row.to_campaign_id || row.candidate_id || row.to_id)).size)}</strong></div>`;
    const metrics = candidates ? `<div class="profile-metric"><small>Receita total declarada</small><strong>${money(node.revenue)}</strong></div><div class="profile-metric"><small>Despesa total declarada</small><strong>${money(node.expenses)}</strong></div><div class="profile-metric"><small>Votos publicados nesta base</small><strong>${number(node.votes)}</strong></div><div class="profile-metric"><small>Contrapartes nos filtros</small><strong>${number(peers.size)}</strong></div>` : `<div class="profile-metric"><small>Contrapartes nos filtros</small><strong>${number(peers.size)}</strong></div>`;
    const direct = [...incoming, ...outgoing.filter(row => row.from_id !== row.to_id)].sort((a, b) => (b.amount ?? -1) - (a.amount ?? -1));
    const topGroups = F.aggregate(incoming).sort((a, b) => (b.total ?? -1) - (a.total ?? -1)).slice(0, 5);
    $('detail-content').innerHTML = `<span class="entity-label">${esc(kindLabel(node).toLocaleUpperCase('pt-BR'))}</span>${node.candidacies?.length > 1 ? `<p class="profile-meta">${node.candidacies.map(c => `${esc(c.ballot_name || c.name)} · ${esc(c.office)} · ${esc(c.party)} · TSE ${esc(c.id)}`).join('<br>')}</p>` : ''}<p class="profile-meta">${candidates ? `${esc(node.office)} · ${esc(node.party || 'Partido não informado')} · ${esc(node.number || 'Número não informado')}<br>${esc(node.status || 'Situação não informada')}` : esc(kindLabel(node))}</p><p class="entity-id">ID interno: ${esc(node.id)}${node.candidate_ids?.length ? ' · candidatura TSE: ' + node.candidate_ids.map(esc).join(', ') : ''}</p>${node.aliases.length ? `<details class="official-names"><summary>${number(node.aliases.length)} variações oficiais neste mesmo ID</summary><p class="filter-help">${node.aliases.map(esc).join(' · ')}. Os nomes originais são preservados em cada registro.</p></details>` : ''}<div class="role-badges">${rolesHTML(node)}</div>${node.civil_name ? `<p class="profile-meta">Nome civil: <strong>${esc(node.civil_name)}</strong></p>` : ''}${node.evidence?.length ? `<details class="identity-evidence"><summary>Campanhas e evidências da associação</summary>${node.candidate_ids?.length ? `<p>Registro oficial de candidatura: ${node.candidate_ids.map(esc).join(', ')}</p>${sourceLink(node.source_url)}` : ''}${(node.campaigns || []).map(campaign => `<p>${esc(campaign.name)}<br>CNPJ de campanha: ${esc(campaign.cnpj)}<br>Candidatura: ${campaign.candidate_ids.map(esc).join(', ')}</p>${sourceLink(campaign.evidence[0]?.source_url)}`).join('')}${node.roles.includes('donor') ? '<p>Identidade pessoal confirmada por igualdade de CPF completo nos arquivos oficiais, sem publicar o documento.</p>' : '<p>Repasses de campanha não são classificados como doações pessoais.</p>'}</details>` : ''}<div class="profile-metrics">${metrics}${roleMetrics}</div>${candidates ? '<p class="filter-help">Receitas e despesas são totais da candidatura na base, independentes dos filtros da rede. Votos ausentes não são zero.</p>' : ''}${inbound.missing || outbound.missing ? '<p class="subtotal-note">Há valores não informados neste contexto. Somas incluem apenas os registros com valor.</p>' : ''}${topGroups.length ? `<h4>Principais origens nos filtros</h4><div>${topGroups.map(group => `<div class="record"><button type="button" data-node="${esc(group.from_id)}">${esc(index.nodes.get(group.from_id).name)} →</button><p>${money(group.total)} · ${number(group.rows.length)} registro(s)</p></div>`).join('')}</div>` : ''}<h4>${number(direct.length)} registros diretos nos filtros</h4>${direct.length ? recordListHTML(direct) : '<p class="muted">Nenhuma transferência documentada neste contexto. Isso não equivale a ausência de atividade financeira.</p>'}`;
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
    hoveredID = ''; hideTooltip();
    const center = index.nodes.get(state.selected), nodes = graphData.nodes;
    $('graph-title').textContent = center ? center.name : 'Visão geral';
    $('graph-depth').textContent = !center ? 'VISÃO GERAL · RELAÇÕES NOS FILTROS' : state.depth > 1 ? `DIRETAS + ATÉ ${state.depth} NÍVEIS DOCUMENTADOS` : 'CONEXÕES DIRETAS';
    $('center-selection').disabled = !center;
    $('overview-button').setAttribute('aria-pressed', String(!center));
    $('expand-neighbors').disabled = !center || !contextRows.length;
    $('expand-neighbors').textContent = state.depth === 3 ? 'Voltar às diretas' : `Expandir ${state.depth + 1}º nível`;
    $('connection-coverage').textContent = directCoverage ? `${number(directCoverage.available)} registros diretos na base · ${number(directCoverage.available - directCoverage.excludedByFilters)} nos filtros${directCoverage.excludedByFilters ? ` · ${number(directCoverage.excludedByFilters)} ocultos pelos filtros explícitos. Use Limpar filtros para incluí-los.` : '. A busca por nome não restringe as relações.'}` : 'Cada entidade abre sua própria rede completa na base publicada. Os limites do desenho não limitam a busca nem a tabela.';
    $('graph-summary').textContent = `${number(nodes.length)} entidades · ${number(graphData.edges.length)} vínculos agrupados · ${number(contextRows.length)} registros no contexto${graphData.hiddenEdges || graphData.hiddenNodes ? `. Limite visual: ${number(graphData.hiddenNodes)} entidades e ${number(graphData.hiddenEdges)} vínculos fora do desenho. Consulte a tabela.` : '.'}`;
    const empty = !graphData.edges.length;
    $('graph-empty').hidden = !empty || nodes.length > 0;
    $('export-graph').disabled = empty;
    if (!nodes.length) {
      $('graph-empty').querySelector('h4').textContent = index.data.transfers.length ? 'Sem relações neste contexto' : 'Aguardando relações documentadas';
      $('graph-empty').querySelector('p').textContent = index.data.transfers.length ? 'Selecione outra candidatura ou ajuste os filtros. Nenhuma conexão será presumida a partir de nomes iguais.' : 'A base ainda não contém transferências verificadas. Candidaturas e valores disponíveis continuam acessíveis.';
      applyTransform(); return;
    }
    const maxVolume = Math.max(1, ...nodes.map(node => node.volume));
    const radiusFor = node => node.id === state.selected ? 31 : 8 + 16 * Math.sqrt(node.volume / maxVolume);
    const layoutKey = JSON.stringify([isCompact(), state.selected, nodes.map(node => node.id).sort(), graphData.edges.map(edge => edge.id).sort()]);
    if (layoutCache.has(layoutKey)) positioned = layoutCache.get(layoutKey);
    else {
      positioned = F.stableLayout(nodes, graphData.edges, {previous: positioned, selected: state.selected, radius: radiusFor, compact: isCompact()});
      if (layoutCache.size >= 24) layoutCache.delete(layoutCache.keys().next().value);
      layoutCache.set(layoutKey, positioned);
    }
    const maxAmount = Math.max(1, ...graphData.edges.map(edge => edge.total ?? 0));
    const categories = Array.from(new Set(graphData.edges.map(edge => edge.type))).sort();
    const patterns = ['', '7 4', '2 4', '10 3 2 3'];
    const edgesGroup = svgElement('g', {'class': 'graph-edges'}, viewport);
    graphData.edges.forEach((edge, rank) => {
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
      const value = svgElement('text', {x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 - 10, 'text-anchor': 'middle', 'class': 'edge-value-label', 'data-rank': rank, 'aria-hidden': 'true'}, group);
      value.textContent = shortMoney(edge.total);
      svgElement('title', {}, group).textContent = `${edge.type} · ${edge.rows.length} registro(s)${edge.reciprocal ? ' · Também há repasses no sentido oposto' : ''}`;
    });
    const nodesGroup = svgElement('g', {'class': 'graph-nodes'}, viewport);
    nodes.forEach((node, i) => {
      const point = positioned.get(node.id); if (!point) return;
      const radius = radiusFor(node);
      const group = svgElement('g', {'class': 'graph-node', 'data-node': node.id, 'data-kind': node.kind, role: 'button', tabindex: 0, transform: `translate(${point.x},${point.y})`, 'aria-label': `${node.name}, ${kindLabel(node)}, volume ${money(node.volume)}`}, nodesGroup);
      svgElement('circle', {r: Math.max(radius, isCompact() ? 56 : 22), 'class': 'node-hit'}, group);
      svgElement('circle', {r: radius}, group);
      if (node.kind === 'organization') svgElement('rect', {x: -radius - 5, y: -radius - 5, width: 2 * (radius + 5), height: 2 * (radius + 5), rx: 4, 'class': 'node-outline'}, group);
      else if (!candidateRole(node) || node.roles?.includes('donor') || node.roles?.includes('campaign_financier')) svgElement('circle', {r: radius + 4, 'class': 'node-outline'}, group);
      if (node.id === state.selected) { const initial = svgElement('text', {y: 4, 'text-anchor': 'middle', 'class': 'node-initial'}, group); initial.textContent = node.name.trim().split(/\s+/).slice(0, 2).map(value => value[0]).join(''); }
      const label = svgElement('text', {y: radius + 19, 'text-anchor': 'middle', 'class': 'node-label', 'data-rank': i, 'data-radius': radius, 'aria-hidden': 'true'}, group);
      const maxLength = isCompact() ? 19 : 25;
      label.textContent = node.name.length > maxLength ? node.name.slice(0, maxLength - 2) + '…' : node.name;
    });
    if (firstFrame) { firstFrame = false; fitGraph(); if (center) centerSelection(); }
    else applyTransform();
    highlightSelection();
  }
  function highlightSelection() {
    const active = hoveredID || state.selected, peers = new Set([active]);
    for (const edge of graphData?.edges || []) if (edge.from_id === active || edge.to_id === active) { peers.add(edge.from_id); peers.add(edge.to_id); }
    const edgeNodes = !hoveredID && selectedEdge ? new Set([selectedEdge.from_id, selectedEdge.to_id]) : null;
    document.querySelectorAll('.graph-node').forEach(node => {
      node.classList.toggle('is-selected', node.dataset.node === state.selected || !!edgeNodes?.has(node.dataset.node));
      node.classList.toggle('is-hovered', node.dataset.node === hoveredID);
      node.classList.toggle('is-dimmed', !!active && !(edgeNodes || peers).has(node.dataset.node));
    });
    document.querySelectorAll('.graph-edge').forEach(element => {
      const edge = graphData.edges.find(row => row.id === element.dataset.edge);
      if (!edge) return; // focusout can fire while the old SVG is being replaced.
      const related = edge.from_id === active || edge.to_id === active;
      element.classList.toggle('is-selected', !!selectedEdge && element.dataset.edge === selectedEdge.id);
      element.classList.toggle('is-related', (!!hoveredID || !selectedEdge) && related);
      element.classList.toggle('is-dimmed', !hoveredID && selectedEdge ? element.dataset.edge !== selectedEdge.id : !!active && !related);
    });
    updateLabels();
  }
  function svgPoint(clientX, clientY) {
    const matrix = $('graph').getScreenCTM();
    return matrix ? new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse()) : {x: 450, y: 310};
  }
  function applyTransform() {
    if (cameraFrame !== null) cancelAnimationFrame(cameraFrame);
    cameraFrame = null;
    $('graph-viewport').setAttribute('transform', `translate(${transform.x} ${transform.y}) scale(${transform.scale})`);
    $('zoom-level').textContent = `${Math.round(transform.scale * 100)}%`;
    updateLabels();
  }
  function requestCamera() {
    if (cameraFrame === null) cameraFrame = requestAnimationFrame(applyTransform);
  }
  function zoom(factor, anchor = {x: 450, y: 310}) {
    transform = F.zoomAt(transform, factor, anchor); requestCamera(); rememberCamera();
  }
  function fitGraph() {
    transform = F.fitCamera(F.layoutBounds(positioned, graphData?.nodes || [], 38)); applyTransform();
  }
  function centerSelection() {
    const point = positioned.get(state.selected);
    if (!point) { announce('A entidade não está no desenho atual. Selecione-a na busca para abrir seu contexto.'); return; }
    transform = F.centerCamera(transform, point); applyTransform();
  }
  function updateLabels() {
    if (!graphData) return;
    const matrix = $('graph').getScreenCTM(), unit = matrix ? Math.hypot(matrix.a, matrix.b) : 1;
    const font = 11 / (transform.scale * Math.max(.1, unit)), occupied = [];
    const labels = Array.from($('graph-viewport').querySelectorAll('.node-label'));
    labels.sort((a, b) => Number(b.parentNode.dataset.node === hoveredID || b.parentNode.dataset.node === state.selected) - Number(a.parentNode.dataset.node === hoveredID || a.parentNode.dataset.node === state.selected) || Number(a.dataset.rank) - Number(b.dataset.rank));
    const overviewLimit = isCompact() ? 4 : 8; let shown = 0;
    for (const label of labels) {
      const id = label.parentNode.dataset.node, point = positioned.get(id), important = id === state.selected || id === hoveredID;
      const y = Number(label.dataset.radius) + font * 1.65, width = label.textContent.length * font * .57;
      const box = {x: point.x - width / 2, y: point.y + y - font, width, height: font * 1.45};
      const screen = {x: box.x * transform.scale + transform.x, y: box.y * transform.scale + transform.y};
      const inFrame = screen.x + width * transform.scale > 0 && screen.x < 900 && screen.y + box.height * transform.scale > 0 && screen.y < 620;
      const overlaps = occupied.some(other => box.x < other.x + other.width && box.x + box.width > other.x && box.y < other.y + other.height && box.y + box.height > other.y);
      const visible = important || inFrame && !overlaps && (transform.scale >= 1.5 || shown < overviewLimit);
      label.style.display = visible ? '' : 'none'; label.style.fontSize = `${font}px`; label.style.strokeWidth = `${font * .22}px`; label.setAttribute('y', y);
      if (visible) { occupied.push(box); shown++; }
    }
    $('graph-viewport').querySelectorAll('.edge-value-label').forEach(label => {
      const selected = label.parentNode.classList.contains('is-selected');
      label.style.display = (transform.scale >= 2 && Number(label.dataset.rank) < 18 || selected) ? '' : 'none';
      label.style.fontSize = `${font}px`; label.style.strokeWidth = `${font * .3}px`;
    });
  }
  function hideTooltip() {
    $('graph-tooltip').hidden = true;
    $('graph').querySelectorAll('[aria-describedby="graph-tooltip"]').forEach(node => node.removeAttribute('aria-describedby'));
  }
  function hoverNode(element, event) {
    const id = element?.dataset.node || '', node = index?.nodes.get(id);
    if (hoveredID !== id) { hoveredID = id; highlightSelection(); }
    if (!node) { hideTooltip(); return; }
    const tooltip = $('graph-tooltip');
    tooltip.textContent = `${node.name}\n${kindLabel(node)} · ${money(graphData.nodes.find(item => item.id === id)?.volume)}`;
    tooltip.hidden = false; element.setAttribute('aria-describedby', 'graph-tooltip');
    const bounds = $('graph-container').getBoundingClientRect(), point = element.getBoundingClientRect();
    const x = event?.clientX ?? point.x + point.width / 2, y = event?.clientY ?? point.y + point.height / 2;
    tooltip.style.left = `${Math.max(8, Math.min(bounds.width - Math.min(250, bounds.width - 16), x - bounds.x + 14))}px`;
    tooltip.style.top = `${Math.max(8, Math.min(bounds.height - tooltip.offsetHeight - 12, y - bounds.y + 14))}px`;
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
    style.textContent = `text{font-family:Arial,sans-serif;font-size:11px;fill:${colors.getPropertyValue('--ink')};paint-order:stroke;stroke:${colors.getPropertyValue('--paper')};stroke-width:3px}.graph-node circle{fill:${colors.getPropertyValue('--teal')};stroke:${colors.getPropertyValue('--paper')};stroke-width:3px}.graph-node[data-kind=counterparty] circle{fill:${colors.getPropertyValue('--gold')}}.graph-node[data-kind=organization] circle{fill:${colors.getPropertyValue('--organization-blue')}}.graph-node[data-kind=organization] .node-outline{stroke:${colors.getPropertyValue('--organization-blue')};stroke-dasharray:none}.graph-node[data-kind=candidate-donor] circle{fill:${colors.getPropertyValue('--identity-purple')}}.graph-node[data-kind=candidate-campaign] circle{fill:${colors.getPropertyValue('--teal')}}.node-outline{fill:none!important;stroke-dasharray:3 3}.edge-line{fill:none;stroke:${colors.getPropertyValue('--muted')};stroke-opacity:.6}.edge-hit{display:none}.node-initial{fill:${colors.getPropertyValue('--surface')};stroke:none;font-weight:bold}`;
    const bg = svgElement('rect', {width: 900, height: 645, fill: colors.getPropertyValue('--paper')}); svg.insertBefore(bg, svg.firstChild);
    const footer = svgElement('text', {x: 15, y: 632, 'font-size': 9}, svg); footer.textContent = `AFGNET · Goiás 2026 · Base ${date(index.data.generated_at)} · ${graphData.edges.length} vínculos / ${contextRows.length} registros · relação financeira não demonstra irregularidade`;
    const blob = new Blob([new XMLSerializer().serializeToString(svg)], {type: 'image/svg+xml;charset=utf-8'}), url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = 'raio-x-goias-2026.svg'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); announce('Imagem SVG exportada com a data e o limite da visualização.');
  }
  function renderPathOptions() {
    if (F.personalDocumentInput($('path-search').value)) {
      $('path-search').value = ''; announce('Busca por CPF indisponível. Pesquise pelo nome.');
    }
    const q = F.normalize($('path-search').value);
    if (!index || !q) { $('path-options').textContent = ''; $('path-search').setAttribute('aria-expanded', 'false'); return; }
    const found = F.searchEntities(index, {q}, {limit: 9}).items.filter(node => node.id !== state.selected).slice(0, 8);
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
      const requested = state.selected;
      state.selected = F.resolveSelection(index, requested);
      if (requested && !state.selected) announce('A entidade do link não está disponível nesta base. Abrimos a visão geral.');
      if (!state.selected) state.depth = 1;
      for (const [id, values] of [['party', new Set(data.candidates.map(row => row.party).filter(Boolean))], ['connection-type', new Set(data.transfers.map(row => row.type || 'Categoria não informada'))]]) {
        const select = $(id); Array.from(values).sort((a, b) => a.localeCompare(b, 'pt-BR')).forEach(value => { const option = document.createElement('option'); option.value = value; option.textContent = value; select.appendChild(option); });
      }
      for (const [key, id] of Object.entries(FIELD_IDS)) if (['office', 'party', 'kind', 'type', 'direction'].includes(key) && state[key] && !Array.from($(id).options).some(option => option.value === state[key])) state[key] = '';
      fillFilters();
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
      render(); syncURL();
    }, 140);
  });
  $('reset-filters').addEventListener('click', () => { if (!index) return; syncURL(); state = F.fromQuery(''); candidatePage = 0; tablePage = 0; detailPage = 0; selectedEdge = null; fillFilters(); $('path-search').value = ''; $('path-options').textContent = ''; $('path-result').textContent = ''; filterValues(); render(); fitGraph(); syncURL(true); });
  $('overview-button').addEventListener('click', () => goGeneral());
  $('navigation-back').addEventListener('click', () => { if (navigationAt > 0) history.back(); });
  $('navigation-forward').addEventListener('click', () => { if (navigationAt < navigation.length - 1) history.forward(); });
  $('navigation-trail').addEventListener('click', event => {
    const button = event.target.closest('[data-navigation]'); if (!button) return;
    const at = navigation.findIndex(entry => entry.key === Number(button.dataset.navigation));
    if (at >= 0 && at !== navigationAt) history.go(at - navigationAt);
  });
  $('candidate-list').addEventListener('click', event => { const button = event.target.closest('[data-candidate]'); if (button) selectNode(button.dataset.candidate, {candidate: true, restoreCandidateFocus: event.detail === 0}); });
  $('candidate-prev').addEventListener('click', () => { candidatePage = Math.max(0, candidatePage - 1); renderCandidates(); $('candidate-list').scrollTop = 0; });
  $('candidate-next').addEventListener('click', () => { candidatePage += 1; renderCandidates(); $('candidate-list').scrollTop = 0; });
  $('table-prev').addEventListener('click', () => { tablePage = Math.max(0, tablePage - 1); renderTable(); });
  $('table-next').addEventListener('click', () => { tablePage += 1; renderTable(); });
  $('table-view-button').addEventListener('click', () => { state.view = 'table'; renderView(); syncURL(); });
  $('graph-view-button').addEventListener('click', () => { state.view = 'graph'; renderView(); syncURL(); });
  $('filters-toggle').addEventListener('click', () => { const open = $('filters-panel').classList.toggle('is-open'); $('filters-toggle').setAttribute('aria-expanded', String(open)); if (open) $('search').focus({preventScroll: true}); });
  $('expand-neighbors').addEventListener('click', () => { state.depth = state.depth === 3 ? 1 : state.depth + 1; selectedEdge = null; tablePage = 0; render(); syncURL(); });
  $('clear-selection').addEventListener('click', () => { if (selectedEdge) { selectedEdge = null; renderDetail(); highlightSelection(); } else goGeneral(); });
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
  $('search').addEventListener('keydown', event => {
    if (event.key === 'ArrowDown') { event.preventDefault(); $('candidate-list').querySelector('button')?.focus(); }
    if (event.key === 'Enter' && index) { event.preventDefault(); const result = F.searchEntities(index, state); if (result.total === 1) selectNode(result.items[0].id, {candidate: true}); else { $('candidate-list').querySelector('button')?.focus(); announce('Escolha explicitamente uma das identidades encontradas.'); } }
  });
  $('candidate-list').addEventListener('keydown', event => {
    const buttons = [...$('candidate-list').querySelectorAll('button')], at = buttons.indexOf(document.activeElement);
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); buttons[(at + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length]?.focus(); }
    if (event.key === 'Escape') $('search').focus();
  });
  $('zoom-in').addEventListener('click', () => zoom(1.2)); $('zoom-out').addEventListener('click', () => zoom(1 / 1.2));
  $('fit-graph').addEventListener('click', () => { fitGraph(); rememberCamera(); });
  $('center-selection').addEventListener('click', () => { centerSelection(); rememberCamera(); });
  $('reset-zoom').addEventListener('click', () => { transform = {scale: 1, x: 0, y: 0}; applyTransform(); rememberCamera(); });
  $('export-graph').addEventListener('click', exportSVG);
  $('graph').addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') { const target = event.target.closest('[data-node],[data-edge]'); if (!target) return; event.preventDefault(); if (target.dataset.node) selectNode(target.dataset.node, {focusDetail: true}); else selectEdge(target.dataset.edge); }
    else if (event.key === 'Escape') { event.preventDefault(); hoveredID = ''; hideTooltip(); goGeneral(); }
    else if (event.target === $('graph')) {
      if (['+', '=', '-'].includes(event.key)) { event.preventDefault(); zoom(event.key === '-' ? 1 / 1.2 : 1.2); }
      if (event.key === 'Home') { event.preventDefault(); fitGraph(); rememberCamera(); }
      if (event.key.startsWith('Arrow')) { event.preventDefault(); transform.x += event.key === 'ArrowLeft' ? 30 : event.key === 'ArrowRight' ? -30 : 0; transform.y += event.key === 'ArrowUp' ? 30 : event.key === 'ArrowDown' ? -30 : 0; applyTransform(); rememberCamera(); }
    }
  });
  $('graph').addEventListener('click', event => { if (event.detail !== 0 && performance.now() < suppressClickUntil) return; const target = event.target.closest('[data-node],[data-edge]'); if (target?.dataset.node) selectNode(target.dataset.node); else if (target?.dataset.edge) selectEdge(target.dataset.edge); else if (state.selected || selectedEdge) goGeneral(); });
  $('graph').addEventListener('wheel', event => {
    if (!event.ctrlKey && !event.metaKey) return; event.preventDefault();
    const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? $('graph').clientHeight : 1);
    zoom(Math.exp(-Math.max(-500, Math.min(500, delta)) * .0015), svgPoint(event.clientX, event.clientY));
  }, {passive: false});
  $('graph').addEventListener('focusin', event => hoverNode(event.target.closest('[data-node]')));
  $('graph').addEventListener('focusout', () => { hoveredID = ''; hideTooltip(); highlightSelection(); });
  $('graph').addEventListener('pointerleave', () => { if (!gesture) { hoveredID = ''; hideTooltip(); highlightSelection(); } });
  function startGesture(moved = false) {
    const points = [...activePointers.values()]; if (!points.length) { gesture = null; return; }
    gesture = {camera: {...transform}, points, moved};
    if (points.length > 1) gesture.moved = true;
  }
  $('graph').addEventListener('pointerdown', event => {
    if (event.button > 0 || !index) return;
    activePointers.set(event.pointerId, svgPoint(event.clientX, event.clientY)); startGesture(gesture?.moved || false);
  });
  $('graph').addEventListener('pointermove', event => {
    if (!activePointers.has(event.pointerId) || !gesture) { if (event.pointerType !== 'touch') hoverNode(event.target.closest('[data-node]'), event); return; }
    activePointers.set(event.pointerId, svgPoint(event.clientX, event.clientY));
    const points = [...activePointers.values()], original = gesture.points;
    if (points.length > 1 && original.length > 1) {
      const mid = list => ({x: (list[0].x + list[1].x) / 2, y: (list[0].y + list[1].y) / 2});
      const distance = list => Math.hypot(list[0].x - list[1].x, list[0].y - list[1].y);
      const a = mid(original), b = mid(points), camera = F.zoomAt(gesture.camera, distance(points) / Math.max(1, distance(original)), a);
      transform = {...camera, x: camera.x + b.x - a.x, y: camera.y + b.y - a.y}; gesture.moved = true;
    } else {
      const dx = points[0].x - original[0].x, dy = points[0].y - original[0].y;
      const matrix = $('graph').getScreenCTM(), screenUnit = matrix ? Math.hypot(matrix.a, matrix.b) : 1;
      if (Math.hypot(dx, dy) * screenUnit > 5) gesture.moved = true;
      if (!gesture.moved) return;
      transform = {...gesture.camera, x: gesture.camera.x + dx, y: gesture.camera.y + dy};
    }
    $('graph').setPointerCapture(event.pointerId); $('graph').classList.add('is-panning');
    hoveredID = ''; hideTooltip(); requestCamera();
  });
  const finishPan = event => {
    if (!activePointers.has(event.pointerId)) return;
    const moved = gesture?.moved; activePointers.delete(event.pointerId);
    if (moved) { suppressClickUntil = performance.now() + 350; applyTransform(); rememberCamera(); }
    if ($('graph').hasPointerCapture(event.pointerId)) $('graph').releasePointerCapture(event.pointerId);
    $('graph').classList.remove('is-panning'); startGesture(moved); highlightSelection();
  };
  // End even a short press released outside the SVG, before capture starts.
  window.addEventListener('pointerup', finishPan); window.addEventListener('pointercancel', finishPan);
  $('share-button').addEventListener('click', async () => { syncURL(); try { await navigator.clipboard.writeText(location.href); announce('Link copiado com os filtros e a entidade selecionada.'); } catch (_) { announce('Selecione e copie o endereço do navegador para compartilhar os filtros.'); } });
  $('notice').addEventListener('click', event => { if (event.target.closest('#retry-load')) load(); });
  window.addEventListener('popstate', event => {
    clearTimeout(cameraTimer); state = F.fromQuery(location.search); selectedEdge = null; tablePage = 0; detailPage = 0;
    if (index) state.selected = F.resolveSelection(index, state.selected);
    const entry = event.state?.raiox, at = navigation.findIndex(item => item.key === entry?.key);
    if (at >= 0) navigationAt = at;
    else { navigation = [{key: ++navigationKey, selected: state.selected, query: F.toQuery(state)}]; navigationAt = 0; }
    if (entry?.camera) transform = {...entry.camera};
    if (entry?.positions) positioned = new Map(entry.positions);
    fillFilters(); $('path-search').value = ''; $('path-options').textContent = ''; $('path-result').textContent = '';
    render(); syncURL();
  });
  window.addEventListener('resize', () => { if (index) { drawGraph(); highlightSelection(); } });
  // Strip unsupported/document-shaped URL parameters before data or navigation
  // is recorded. Legacy official candidate SQ is resolved internally after load.
  syncURL(); fillFilters(); load();
})();
