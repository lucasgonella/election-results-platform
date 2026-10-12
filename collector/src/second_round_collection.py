"""Official-only round two discovery, persistent HTTP cache and complete packages."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from .discovery import build_ea20_url, ElectionTarget
from .election_release import UFS, canonical, digest, parse
from .live_static import manifest_item, static_payload, validate_target
from .parser import parse_ea20
from .planner import build_ea14_url, ElectionCollectionPlan
from .runtime import build_config_url, select_supported_elections
from .second_round_discovery import SETTINGS, evaluate
from .tse_client import TseClient, TseFetchResult


class AwaitingData(Exception):
    pass


class RateLimited(Exception):
    def __init__(self, seconds):
        self.seconds = seconds


def official_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'resultados.tse.jus.br'
            or parsed.query or parsed.fragment or '..' in parsed.path.split('/')
            or not parsed.path.startswith('/oficial/')):
        raise ValueError('non_official_second_round_source')
    return url


class CachedClient(TseClient):
    """Independent round-two cache. No redirects and no automatic network retry."""
    def __init__(self, directory):
        super().__init__()
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.records = {}

    def fetch_json(self, url, **_):
        official_url(url)
        path = self.directory / (digest(url.encode()) + '.json')
        old = parse(path.read_bytes()) if path.exists() else None
        headers = {'If-None-Match': old['etag']} if old and old.get('etag') else {}
        response = self.session.get(url, headers=headers, timeout=self.timeout, allow_redirects=False)
        if response.status_code == 429:
            delay = response.headers.get('Retry-After', '300')
            try: seconds = int(delay)
            except ValueError: seconds = 300
            raise RateLimited(max(60, min(seconds, 3600)))
        if response.status_code in (404, 204):
            raise AwaitingData()
        if response.status_code == 304:
            if not old:
                raise ValueError('cache_without_payload')
            record = old
        else:
            response.raise_for_status()
            if response.status_code != 200 or len(response.content) > 16 * 1024 * 1024:
                raise ValueError('invalid_official_http_response')
            payload = parse(response.content.decode('utf-8-sig'))
            if not isinstance(payload, dict) or payload.get('f') != 'o':
                raise ValueError('invalid_official_payload')
            record = {'url': url, 'etag': response.headers.get('ETag'),
                      'sha256': digest(response.content), 'payload': payload}
            # Cache is an optimization; no publisher checkpoint is updated here.
            from .second_round_publish import save
            save(path, record)
        if record['url'] != url:
            raise ValueError('cache_identity_mismatch')
        self.records[url] = record
        return TseFetchResult(url, 200, record.get('etag'), None, record['sha256'], record['payload'])


def discover(client):
    config = client.fetch_json(build_config_url(SETTINGS)).payload
    if config.get('f') != 'o': raise ValueError('non_official_second_round_configuration')
    evaluate(config)
    elections = select_supported_elections(config, SETTINGS)
    plans = []
    for election in elections:
        ea14_url = build_ea14_url(settings=SETTINGS, election_code=election.election_code)
        ea14 = client.fetch_json(ea14_url).payload
        if (str(ea14.get('ele')) != str(election.election_code)
                or str(ea14.get('t')) != '2' or ea14.get('f') != 'o'
                or not isinstance(ea14.get('abr'), list) or not ea14['abr']):
            raise ValueError('invalid_second_round_ea14')
        scopes = {str(row.get('cdabr', '')).lower() for row in ea14['abr']
                  if row.get('tpabr') in {'uf', 'br'}}
        if not scopes <= set(UFS + ['br', 'zz']):
            raise ValueError('invalid_second_round_scope')
        raw_election = next(e for group in config['pl'] if group['c'] == 'ele2026'
                            for e in group['e'] if int(e['cd']) == election.election_code)
        targets = {}
        for coverage in raw_election['abr']:
            coverage_scope = str(coverage['cd']).lower()
            for office in coverage['cp']:
                code = int(office['cd'])
                if code not in (1, 3):
                    raise ValueError('second_round_unexpected_office')
                # Presidential national config expands only through its own EA14.
                selected = scopes if coverage_scope == 'br' and code == 1 else {coverage_scope}
                if code == 3 and coverage_scope == 'br':
                    selected = scopes - {'br', 'zz'}
                if not selected <= scopes or not selected:
                    raise ValueError('incomplete_second_round_ea14')
                for scope in sorted(selected):
                    if code == 3 and scope not in UFS:
                        raise ValueError('invalid_governor_scope')
                    key = (scope, code)
                    if key in targets:
                        raise ValueError('duplicate_second_round_target')
                    targets[key] = ElectionTarget(election.election_code, 'ele2026', 2,
                        scope, code, office.get('ds', ''), build_ea20_url(base_url=SETTINGS.base_url,
                        environment='oficial', cycle='ele2026', election_code=election.election_code,
                        scope_code=scope, office_code=code))
        plans.append(ElectionCollectionPlan(election.election_code, election.election_type, 'ele2026',
            ea14_url, str(ea14['idg']), tuple(targets.values())))
    targets = [t for p in plans for t in p.targets]
    if len({(t.scope_code, t.office_code) for t in targets}) != len(targets) or len(targets) > 56:
        raise ValueError('invalid_second_round_inventory')
    return tuple(plans)


def build_values(client, plans):
    values = {}
    started = False
    for plan in plans:
        for target in plan.targets:
            fetched = client.fetch_json(target.url)
            raw = fetched.payload
            if raw.get('f') != 'o':
                raise ValueError('non_official_second_round_result')
            parsed = parse_ea20(raw)
            validate_target(target, parsed)
            if not parsed.offices[0].candidates:
                raise AwaitingData()
            if parsed.generated_at is None:
                raise ValueError('missing_official_generation')
            # Source generation gives identical packages for identical data.
            payload = static_payload(parsed, environment='oficial', captured_at=parsed.generated_at)
            name = f'{target.scope_code}/' + ('president' if target.office_code == 1 else 'governor') + '.json'
            if name in values:
                raise ValueError('duplicate_second_round_result')
            values[name] = payload
            started |= bool(parsed.stats.sections_totalized and parsed.stats.sections_totalized > 0)
    if not values:
        raise AwaitingData()
    generation = max(v['snapshot']['generated_at'] for v in values.values())
    rows = [manifest_item(value, Path(name)) for name, value in sorted(values.items())]
    meta = {'schema_version': 1, 'environment': 'oficial', 'round': 2, 'generated_at': generation,
            'publication_phase': 'counting' if started else 'candidate_roster'}
    values['manifest.json'] = {**meta, 'result_count': len(rows),
        'candidate_count': sum(r['candidate_count'] for r in rows), 'results': rows}
    values['version.json'] = meta
    values['alerts.json'] = {**meta, 'alerts': [], 'alert_count': 0}
    return {name: canonical(value) for name, value in values.items()}


def collect(directory, client):
    plans = discover(client)
    values = build_values(client, plans)
    directory.mkdir(parents=True, exist_ok=False)
    for name, raw in values.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        import os
        with path.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    for path in sorted([directory, *[p for p in directory.rglob('*') if p.is_dir()]], reverse=True):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    return values
