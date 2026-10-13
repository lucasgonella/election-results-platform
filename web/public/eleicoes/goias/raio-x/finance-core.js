/* Pure, dependency-free readers for the Goiás finance contract. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.AFGFinance = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const normalize = value => String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR').trim();
  const validAmount = value => typeof value === 'number' && Number.isFinite(value);
  const textID = value => typeof value === 'string' && value.trim().length > 0;
  // A public name search must never become a CPF lookup or serialize a CPF.
  // This deliberately rejects document-shaped input without validating/looking
  // up a personal document. Campaign CNPJs already in the public contract differ.
  function personalDocumentInput(value) {
    const text = String(value ?? '');
    return /(?:^|\D)\d{3}[.\s]\d{3}[.\s]\d{3}[-\s]\d{2}(?:\D|$)/.test(text) || /(?:^|\D)\d{11}(?:\D|$)/.test(text);
  }
  const safeSearch = value => personalDocumentInput(value) ? '' : String(value ?? '').slice(0, 160);
  const nameMatches = (text, query) => normalize(query).split(/\s+/).filter(Boolean).every(token => text.includes(token));
  const safeSource = value => {
    try {
      const url = new URL(value);
      return url.protocol === 'https:' && !url.username && !url.password && (!url.port || url.port === '443') && (url.hostname === 'tse.jus.br' || url.hostname.endsWith('.tse.jus.br')) ? url.href : null;
    } catch (_) { return null; }
  };
  function dateKey(value) {
    if (typeof value !== 'string') return null;
    const match = /^(\d{4})-(\d{2})-(\d{2})(?:T.*)?$/.exec(value) || /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value);
    if (!match) return null;
    const [year, month, day] = match[1].length === 4 ? match.slice(1, 4).map(Number) : [Number(match[3]), Number(match[2]), Number(match[1])];
    const date = new Date(Date.UTC(year, month - 1, day));
    return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day ? `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}` : null;
  }
  function validateData(data) {
    if (!data || data.scope !== 'GO' || data.year !== 2026 || !Array.isArray(data.candidates) || !Array.isArray(data.transfers)) throw new Error('Contrato incompatível: é necessária a base GO / 2026.');
    const candidates = new Set(), transfers = new Set();
    for (const candidate of data.candidates) {
      if (!candidate || !textID(candidate.id) || typeof candidate.name !== 'string' || !candidate.name.trim() || !['deputado federal', 'deputado estadual'].includes(candidate.office) || candidates.has(candidate.id)) throw new Error('Candidaturas inválidas ou identificadores repetidos na base.');
      for (const key of ['revenue', 'expenses', 'votes']) if (candidate[key] != null && (!validAmount(candidate[key]) || candidate[key] < 0)) throw new Error('Valor de candidatura incompatível com o contrato.');
      candidates.add(candidate.id);
    }
    for (const transfer of data.transfers) {
      if (!transfer || !textID(transfer.id) || !textID(transfer.from_id) || !textID(transfer.to_id) || transfers.has(transfer.id)) throw new Error('Transferências inválidas ou identificadores repetidos na base.');
      if (transfer.amount != null && (!validAmount(transfer.amount) || transfer.amount < 0)) throw new Error('Valor de transferência incompatível com o contrato.');
      transfers.add(transfer.id);
    }
    if (data.identity_schema != null) {
      if (data.identity_schema !== 1 || !Array.isArray(data.entities)) throw new Error('Contrato de identidade incompatível.');
      const entities = new Map();
      for (const entity of data.entities) {
        if (!entity || !textID(entity.id) || entities.has(entity.id) || !['person', 'campaign', 'organization', 'unknown'].includes(entity.kind) || !Array.isArray(entity.roles) || !Array.isArray(entity.aliases) || !Array.isArray(entity.candidate_ids)) throw new Error('Identidade inválida.');
        entities.set(entity.id, entity);
      }
      for (const candidate of data.candidates) if (!entities.has(candidate.person_id) || entities.get(candidate.person_id).kind !== 'person' || !entities.get(candidate.person_id).candidate_ids.includes(candidate.id)) throw new Error('Pessoa da candidatura ausente.');
      for (const entity of entities.values()) if (entity.kind === 'campaign' && (!entities.has(entity.owner_person_id) || entities.get(entity.owner_person_id).kind !== 'person')) throw new Error('Titularidade de campanha inválida.');
      for (const row of data.transfers) if (!entities.has(row.from_id) || !entities.has(row.to_id) || (row.from_campaign_id && row.from_campaign_id !== row.from_id) || (row.to_campaign_id && (!entities.has(row.to_campaign_id) || entities.get(row.to_campaign_id).owner_person_id !== row.to_id))) throw new Error('Identidade da transferência inválida.');
    }
    return data;
  }
  function sumKnown(rows, field = 'amount') {
    let total = 0, known = 0;
    for (const row of rows) if (validAmount(row[field])) { total += row[field]; known += 1; }
    return {total: known ? total : null, known, missing: rows.length - known, count: rows.length};
  }
  function buildIndex(data) {
    validateData(data);
    const nodes = new Map(), outgoing = new Map(), incoming = new Map(), aliases = new Map();
    const allEntities = new Map((data.entities || []).map(entity => [entity.id, entity]));
    if (data.identity_schema === 1) {
      const entities = allEntities, byPerson = new Map();
      for (const candidate of data.candidates) {
        if (!byPerson.has(candidate.person_id)) byPerson.set(candidate.person_id, []);
        byPerson.get(candidate.person_id).push(candidate);
      }
      for (const entity of data.entities) {
        if (entity.kind === 'campaign') { aliases.set(entity.id, entity.owner_person_id); continue; }
        const candidacies = byPerson.get(entity.id) || [];
        const roleKind = entity.roles.includes('candidate') ? entity.roles.includes('donor') ? 'candidate-donor' : entity.roles.includes('campaign_financier') ? 'candidate-campaign' : 'candidate' : entity.kind === 'person' ? 'donor' : entity.kind;
        const node = {...(candidacies[0] || {}), ...entity, aliases: [...entity.aliases], kind: roleKind, candidacies, campaigns: (entity.campaign_ids || []).map(id => entities.get(id)).filter(Boolean)};
        if (candidacies.length) for (const key of ['revenue', 'expenses', 'votes']) node[key] = sumKnown(candidacies, key).total;
        nodes.set(entity.id, node);
        for (const candidate of candidacies) aliases.set(candidate.id, entity.id);
      }
      // Display campaign transfers at the documented owner; retain actual legal
      // endpoints and roles on every record. This is a labelled projection.
      data = {...data, candidates: [...nodes.values()].filter(node => node.candidacies.length), transfers: data.transfers.map(row => ({...row, original_from_id: row.from_id, original_to_id: row.to_id, from_id: aliases.get(row.from_id) || row.from_id, to_id: aliases.get(row.to_id) || row.to_id}))};
    } else {
      for (const candidate of data.candidates) nodes.set(candidate.id, {...candidate, kind: 'candidate', aliases: [], roles: ['candidate']});
    }
    for (const transfer of data.transfers) {
      for (const side of ['from', 'to']) {
        const id = transfer[`${side}_id`];
        if (!nodes.has(id)) nodes.set(id, {id, name: transfer[`${side}_name`] || 'Contraparte sem nome informado', kind: 'counterparty', aliases: [], roles: []});
        const node = nodes.get(id), name = transfer[`${side}_name`];
        if (typeof name === 'string' && name.trim() && name !== node.name && !node.aliases.includes(name)) node.aliases.push(name);
      }
      if (!outgoing.has(transfer.from_id)) outgoing.set(transfer.from_id, []);
      if (!incoming.has(transfer.to_id)) incoming.set(transfer.to_id, []);
      outgoing.get(transfer.from_id).push(transfer);
      incoming.get(transfer.to_id).push(transfer);
    }
    const searchOrder = [...nodes.values()].sort((a, b) => a.name.localeCompare(b.name, 'pt-BR') || a.id.localeCompare(b.id));
    const searchText = new Map(searchOrder.map(node => [node.id, normalize([
      node.name, node.civil_name, ...node.aliases, node.party, node.number,
      ...(node.candidacies || []).flatMap(c => [c.ballot_name, c.civil_name, c.party, c.number]),
      ...(node.campaigns || []).flatMap(c => [c.name, ...c.aliases, c.cnpj, String(c.cnpj || '').replace(/\D/g, '')])
    ].join(' '))]));
    return {data, nodes, outgoing, incoming, aliases, entities: allEntities, searchOrder, searchText};
  }
  function matchesKind(node, kind) {
    return !kind || node.kind === kind || kind === 'candidate' && node.roles.includes('candidate') ||
      kind === 'multi' && node.roles.includes('candidate') && (node.roles.includes('donor') || node.roles.includes('campaign_financier'));
  }
  function searchEntities(index, filters = {}, options = {}) {
    const query = safeSearch(filters.q), tokens = normalize(query);
    // Document-shaped input must have zero results, rather than become an empty
    // query that accidentally returns/chooses the first identity.
    if (personalDocumentInput(filters.q)) return {items: [], total: 0, offset: 0};
    const candidates = new Set(filterCandidates(index, {...filters, q: ''}).map(c => c.id));
    const narrowed = !!(filters.office || filters.party);
    const hits = index.searchOrder.filter(node => {
      if (!matchesKind(node, filters.kind)) return false;
      if (narrowed && !candidates.has(node.id)) {
        const connected = [...(index.incoming.get(node.id) || []), ...(index.outgoing.get(node.id) || [])];
        if (!connected.some(row => candidates.has(row.from_id) || candidates.has(row.to_id))) return false;
      }
      const text = index.searchText.get(node.id);
      const campaignQuery = tokens.replace(/[.\/-]/g, '');
      return nameMatches(text, tokens) || /^\d{14}$/.test(campaignQuery) && text.includes(campaignQuery);
    });
    const limit = Math.min(50, Math.max(1, options.limit || 20));
    const offset = Math.min(Math.max(0, Number(options.offset) || 0), Math.max(0, Math.floor((hits.length - 1) / limit) * limit));
    return {items: hits.slice(offset, offset + limit), total: hits.length, offset};
  }
  function resolveSelection(index, requested) {
    const id = index.aliases.get(requested) || requested;
    return typeof id === 'string' && index.nodes.has(id) ? id : '';
  }
  function filterCandidates(index, filters = {}) {
    const q = normalize(filters.q);
    return index.data.candidates.filter(candidate => (candidate.candidacies || [candidate]).some(record => (!filters.office || record.office === filters.office) && (!filters.party || record.party === filters.party)) && (!q || normalize([candidate.name, candidate.civil_name, ...(candidate.aliases || []), candidate.party, candidate.number].join(' ')).includes(q)));
  }
  function filterTransfers(index, filters = {}, records = index.data.transfers) {
    if (['q', 'from', 'to'].some(key => personalDocumentInput(filters[key]))) return [];
    const candidateIDs = new Set(filterCandidates(index, {...filters, q: ''}).map(row => row.id));
    const narrowCandidates = !!(filters.office || filters.party);
    const q = normalize(filters.q), from = normalize(filters.from), to = normalize(filters.to);
    const hasMin = filters.min !== '' && filters.min != null && Number.isFinite(Number(filters.min));
    const hasMax = filters.max !== '' && filters.max != null && Number.isFinite(Number(filters.max));
    return records.filter(row => {
      const origin = index.nodes.get(row.from_id), target = index.nodes.get(row.to_id);
      if (narrowCandidates && !candidateIDs.has(row.from_id) && !candidateIDs.has(row.to_id)) return false;
      if (filters.kind && ![origin, target].some(node => node.kind === filters.kind || (filters.kind === 'candidate' && node.roles?.includes('candidate')) || (filters.kind === 'multi' && node.roles?.includes('candidate') && (node.roles.includes('donor') || node.roles.includes('campaign_financier'))))) return false;
      if (filters.direction && filters.selected) {
        if (filters.direction === 'incoming' && row.to_id !== filters.selected) return false;
        if (filters.direction === 'outgoing' && row.from_id !== filters.selected) return false;
        if (filters.direction === 'personal' && (row.from_id !== filters.selected || row.from_role !== 'person')) return false;
        if (filters.direction === 'campaign' && (row.from_id !== filters.selected || row.from_role !== 'campaign')) return false;
      }
      if (filters.type && (row.type || 'Categoria não informada') !== filters.type) return false;
      const campaignQuery = q.replace(/[.\/-]/g, '');
      const relationQuery = /^\d{14}$/.test(campaignQuery) ? campaignQuery : q;
      if (q && !nameMatches((index.searchText.get(origin.id) || '') + ' ' + (index.searchText.get(target.id) || ''), relationQuery)) return false;
      if (from && !nameMatches(index.searchText.get(origin.id) || '', from)) return false;
      if (to && !nameMatches(index.searchText.get(target.id) || '', to)) return false;
      if (hasMin && (!validAmount(row.amount) || row.amount < Number(filters.min))) return false;
      if (hasMax && (!validAmount(row.amount) || row.amount > Number(filters.max))) return false;
      const date = dateKey(row.date);
      if ((filters.start || filters.end) && !date) return false;
      if (filters.start && date < filters.start) return false;
      if (filters.end && date > filters.end) return false;
      return true;
    });
  }
  const EXPLICIT_FINANCE_FILTERS = ['office', 'party', 'kind', 'type', 'from', 'to', 'min', 'max', 'start', 'end', 'direction'];
  function explicitFinanceFilters(state = {}) {
    // q locates identities in the search list. It is NOT a financial filter and
    // must not restrict a donor to the candidate from whose graph she arrived.
    return Object.fromEntries(EXPLICIT_FINANCE_FILTERS.map(key => [key, state[key] ?? '']));
  }
  function getCompleteDirectConnections(index, requested, explicitFilters = {}) {
    const entityId = resolveSelection(index, requested);
    if (!entityId) return {entityId: '', records: [], available: 0, excludedByFilters: 0};
    // The sole source is the GLOBAL adjacency index, never graphData/contextRows
    // or a rendered node list. A self-transfer appears in both adjacency lists,
    // so deduplicate by original row ID, not amount, date, name or source SQ.
    const byID = new Map();
    for (const row of [...(index.incoming.get(entityId) || []), ...(index.outgoing.get(entityId) || [])]) byID.set(row.id, row);
    const complete = [...byID.values()].sort((a, b) => a.id.localeCompare(b.id));
    const records = filterTransfers(index, {...explicitFinanceFilters(explicitFilters), selected: entityId}, complete);
    return {entityId, records, available: complete.length, excludedByFilters: complete.length - records.length};
  }
  function getExplorationConnections(index, requested, explicitFilters = {}, depth = 1) {
    const direct = getCompleteDirectConnections(index, requested, explicitFilters);
    if (!direct.entityId || depth <= 1) return direct;
    const complete = filterTransfers(index, {...explicitFinanceFilters(explicitFilters), selected: direct.entityId});
    const neighborhoodIDs = neighborhood(complete, direct.entityId, depth).ids;
    const records = complete.filter(row => neighborhoodIDs.has(row.from_id) && neighborhoodIDs.has(row.to_id));
    return {...direct, records, directRecords: direct.records};
  }
  function aggregate(rows) {
    const groups = new Map();
    for (const row of rows) {
      const type = row.type || 'Categoria não informada';
      const id = JSON.stringify([row.from_id, row.to_id, type, row.from_role || '', row.to_role || '']);
      if (!groups.has(id)) groups.set(id, {id, from_id: row.from_id, to_id: row.to_id, type, rows: []});
      groups.get(id).rows.push(row);
    }
    const result = Array.from(groups.values()).map(group => ({...group, ...sumKnown(group.rows)}));
    const pairs = new Set(result.map(group => JSON.stringify([group.from_id, group.to_id])));
    return result.map(group => ({...group, reciprocal: group.from_id !== group.to_id && pairs.has(JSON.stringify([group.to_id, group.from_id]))}));
  }
  function neighborhood(rows, selected, depth = 1) {
    const adjacency = new Map();
    for (const row of rows) {
      if (!adjacency.has(row.from_id)) adjacency.set(row.from_id, new Set());
      if (!adjacency.has(row.to_id)) adjacency.set(row.to_id, new Set());
      adjacency.get(row.from_id).add(row.to_id); adjacency.get(row.to_id).add(row.from_id);
    }
    const seen = new Set(selected ? [selected] : []), distance = new Map(selected ? [[selected, 0]] : []);
    let frontier = selected ? [selected] : [];
    for (let hop = 1; hop <= Math.min(3, Math.max(1, depth)); hop++) {
      const next = [];
      for (const id of frontier) for (const other of adjacency.get(id) || []) if (!seen.has(other)) { seen.add(other); distance.set(other, hop); next.push(other); }
      frontier = next;
    }
    return {ids: seen, distance};
  }
  function graphView(index, rows, selected, depth = 1, limits = {}) {
    const maxNodes = Math.max(1, limits.nodes || 70), maxEdges = Math.max(1, limits.edges || 140);
    const local = neighborhood(rows, selected, depth);
    let groups = aggregate(rows).filter(group => !selected || (local.ids.has(group.from_id) && local.ids.has(group.to_id)));
    groups.sort((a, b) => (b.total ?? -1) - (a.total ?? -1) || a.id.localeCompare(b.id));
    const volume = new Map(), participating = new Set();
    for (const group of groups) for (const id of [group.from_id, group.to_id]) {
      participating.add(id);
      if (group.known > 0) volume.set(id, (volume.get(id) || 0) + group.total);
    }
    const ids = new Set(selected && index.nodes.has(selected) ? [selected] : []), chosen = [];
    for (const group of groups) {
      const missing = [group.from_id, group.to_id].filter(id => !ids.has(id));
      if (chosen.length >= maxEdges || ids.size + new Set(missing).size > maxNodes) continue;
      missing.forEach(id => ids.add(id)); chosen.push(group);
    }
    const nodes = Array.from(ids).map(id => ({...index.nodes.get(id), volume: volume.has(id) ? volume.get(id) : null, distance: local.distance.get(id) ?? 1}));
    return {nodes, edges: chosen, totalEdges: groups.length, hiddenEdges: groups.length - chosen.length, totalNodes: selected ? local.ids.size : participating.size, hiddenNodes: Math.max(0, (selected ? local.ids.size : participating.size) - nodes.length)};
  }
  /* Directed breadth-first search. Every hop is backed by an original row ID;
     it never joins entities by name or turns a path into a direct transfer. */
  function findPath(rows, fromID, toID, options = {}) {
    if (!fromID || !toID || fromID === toID) return {status: 'invalid', rows: [], visited: 0};
    const maxHops = Math.min(6, Math.max(1, options.maxHops || 4)), maxVisited = Math.max(1, options.maxVisited || 5000);
    const adjacency = new Map();
    for (const row of rows) { if (!adjacency.has(row.from_id)) adjacency.set(row.from_id, []); adjacency.get(row.from_id).push(row); }
    const queue = [fromID], parent = new Map(), depth = new Map([[fromID, 0]]);
    let cursor = 0;
    while (cursor < queue.length) {
      const current = queue[cursor++];
      if (depth.get(current) >= maxHops) continue;
      for (const row of adjacency.get(current) || []) {
        if (depth.has(row.to_id)) continue;
        if (depth.size >= maxVisited) return {status: 'limit', rows: [], visited: depth.size};
        depth.set(row.to_id, depth.get(current) + 1); parent.set(row.to_id, row); queue.push(row.to_id);
        if (row.to_id === toID) {
          const path = []; let id = toID;
          while (id !== fromID) { const step = parent.get(id); path.unshift(step); id = step.from_id; }
          return {status: 'found', rows: path, visited: depth.size};
        }
      }
    }
    return {status: 'missing', rows: [], visited: depth.size};
  }
  // Camera coordinates are SVG user units, after inverting the SVG's screen
  // CTM in the DOM reader. p = t + s*q; t' = p - (p-t)*(s'/s).
  function zoomAt(camera, factor, point, limits = {}) {
    const min = limits.min || .35, max = limits.max || 8;
    const scale = Math.min(max, Math.max(min, camera.scale * factor));
    const ratio = scale / camera.scale;
    return {scale, x: point.x - (point.x - camera.x) * ratio, y: point.y - (point.y - camera.y) * ratio};
  }
  function fitCamera(bounds, width = 900, height = 620, padding = 55) {
    if (!bounds || !Number.isFinite(bounds.x) || !bounds.width || !bounds.height) return {scale: 1, x: 0, y: 0};
    const scale = Math.min(2.5, Math.max(.35, Math.min((width - padding * 2) / bounds.width, (height - padding * 2) / bounds.height)));
    return {scale, x: width / 2 - (bounds.x + bounds.width / 2) * scale, y: height / 2 - (bounds.y + bounds.height / 2) * scale};
  }
  function centerCamera(camera, point, width = 900, height = 620) {
    return {...camera, x: width / 2 - point.x * camera.scale, y: height / 2 - point.y * camera.scale};
  }
  function layoutBounds(points, nodes, radius = 26) {
    if (!nodes.length) return null;
    const xs = nodes.map(node => points.get(node.id)?.x).filter(Number.isFinite);
    const ys = nodes.map(node => points.get(node.id)?.y).filter(Number.isFinite);
    if (!xs.length || !ys.length) return null;
    const x = Math.min(...xs) - radius, y = Math.min(...ys) - radius;
    return {x, y, width: Math.max(...xs) - x + radius, height: Math.max(...ys) - y + radius};
  }
  function stableLayout(nodes, edges, options = {}) {
    // Bounded deterministic force layout. Positions are visual geometry only:
    // financial identities and edges are neither grouped nor changed here.
    const sorted = [...nodes].sort((a, b) => a.id.localeCompare(b.id));
    const previous = options.previous || new Map(), positions = new Map(), velocity = new Map();
    const columns = Math.max(1, Math.ceil(Math.sqrt(sorted.length * 1.45))), rows = Math.ceil(sorted.length / columns);
    for (const [i, node] of sorted.entries()) {
      const cached = previous.get(node.id);
      positions.set(node.id, cached ? {...cached} : {x: 70 + (i % columns + .5) * 760 / columns, y: 60 + (Math.floor(i / columns) + .5) * 500 / Math.max(1, rows)});
      velocity.set(node.id, {x: 0, y: 0});
    }
    // Preserve the selected point in world coordinates while the new network
    // settles. The reader centers the camera explicitly after navigation.
    if (options.selected && positions.has(options.selected) && !previous.has(options.selected)) positions.set(options.selected, {x: 450, y: 310});
    const pinned = options.selected && positions.has(options.selected) ? options.selected : null;
    for (let step = 0; step < 100; step++) {
      const forces = new Map(sorted.map(node => [node.id, {x: 0, y: 0}]));
      for (let i = 0; i < sorted.length; i++) {
        for (let j = i + 1; j < sorted.length; j++) {
          const a = positions.get(sorted[i].id), b = positions.get(sorted[j].id);
          let dx = a.x - b.x, dy = a.y - b.y, length = Math.hypot(dx, dy);
          if (length < .001) { dx = .8; dy = .6; length = 1; }
          const minimum = (options.compact ? 38 : 27) + (options.radius?.(sorted[i]) || 18) + (options.radius?.(sorted[j]) || 18);
          const push = Math.min(14, 1550 / (length * length) + Math.max(0, minimum - length) * .25);
          const fx = dx / length * push, fy = dy / length * push;
          const fa = forces.get(sorted[i].id), fb = forces.get(sorted[j].id);
          fa.x += fx; fa.y += fy; fb.x -= fx; fb.y -= fy;
        }
      }
      for (const edge of edges) {
        const a = positions.get(edge.from_id), b = positions.get(edge.to_id);
        if (!a || !b || edge.from_id === edge.to_id) continue;
        const dx = b.x - a.x, dy = b.y - a.y, length = Math.max(1, Math.hypot(dx, dy));
        const pull = Math.max(0, length - 125) * .018;
        const fa = forces.get(edge.from_id), fb = forces.get(edge.to_id);
        fa.x += dx / length * pull; fa.y += dy / length * pull;
        fb.x -= dx / length * pull; fb.y -= dy / length * pull;
      }
      const cooling = 1 - step / 125;
      for (const node of sorted) {
        if (node.id === pinned) continue;
        const p = positions.get(node.id), f = forces.get(node.id), v = velocity.get(node.id);
        v.x = (v.x + f.x + (450 - p.x) * .003) * .62;
        v.y = (v.y + f.y + (310 - p.y) * .003) * .62;
        p.x = Math.min(855, Math.max(45, p.x + Math.max(-12, Math.min(12, v.x)) * cooling));
        p.y = Math.min(562, Math.max(58, p.y + Math.max(-12, Math.min(12, v.y)) * cooling));
      }
    }
    return positions;
  }
  const QUERY_FIELDS = ['q', 'office', 'party', 'kind', 'type', 'from', 'to', 'min', 'max', 'start', 'end', 'selected', 'view', 'depth', 'direction'];
  const opaqueEntityID = value => /^(?:person|donor|campaign|organization|unknown):[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(String(value));
  function toQuery(state) {
    const query = new URLSearchParams();
    for (const key of QUERY_FIELDS) if (state[key] != null && String(state[key]) !== '' && (key === 'selected' && opaqueEntityID(state[key]) || !personalDocumentInput(state[key])) && !(key === 'view' && state[key] === 'graph') && !(key === 'depth' && Number(state[key]) === 1)) query.set(key, String(state[key]));
    return query.toString();
  }
  function fromQuery(value) {
    const query = new URLSearchParams(value), state = {};
    for (const key of QUERY_FIELDS) state[key] = query.get(key) || '';
    for (const key of ['q', 'from', 'to', 'office', 'party', 'kind', 'type', 'direction']) state[key] = safeSearch(state[key]);
    state.view = state.view === 'table' ? 'table' : 'graph'; state.depth = ['2', '3'].includes(state.depth) ? Number(state.depth) : 1;
    for (const key of ['min', 'max']) if (state[key] && (!Number.isFinite(Number(state[key])) || Number(state[key]) < 0)) state[key] = '';
    for (const key of ['start', 'end']) if (state[key] && dateKey(state[key]) !== state[key]) state[key] = '';
    return state;
  }
  return {normalize, validAmount, safeSource, dateKey, personalDocumentInput, safeSearch, validateData, sumKnown, buildIndex, filterCandidates, searchEntities, resolveSelection, matchesKind, filterTransfers, explicitFinanceFilters, getCompleteDirectConnections, getExplorationConnections, aggregate, neighborhood, graphView, findPath, zoomAt, fitCamera, centerCamera, stableLayout, layoutBounds, toQuery, fromQuery};
});
