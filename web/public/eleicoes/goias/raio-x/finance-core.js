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
    return data;
  }
  function sumKnown(rows, field = 'amount') {
    let total = 0, known = 0;
    for (const row of rows) if (validAmount(row[field])) { total += row[field]; known += 1; }
    return {total: known ? total : null, known, missing: rows.length - known, count: rows.length};
  }
  function buildIndex(data) {
    validateData(data);
    const nodes = new Map(), outgoing = new Map(), incoming = new Map();
    for (const candidate of data.candidates) nodes.set(candidate.id, {...candidate, kind: 'candidate', aliases: []});
    for (const transfer of data.transfers) {
      for (const side of ['from', 'to']) {
        const id = transfer[`${side}_id`];
        if (!nodes.has(id)) nodes.set(id, {id, name: transfer[`${side}_name`] || 'Contraparte sem nome informado', kind: 'counterparty', aliases: []});
        const node = nodes.get(id), name = transfer[`${side}_name`];
        if (typeof name === 'string' && name.trim() && name !== node.name && !node.aliases.includes(name)) node.aliases.push(name);
      }
      if (!outgoing.has(transfer.from_id)) outgoing.set(transfer.from_id, []);
      if (!incoming.has(transfer.to_id)) incoming.set(transfer.to_id, []);
      outgoing.get(transfer.from_id).push(transfer);
      incoming.get(transfer.to_id).push(transfer);
    }
    return {data, nodes, outgoing, incoming};
  }
  function filterCandidates(index, filters = {}) {
    const q = normalize(filters.q);
    return index.data.candidates.filter(candidate => (!filters.office || candidate.office === filters.office) && (!filters.party || candidate.party === filters.party) && (!q || normalize([candidate.name, candidate.party, candidate.number].join(' ')).includes(q)));
  }
  function filterTransfers(index, filters = {}) {
    const candidateIDs = new Set(filterCandidates(index, {...filters, q: ''}).map(row => row.id));
    const narrowCandidates = !!(filters.office || filters.party);
    const q = normalize(filters.q), from = normalize(filters.from), to = normalize(filters.to);
    const hasMin = filters.min !== '' && filters.min != null && Number.isFinite(Number(filters.min));
    const hasMax = filters.max !== '' && filters.max != null && Number.isFinite(Number(filters.max));
    return index.data.transfers.filter(row => {
      const origin = index.nodes.get(row.from_id), target = index.nodes.get(row.to_id);
      if (narrowCandidates && !candidateIDs.has(row.from_id) && !candidateIDs.has(row.to_id)) return false;
      if (filters.kind && origin.kind !== filters.kind && target.kind !== filters.kind) return false;
      if (filters.type && (row.type || 'Categoria não informada') !== filters.type) return false;
      if (q && !normalize([origin.name, target.name, origin.party, target.party, origin.number, target.number].join(' ')).includes(q)) return false;
      if (from && !normalize(origin.name).includes(from)) return false;
      if (to && !normalize(target.name).includes(to)) return false;
      if (hasMin && (!validAmount(row.amount) || row.amount < Number(filters.min))) return false;
      if (hasMax && (!validAmount(row.amount) || row.amount > Number(filters.max))) return false;
      const date = dateKey(row.date);
      if ((filters.start || filters.end) && !date) return false;
      if (filters.start && date < filters.start) return false;
      if (filters.end && date > filters.end) return false;
      return true;
    });
  }
  function aggregate(rows) {
    const groups = new Map();
    for (const row of rows) {
      const type = row.type || 'Categoria não informada';
      const id = JSON.stringify([row.from_id, row.to_id, type]);
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
    for (let hop = 1; hop <= Math.min(2, Math.max(1, depth)); hop++) {
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
  const QUERY_FIELDS = ['q', 'office', 'party', 'kind', 'type', 'from', 'to', 'min', 'max', 'start', 'end', 'selected', 'view', 'depth'];
  function toQuery(state) {
    const query = new URLSearchParams();
    for (const key of QUERY_FIELDS) if (state[key] != null && String(state[key]) !== '' && !(key === 'view' && state[key] === 'graph') && !(key === 'depth' && Number(state[key]) === 1)) query.set(key, String(state[key]));
    return query.toString();
  }
  function fromQuery(value) {
    const query = new URLSearchParams(value), state = {};
    for (const key of QUERY_FIELDS) state[key] = query.get(key) || '';
    state.view = state.view === 'table' ? 'table' : 'graph'; state.depth = state.depth === '2' ? 2 : 1;
    for (const key of ['min', 'max']) if (state[key] && (!Number.isFinite(Number(state[key])) || Number(state[key]) < 0)) state[key] = '';
    for (const key of ['start', 'end']) if (state[key] && dateKey(state[key]) !== state[key]) state[key] = '';
    return state;
  }
  return {normalize, validAmount, safeSource, dateKey, validateData, sumKnown, buildIndex, filterCandidates, filterTransfers, aggregate, neighborhood, graphView, findPath, toQuery, fromQuery};
});
