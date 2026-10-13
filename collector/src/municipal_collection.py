"""Isolated official presidential municipality collection. No existing DB/state."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit

import requests

from .election_release import canonical, digest, parse
from .parser import parse_ea20
from .second_round_publish import save

UF_CODES = dict(zip('ro ac am rr pa ap to ma pi ce rn pb pe al se ba mg es rj sp pr sc rs ms mt go df'.split(),
                   '11 12 13 14 15 16 17 21 22 23 24 25 26 27 28 29 31 32 33 35 41 42 43 50 51 52 53'.split()))
CONFIG = 'https://resultados.tse.jus.br/oficial/comum/config/ele-c.json'


class Unavailable(RuntimeError):
    pass


class Throttled(RuntimeError):
    pass


def official(url):
    p = urlsplit(url)
    if p.scheme != 'https' or p.netloc != 'resultados.tse.jus.br' or not p.path.startswith('/oficial/') or p.query or p.fragment or '..' in p.path.split('/'):
        raise ValueError('municipal_non_official_source')
    return url


class HTTP:
    """Four bounded workers share a rate gate; cache is independent per round."""
    def __init__(self, directory, *, rate=4, session_factory=requests.Session, sleep=time.sleep, clock=time.monotonic):
        if not 0 < rate <= 10: raise ValueError('municipal_invalid_rate')
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.interval, self.next_request = 1 / rate, 0
        self.factory, self.sleep, self.clock = session_factory, sleep, clock
        self.local, self.lock = threading.local(), threading.Lock()
        self.stop = threading.Event()
        self.downloads = self.not_modified = self.reused = 0

    def cached(self, url):
        name = digest(official(url).encode())
        body, meta = self.directory / (name + '.json'), self.directory / (name + '.meta.json')
        if not body.exists() or not meta.exists(): return None
        info, raw = parse(meta.read_bytes()), body.read_bytes()
        if info.get('url') != url or info.get('sha256') != digest(raw):
            raise ValueError('municipal_cache_integrity')
        return info, parse(raw)

    def get(self, url, *, reuse=False):
        official(url)
        cached = self.cached(url)
        checked=(cached[0].get('checked_at') or datetime.fromisoformat(cached[0]['captured_at']).timestamp()) if cached else 0
        if reuse and cached and 0<=time.time()-checked<6*3600:
            self.reused += 1
            return cached
        if not hasattr(self.local, 'session'):
            self.local.session = self.factory()
        headers = {'Accept': 'application/json'}
        if cached:
            meta = cached[0]
            if meta.get('etag'): headers['If-None-Match'] = meta['etag']
            if meta.get('last_modified'): headers['If-Modified-Since'] = meta['last_modified']
        for attempt in range(3):
            if self.stop.is_set(): raise Unavailable('municipal_source_circuit_open')
            with self.lock:
                delay = max(0, self.next_request - self.clock())
                if delay: self.sleep(delay)
                self.next_request = self.clock() + self.interval
            if self.stop.is_set():raise Unavailable('municipal_source_circuit_open')
            try:
                response = self.local.session.get(url, headers=headers, timeout=(10, 30), allow_redirects=False)
                if response.status_code == 429:
                    self.stop.set()
                    try:delay=int(response.headers.get('Retry-After','600'))
                    except ValueError:delay=600
                    save(self.directory / 'cooldown.json', {'until': time.time() + max(600, min(3600,delay))})
                    raise Throttled('municipal_tse_rate_limited')
                if response.status_code in (404, 204):
                    # Do not scan thousands of unavailable URLs and trigger TSE blocking.
                    self.stop.set()
                    raise Unavailable('municipal_official_file_unavailable')
                if response.status_code == 304:
                    if not cached: raise ValueError('municipal_304_without_cache')
                    cached[0]['checked_at']=time.time()
                    save(self.directory/(digest(url.encode())+'.meta.json'),cached[0])
                    self.not_modified += 1
                    return cached
                if response.status_code >= 500: response.raise_for_status()
                if response.status_code != 200: raise ValueError('municipal_invalid_http_status')
                raw = response.content
                if len(raw) > 16 * 1024 * 1024: raise ValueError('municipal_file_too_large')
                payload = parse(raw.decode('utf-8-sig'))
                if not isinstance(payload, dict) or payload.get('f') != 'o': raise ValueError('municipal_invalid_official_payload')
                info = {'url': url, 'sha256': digest(raw), 'etag': response.headers.get('ETag'),
                        'last_modified': response.headers.get('Last-Modified'), 'captured_at': datetime.now(timezone.utc).isoformat(),'checked_at':time.time()}
                if cached and cached[0]['sha256']==info['sha256']:info['captured_at']=cached[0]['captured_at']
                name = digest(url.encode())
                path = self.directory / (name + '.json')
                temporary = path.with_suffix('.tmp')
                temporary.write_bytes(raw); temporary.replace(path)
                save(self.directory / (name + '.meta.json'), info)
                self.downloads += 1
                return info, payload
            except (requests.RequestException, OSError):
                if attempt == 2: raise
                self.sleep(2 ** attempt)
        raise RuntimeError('municipal_http_retry_exhausted')


def election(config, round_number):
    if config.get('f') != 'o' or round_number not in (1, 2): raise ValueError('municipal_invalid_configuration')
    matches = [(p, e) for p in config.get('pl', []) if p.get('c') == 'ele2026'
               for e in p.get('e', []) if str(e.get('t')) == str(round_number)
               and any(str(c.get('cd')) == '1' for a in e.get('abr', []) for c in a.get('cp', []))]
    if not matches: raise Unavailable('municipal_round_not_announced')
    if len(matches) != 1: raise ValueError('municipal_ambiguous_election')
    p, e = matches[0]
    if not re.fullmatch(r'\d{1,6}', str(e['cd'])): raise ValueError('municipal_invalid_election')
    return {'code': int(e['cd']), 'round': round_number, 'year': 2026, 'cycle': p['c'], 'pleito': p['cd']}


def source_url(config, selected, kind, uf, filename):
    matches = [r['dir'] for r in config.get('arq', []) if r.get('tp') == kind]
    if len(matches) != 1 or uf not in set(UF_CODES) | {'br', 'zz'}: raise ValueError('municipal_invalid_source_template')
    url = matches[0]
    for key, value in {'base': 'https://resultados.tse.jus.br', 'ambiente': 'oficial', 'ciclo': selected['cycle'], 'cd_eleicao': str(selected['code']), 'uf': uf}.items():
        url = url.replace('<' + key + '>', value)
    if '<' in url or '>' in url: raise ValueError('municipal_unresolved_source_template')
    return official(url + '/' + filename)


def inventory(payload, scopes=None):
    if payload.get('f') != 'o' or not isinstance(payload.get('abr'), list): raise ValueError('municipal_invalid_ea12')
    rows, seen_tse, seen_ibge, seen_ufs = [], set(), set(), set()
    for state in payload['abr']:
        uf = str(state.get('cd', '')).lower()
        if uf == 'zz': continue  # Exterior is explicitly excluded from territorial comparisons.
        if uf not in UF_CODES or uf in seen_ufs: raise ValueError('municipal_invalid_uf')
        seen_ufs.add(uf)
        if not isinstance(state.get('mu'), list) or not state['mu']: raise ValueError('municipal_empty_inventory')
        for m in state['mu']:
            tse, ibge = str(m.get('cd', '')), str(m.get('cdi', ''))
            if not re.fullmatch(r'\d{5}', tse) or not re.fullmatch(r'\d{7}', ibge) or not ibge.startswith(UF_CODES[uf]) or not str(m.get('nm', '')).strip():
                raise ValueError('municipal_invalid_official_codes')
            if tse in seen_tse or ibge in seen_ibge: raise ValueError('municipal_duplicate_codes')
            seen_tse.add(tse); seen_ibge.add(ibge)
            if scopes is None or uf in scopes: rows.append({'uf': uf, 'tse_code': tse, 'ibge_code': ibge, 'name': m['nm']})
    if seen_ufs != set(UF_CODES): raise ValueError('municipal_incomplete_national_inventory')
    return sorted(rows, key=lambda r: (r['uf'], r['tse_code']))


def result(raw, municipality, selected, info, roster=None):
    expected = municipality['tse_code'] if municipality else info['scope']
    if (raw.get('f') != 'o' or str(raw.get('ele')) != str(selected['code']) or str(raw.get('t')) != str(selected['round'])
            or raw.get('tpabr') != ('mu' if municipality else ('br' if expected == 'br' else 'uf')) or str(raw.get('cdabr')) != expected
            or raw.get('dv') != 's'):
        raise ValueError('municipal_result_identity_mismatch')
    parsed = parse_ea20(raw)
    if len(parsed.offices) != 1 or parsed.offices[0].code != 1: raise ValueError('municipal_wrong_office')
    stats = parsed.stats
    for value in [stats.sections_total, stats.sections_totalized, stats.candidate_valid_votes, stats.valid_votes, stats.votes_total]:
        if type(value) is not int or value < 0: raise ValueError('municipal_invalid_totals')
    if stats.sections_totalized > stats.sections_total: raise ValueError('municipal_invalid_sections')
    candidates = []
    for c in parsed.offices[0].candidates:
        cid = str(c.tse_candidate_seq)
        if type(c.votes) is not int or c.votes < 0 or roster is not None and cid not in roster:
            raise ValueError('municipal_invalid_candidate')
        if roster is not None and roster[cid].get('party') and roster[cid]['party']!=c.party_acronym:raise ValueError('municipal_candidate_party_mismatch')
        share = float(c.vote_percentage) if c.vote_percentage is not None else None
        if share is not None and not 0 <= share <= 100: raise ValueError('municipal_invalid_percentage')
        candidates.append({'id': cid, 'votes': c.votes, 'percentage': share, 'vote_destination': c.candidate_status})
    if not candidates: raise Unavailable('municipal_candidates_unavailable')
    eligible = sorted([c for c in candidates if c['vote_destination'] == 'Válido'], key=lambda c: (-c['votes'], c['id']))
    if not stats.sections_totalized and any(c['votes'] for c in candidates): raise ValueError('municipal_votes_without_sections')
    valid = stats.candidate_valid_votes
    consistent = sum(c['votes'] for c in eligible) == valid
    for c in eligible:
        if valid and c['percentage'] is not None and abs(c['percentage'] - c['votes'] / valid * 100) > .02:
            raise ValueError('municipal_percentage_denominator_mismatch')
    final = raw.get('tf') == 's' and stats.sections_total > 0 and stats.sections_totalized == stats.sections_total
    status = 'waiting' if not stats.sections_totalized else 'inconclusive' if not consistent or not valid else 'tie' if len(eligible) > 1 and eligible[0]['votes'] == eligible[1]['votes'] else 'final' if final else 'partial'
    leader, second = (eligible + [None, None])[:2]
    ties=[c for c in eligible if c['votes']==eligible[0]['votes']] if status=='tie' else []
    if status not in ('final', 'partial'):
        leader = None
        if status!='tie':second=None
    return {**(municipality or {'uf': expected, 'name': expected.upper()}), 'election': selected, 'office': 1,
            'status': status, 'consolidation': 'final' if final else 'partial',
            'sections': {'total': stats.sections_total, 'totalized': stats.sections_totalized, 'percentage': float(stats.sections_percentage) if stats.sections_percentage is not None else None},
            'electorate': {'totalized': stats.electorate_totalized, 'turnout': stats.turnout, 'abstentions': stats.abstentions},
            'valid_votes': valid, 'total_votes': stats.votes_total, 'candidates': candidates,
            'leader': leader, 'second': second, 'ties':ties, 'difference_votes': leader['votes'] - second['votes'] if leader and second else None,
            'difference_percentage_points': (leader['votes'] - second['votes']) / valid * 100 if leader and second and valid else None,
            'updated_at': parsed.generated_at.isoformat() if parsed.generated_at else None,
            'totalized_at': parsed.totalized_at.isoformat() if parsed.totalized_at else None,
            'captured_at': info['captured_at'], 'source_url': info['url'], 'source_sha256': info['sha256']}


def collect(client, round_number, scopes=None, progress=lambda _: None):
    cooldown = client.directory / 'cooldown.json'
    if cooldown.exists() and parse(cooldown.read_bytes())['until'] > time.time(): raise Throttled('municipal_tse_cooldown')
    config_info, config = client.get(CONFIG)
    selected = election(config, round_number)
    number = f"{selected['code']:06d}"
    ea14_url=source_url(config,selected,'ab','br',f'br-e{number}-ab.json')
    ea14_info,ea14=client.get(ea14_url)
    scopes_announced={str(row.get('cdabr','')).lower() for row in ea14.get('abr',[]) if row.get('tpabr')=='uf'}
    if ea14.get('f')!='o' or str(ea14.get('ele'))!=str(selected['code']) or str(ea14.get('t'))!=str(round_number) or not set(UF_CODES)<=scopes_announced:
        raise ValueError('municipal_invalid_ea14')
    mun_url = source_url(config, selected, 'cm', 'br', f'mun-e{number}-cm.json')
    mun_info, mun = client.get(mun_url)
    places = inventory(mun, scopes)
    expected_ufs = sorted({m['uf'] for m in places})
    national_url = source_url(config, selected, 'u', 'br', f'br-c0001-e{number}-u.json')
    ni, national = client.get(national_url)
    result(national, None, selected, {**ni, 'scope': 'br'})
    if round_number==2 and int(national.get('s',{}).get('st',0))==0: raise Unavailable('municipal_second_round_not_started')
    roster = {str(c.tse_candidate_seq): {'id': str(c.tse_candidate_seq), 'number': c.ballot_number, 'name': c.ballot_name or c.name, 'civil_name': c.name, 'party': c.party_acronym}
              for c in parse_ea20(national).offices[0].candidates}
    output, coverage, states = [], {}, {}
    for uf in expected_ufs:
        subset = [m for m in places if m['uf'] == uf]
        track_url = source_url(config, selected, 'ab', uf, f'{uf}-e{number}-ab.json')
        ti, tracking = client.get(track_url)
        if tracking.get('f') != 'o' or str(tracking.get('ele')) != str(selected['code']) or str(tracking.get('t')) != str(round_number): raise ValueError('municipal_invalid_ea15')
        tracks = {str(r['cdabr']): r for r in tracking.get('abr', []) if r.get('tpabr') in ('mun', 'mu')}
        municipal_rows = [r for r in tracking.get('abr', []) if r.get('tpabr') in ('mun', 'mu')]
        other_rows = [r for r in tracking.get('abr', []) if r.get('tpabr') not in ('mun', 'mu')]
        if len(tracks) != len(municipal_rows) or set(tracks) != {m['tse_code'] for m in subset} or any(r.get('tpabr') != 'uf' or r.get('cdabr') != uf for r in other_rows): raise ValueError('municipal_ea15_inventory_mismatch')
        checkpoint_path = client.directory / (uf + '-tracking.json')
        previous = parse(checkpoint_path.read_bytes()) if checkpoint_path.exists() else {}
        def one(m):
            url = source_url(config, selected, 'u', uf, f"{uf}{m['tse_code']}-c0001-e{number}-u.json")
            token = digest(canonical(tracks[m['tse_code']]))
            info, raw = client.get(url, reuse=previous.get(m['tse_code']) == token)
            try:parsed = result(raw, m, selected, info, roster)
            except ValueError:
                if previous.get(m['tse_code'])!=token:raise
                info,raw=client.get(url,reuse=False)
                parsed=result(raw,m,selected,info,roster)
            if parsed['sections']['totalized'] != int(tracks[m['tse_code']]['s']['st']):
                raise ValueError('municipal_ea15_ea20_not_synchronized')
            return parsed
        local = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = [pool.submit(one, m) for m in subset]
            try:
                for job in as_completed(jobs): local.append(job.result())
            except BaseException:
                client.stop.set()
                for job in jobs: job.cancel()
                raise
        # The CDN can publish EA15 and EA20 at different times. Do not activate
        # a package if the tracking snapshot moved during collection.
        _, after = client.get(track_url)
        if digest(canonical(after)) != digest(canonical(tracking)): raise ValueError('municipal_ea15_changed_during_collection')
        su = source_url(config, selected, 'u', uf, f'{uf}-c0001-e{number}-u.json')
        si, state_raw = client.get(su)
        state = result(state_raw, None, selected, {**si, 'scope': uf}, roster)
        totals = {c['id']: sum(next((m['votes'] for m in r['candidates'] if m['id'] == c['id']), 0) for r in local) for c in state['candidates']}
        equal = totals == {c['id']: c['votes'] for c in state['candidates']}
        all_final = state['consolidation'] == 'final' and all(r['consolidation'] == 'final' for r in local)
        if all_final and not equal:
            save(checkpoint_path,{})  # revalidate this UF's cached bodies on next attempt
            raise ValueError('municipal_final_uf_reconciliation_failed')
        report = {'expected': len(subset), 'processed': len(local), 'available': sum(r['status'] in ('partial','final','tie') for r in local),
                  'waiting': sum(r['status']=='waiting' for r in local), 'inconclusive': sum(r['status']=='inconclusive' for r in local), 'pending': 0, 'failed': 0,
                  'coverage_percentage': 100, 'reconciliation': 'equal' if equal else 'partial_cdn_timestamps_differ', 'all_final': all_final}
        coverage[uf], states[uf] = report, state
        output += sorted(local, key=lambda r: r['tse_code'])
        save(checkpoint_path, {code: digest(canonical(row)) for code,row in tracks.items()})
        progress({'uf': uf, **report, 'downloads': client.downloads, 'cached': client.reused, 'not_modified': client.not_modified})
    # Config/inventory changes invalidate the declared coverage as well.
    if digest(canonical(client.get(mun_url)[1])) != digest(canonical(mun)): raise ValueError('municipal_inventory_changed')
    return {'schema': 1, 'environment': 'oficial', 'election': selected, 'catalog': roster,
            'municipalities': output, 'states': states, 'coverage': coverage,
            'sources': {kind:{key:info[key] for key in ['url','sha256','captured_at']} for kind,info in [('ea11',config_info),('ea12',mun_info),('ea14',ea14_info)]}, 'exterior_included': False}


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--round', type=int, choices=[1,2], required=True)
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--uf', choices=sorted(UF_CODES))
    args = p.parse_args()
    data = collect(HTTP(args.cache / str(args.round)), args.round, {args.uf} if args.uf else None, lambda report: print(json.dumps(report), flush=True))
    save(args.output, data)
    print(json.dumps({'status': 'collected', 'municipalities': len(data['municipalities']), 'round':args.round}), flush=True)
