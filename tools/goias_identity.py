"""Deterministic official identity resolution; tax documents never leave memory.

Public IDs are UUIDs derived from candidacy/transaction anchors, never CPF hashes.
Campaign ownership is a separate fact from the personal identity of its owner.
"""
from collections import defaultdict
import re
import uuid

NAMESPACE = uuid.UUID('52919fbe-11c2-4cf9-a795-0ab5f98e0e4b')
CAND_SOURCE = 'https://dadosabertos.tse.jus.br/dataset/candidatos-2026'
FIN_SOURCE = 'https://dadosabertos.tse.jus.br/dataset/prestacao-de-contas-eleitorais-2026'


def document(value, length):
    value = str(value or '').strip()
    # Preserve leading zeroes; masking, arbitrary characters and partials fail closed.
    if not re.fullmatch(r'[0-9.\-/]+', value):
        return None
    digits = re.sub(r'[.\-/]', '', value)
    if len(digits) != length or len(set(digits)) == 1:
        return None
    a = list(map(int, digits))
    if length == 11:
        valid = all(((sum(a[i] * w for i, w in enumerate(range(n + 1, 1, -1))) * 10) % 11) % 10 == a[n] for n in (9, 10))
    else:
        def check(n, weights):
            rest = sum(a[i] * w for i, w in enumerate(weights)) % 11
            return a[n] == (0 if rest < 2 else 11 - rest)
        valid = check(12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]) and check(13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return digits if valid else None


def opaque(kind, anchor):
    return kind + ':' + str(uuid.uuid5(NAMESPACE, 'GO:2026:' + kind + ':' + anchor))


def resolve(candidates, private_candidates, records, campaign_owners):
    """Inputs are scoped official records. Return only allowlisted public facts."""
    cpf_candidates = defaultdict(set)
    candidate_conflicts = set()
    for cid, facts in private_candidates.items():
        cpfs = {v for raw in facts['cpfs'] if (v := document(raw, 11))}
        if len(cpfs) > 1:
            candidate_conflicts.add(cid)
        elif cpfs:
            cpf_candidates[next(iter(cpfs))].add(cid)
    # A single candidacy must never bridge contradictory documents.
    cpf_candidates = {cpf: ids for cpf, ids in cpf_candidates.items() if not ids & candidate_conflicts}
    person_for = {}
    for ids in cpf_candidates.values():
        pid = opaque('person', 'candidate:' + min(ids))
        for cid in ids:
            person_for[cid] = pid
    for cid in candidates:
        person_for.setdefault(cid, opaque('person', 'candidate:' + cid))

    entities = {}
    for cid, candidate in sorted(candidates.items()):
        pid = person_for[cid]
        candidate['person_id'] = pid
        candidate['civil_name'] = private_candidates[cid]['civil_name']
        candidate['ballot_name'] = candidate['name']
        candidate['uf'] = 'GO'
        candidate['source_url'] = CAND_SOURCE
        candidate['campaign_ids'] = []
        node = entities.setdefault(pid, {'id': pid, 'kind': 'person', 'name': candidate['name'],
            'civil_name': candidate['civil_name'], 'aliases': [], 'roles': ['candidate', 'beneficiary'],
            'candidate_ids': [], 'campaign_ids': [], 'evidence': []})
        node['candidate_ids'].append(cid)
        for name in [candidate['name'], candidate['civil_name']]:
            if name and name != node['name'] and name not in node['aliases']:
                node['aliases'].append(name)
        node['evidence'].append({'method': 'official_candidacy', 'candidate_id': cid, 'source_url': CAND_SOURCE})

    campaigns = {}
    campaign_conflicts = set()
    for cnpj, owners in sorted(campaign_owners.items()):
        if not document(cnpj, 14):
            continue
        if len(owners) != 1:
            campaign_conflicts.add(cnpj)
            continue
        cid = next(iter(owners))
        if cid not in candidates:
            continue
        campaign_id = opaque('campaign', 'candidate:' + cid + ':' + min(owners[cid]))
        campaign = {'id': campaign_id, 'kind': 'campaign', 'name': 'Campanha de ' + candidates[cid]['name'],
            'cnpj': cnpj, 'owner_person_id': person_for[cid], 'candidate_ids': [cid],
            'roles': ['campaign'], 'aliases': [], 'evidence': [{'method': 'official_campaign_ownership',
                'candidate_id': cid, 'fields': ['SQ_CANDIDATO', 'NR_CNPJ_PRESTADOR_CONTA'], 'source_url': FIN_SOURCE}]}
        campaigns[cnpj] = campaign
        entities[campaign_id] = campaign
        candidates[cid]['campaign_ids'].append(campaign_id)
        entities[person_for[cid]]['campaign_ids'].append(campaign_id)

    groups = defaultdict(list)
    for record in records:
        cpf = document(record['donor_document'], 11)
        cnpj = document(record['donor_document'], 14)
        key = ('cpf', cpf) if cpf else ('cnpj', cnpj) if cnpj else ('unresolved', record['id'])
        groups[key].append(record)
    confirmed_persons, confirmed_campaigns, unresolved = set(), set(), 0
    transfers = []
    conflicts = len(candidate_conflicts) + len(campaign_conflicts)
    conflict_records = 0
    for (kind, doc), donor_records in sorted(groups.items()):
        anchor = min(record['id'] for record in donor_records)
        ids = cpf_candidates.get(doc, set()) if kind == 'cpf' else set()
        campaign = campaigns.get(doc) if kind == 'cnpj' else None
        pid = person_for[min(ids)] if ids else None
        # The donor sequence is corroboration, never a substitute for full CPF/CNPJ.
        contradictory = any(r['donor_candidate_id'] in candidates and
            ((pid and person_for[r['donor_candidate_id']] != pid) or
             (campaign and r['donor_candidate_id'] not in campaign['candidate_ids'])) for r in donor_records)
        if contradictory:
            pid, campaign = None, None
            conflicts += 1
            conflict_records += len(donor_records)
        if pid:
            origin = entities[pid]
            confirmed_persons.add(pid)
            if 'donor' not in origin['roles']:
                origin['roles'].append('donor')
                origin['evidence'].append({'method': 'full_cpf_exact', 'candidate_ids': sorted(ids),
                    'fields': ['NR_CPF_CANDIDATO', 'NR_CPF_CNPJ_DOADOR'], 'source_url': FIN_SOURCE})
            status, method = 'confirmed', 'full_cpf_exact'
        elif campaign:
            origin = campaign
            confirmed_campaigns.add(campaign['owner_person_id'])
            if 'financier' not in origin['roles']:
                origin['roles'].append('financier')
            status, method = 'confirmed_campaign', 'campaign_cnpj_and_owner'
        else:
            origin = {'id': opaque('donor', 'transaction:' + anchor),
                'kind': 'person' if kind == 'cpf' else 'organization' if kind == 'cnpj' else 'unknown',
                'name': donor_records[0]['from_name'], 'aliases': [], 'roles': ['donor'],
                'candidate_ids': [], 'campaign_ids': [], 'evidence': []}
            entities[origin['id']] = origin
            status, method = ('conflict', 'conflicting_official_identifiers') if contradictory else ('unconfirmed', 'no_scoped_candidate_match')
            unresolved += 1
        for record in donor_records:
            name = record['from_name']
            if name and name != origin['name'] and name not in origin['aliases']:
                origin['aliases'].append(name)
            target_campaign = next((campaigns[cnpj] for cnpj, owners in campaign_owners.items()
                if record['candidate_id'] in owners and cnpj in campaigns), None)
            transfer = {k: record[k] for k in ['id', 'from_name', 'to_name', 'amount', 'date', 'type', 'source_url', 'source_record_id', 'source_file', 'source_row', 'candidate_id']}
            transfer.update({'from_id': origin['id'], 'to_id': person_for[record['candidate_id']],
                'from_role': 'campaign' if campaign else 'person' if kind == 'cpf' else origin['kind'],
                'to_role': 'campaign', 'to_campaign_id': target_campaign['id'] if target_campaign else None,
                'identity': {'status': status, 'method': method, 'donor_candidate_id': record['donor_candidate_id'],
                             'fields': ['NR_CPF_CANDIDATO', 'NR_CPF_CNPJ_DOADOR'] if pid else ['NR_CPF_CNPJ_DOADOR', 'NR_CNPJ_PRESTADOR_CONTA', 'SQ_CANDIDATO_DOADOR'] if campaign else [],
                             'source_url': FIN_SOURCE}})
            if campaign:
                transfer['from_campaign_id'] = campaign['id']
            transfers.append(transfer)
    transfers.sort(key=lambda row: row['id'])
    for transfer in transfers:
        origin = entities[transfer['from_id']]
        if origin['kind'] == 'campaign':
            person = entities[origin['owner_person_id']]
            if 'campaign_financier' not in person['roles']:
                person['roles'].append('campaign_financier')
    audit = {'candidate_records_examined': len(candidates), 'donor_records_examined': len(records),
        'donor_entities_examined': len(groups), 'personal_identities_confirmed': len(confirmed_persons),
        'candidates_also_personal_donors': sum(len(entities[pid]['candidate_ids']) for pid in confirmed_persons),
        'campaign_owners_confirmed': len(confirmed_campaigns),
        'candidates_with_financing_campaigns': sum(len(entities[pid]['candidate_ids']) for pid in confirmed_campaigns),
        'duplicate_person_nodes_eliminated': len(confirmed_persons),
        'campaign_nodes_projectable': len({t['from_id'] for t in transfers if t['from_role'] == 'campaign'}),
        'candidate_nodes_unified': len(candidates) - len(set(person_for.values())),
        'inconclusive_donor_entities': unresolved, 'identity_conflicts': conflicts, 'conflicting_donor_records': conflict_records,
        'masked_or_missing_document_records': sum(not document(r['donor_document'], 11) and not document(r['donor_document'], 14) for r in records)}
    public_entities = sorted(entities.values(), key=lambda e: e['id'])
    protected_cpfs = {cpf for facts in private_candidates.values() for raw in facts['cpfs'] if (cpf := document(raw, 11))}
    protected_cpfs.update(cpf for row in records if (cpf := document(row['donor_document'], 11)))
    assert_private_documents_absent([list(candidates.values()), public_entities, transfers, audit], protected_cpfs)
    return public_entities, transfers, audit


def assert_private_documents_absent(value, cpfs):
    """No personal document fields or complete CPF tokens in any public leaf."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {'cpf', 'document', 'donor_document', 'nr_cpf_candidato', 'nr_cpf_cnpj_doador'}:
                raise ValueError('Personal document field in public export')
            assert_private_documents_absent(item, cpfs)
    elif isinstance(value, list):
        for item in value:
            assert_private_documents_absent(item, cpfs)
    elif isinstance(value, str):
        tokens = re.findall(r'(?<![0-9])[0-9]{11}(?![0-9])', value)
        tokens += [re.sub(r'\D', '', token) for token in re.findall(r'(?<![0-9])[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}(?![0-9])', value)]
        if any(token in cpfs for token in tokens):
            raise ValueError('Personal document in public export')
