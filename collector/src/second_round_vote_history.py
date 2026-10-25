"""Factual national vote observations from verified, completed publications only."""
from datetime import datetime
import math
import re

from .election_release import canonical, digest, parse
from .second_round_publish import load, save


def build_history(state):
    from .second_round_runner import verify_proof
    checkpoint = load(state / 'checkpoint.json') or {}
    if not checkpoint.get('snapshot_id'): return None
    path = state / 'vote-history.json'
    cached = load(path)
    if cached and (cached.get('schema_version') != 1 or cached.get('round') != 2
                   or cached.get('environment') != 'oficial' or cached.get('scope') != 'br'
                   or cached.get('office') != 1):
        raise ValueError('invalid_vote_history_cache')
    points = {point['snapshot_id']: point for point in (cached or {}).get('points', [])}
    candidates = {row['id']: row for row in (cached or {}).get('candidates', [])}
    election_code = (cached or {}).get('election_code')
    receipts = []
    for receipt_path in (state / 'receipts').glob('*.json'):
        sid = receipt_path.stem
        if not re.fullmatch('[a-f0-9]{64}', sid): continue
        receipt = load(receipt_path) or {}
        if receipt.get('status') != 'published' or receipt.get('snapshot_id') != sid or receipt.get('round') != 2:
            continue
        stamp = receipt.get('verified_at')
        if not isinstance(stamp, str) or datetime.fromisoformat(stamp).tzinfo is None:
            raise ValueError('invalid_vote_history_publication_time')
        receipts.append((stamp, sid, receipt))
    for stamp, sid, receipt in sorted(receipts):
        if sid in points and 'percentages' in points[sid]: continue
        package = state / 'cycles' / sid[:32] / 'package'
        if not package.is_dir(): continue  # Previously verified cached observations remain durable.
        if verify_proof(package)['snapshot_id'] != sid:
            raise ValueError('vote_history_source_proof_mismatch')
        result = parse((package / 'br/president.json').read_bytes())
        if result['election']['round'] != 2 or result['scope']['code'] != 'br' or result['office']['code'] != 1:
            raise ValueError('vote_history_result_identity')
        if result['snapshot']['sections']['totalized'] == 0: continue
        if election_code is not None and result['election']['code'] != election_code:
            raise ValueError('vote_history_election_mismatch')
        election_code = result['election']['code']
        votes, percentages = {}, {}
        for candidate in result['candidates']:
            identity = str(candidate['tse_candidate_seq'])
            count = candidate['votes']
            if not re.fullmatch('[0-9]{1,20}', identity) or type(count) is not int or count < 0:
                raise ValueError('vote_history_invalid_count')
            percentage = candidate['vote_percentage']
            if (type(percentage) not in (int, float) or not math.isfinite(percentage)
                    or not 0 <= percentage <= 100):
                raise ValueError('vote_history_invalid_percentage')
            candidates[identity] = {'id': identity, 'name': candidate['ballot_name'] or candidate['name'],
                                    'number': candidate['ballot_number']}
            votes[identity] = count
            percentages[identity] = percentage
        points[sid] = {'snapshot_id': sid, 'at': stamp,
                       'source_at': result['snapshot']['generated_at'], 'votes': votes,
                       'percentages': percentages}
    if not points: return None
    ordered = sorted(points.values(), key=lambda point: datetime.fromisoformat(point['at']))
    if len(ordered) > 4096: raise ValueError('vote_history_observation_limit')
    result = {'schema_version': 1, 'environment': 'oficial', 'round': 2, 'scope': 'br',
              'office': 1, 'election_code': election_code,
              'candidates': list(candidates.values()), 'points': ordered}
    raw = canonical(result)
    if len(raw) > 2 * 1024 * 1024: raise ValueError('vote_history_size_limit')
    result['generation'] = digest(raw)
    if result != cached: save(path, result)
    return result
