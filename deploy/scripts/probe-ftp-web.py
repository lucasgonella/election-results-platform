"""Client for the existing fixture PHP probe; never an election publisher.

Default: local plan only. Observe: authenticated fixture reads. Exercise requires
prior human approval of the fixed remote namespace and pins the expected FPM host.
No file content is sent over HTTPS, only the probe's existing action names.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from collector.src.ftp_safety import validate_credentials_file

NAMESPACE = '/home/storage/4/b7/e0/afgnet1/ftp-staging-pr75'
LIMIT = 16384


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('fixture_redirect_blocked')


class Client:
    def __init__(self, url, key, expected_host=None, opener=None):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or not parsed.path.endswith('/probe.php')
                or '%' in parsed.path or '\\' in parsed.path or '..' in parsed.path.split('/')):
            raise ValueError('invalid_fixture_url')
        if len(key) != 32:
            raise ValueError('invalid_fixture_key')
        self.url, self.key, self.expected_host = url, key, expected_host
        self.opener = opener or urllib.request.build_opener(NoRedirect())
        self.marker_url = urllib.parse.urlunsplit(parsed._replace(
            path=parsed.path.rsplit('/', 1)[0] + '/probe-marker.json'))

    def request(self, request, no_store=False):
        started = time.monotonic()
        try:
            response = self.opener.open(request, timeout=10)
        except urllib.error.HTTPError as error:
            if error.code != 409:
                raise ValueError('fixture_http_failed') from None
            response = error
        with response:
            raw = response.read(LIMIT + 1)
            headers = {name.lower(): value for name, value in response.headers.items()}
        if len(raw) > LIMIT:
            raise ValueError('fixture_response_too_large')
        if no_store and 'no-store' not in [s.strip().lower() for s in headers.get('cache-control', '').split(',')]:
            raise ValueError('fixture_control_cacheable')
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('invalid_fixture_response')
        return value, {'sha256': hashlib.sha256(raw).hexdigest(),
                       'elapsed_ms': round((time.monotonic() - started) * 1000, 2),
                       'cache': {name: headers[name] for name in
                                 ['cache-control', 'age', 'etag', 'last-modified'] if name in headers}}

    def post(self, action):
        if action not in {'runtime', 'read', 'lock', 'replace_a', 'replace_b'}:
            raise ValueError('invalid_fixture_action')
        raw = json.dumps({'action': action}, separators=(',', ':')).encode()
        stamp = str(int(time.time()))
        signature = hmac.new(self.key, stamp.encode() + b'\n' + raw, 'sha256').hexdigest()
        request = urllib.request.Request(self.url, data=raw, method='POST', headers={
            'Content-Type': 'application/json', 'Cache-Control': 'no-store',
            'X-Timestamp': stamp, 'X-Signature': signature})
        result, evidence = self.request(request, no_store=True)
        if 'error' in result:
            if action == 'lock' and result['error'] == 'publication_busy':
                return {'error': 'publication_busy'}, evidence
            raise ValueError('fixture_action_failed')
        if self.expected_host and result.get('host') != self.expected_host:
            raise ValueError('fixture_host_mismatch')
        allowed = {'host', 'pid', 'sapi', 'php', 'probe_version', 'flock', 'fsync', 'rename',
                   'effective_uid', 'effective_gid', 'fixture_root', 'process_root',
                   'opcache', 'validate_timestamps', 'revalidate_freq', 'marker', 'status'}
        return {name: result[name] for name in allowed if name in result}, evidence

    def public_marker(self, expected):
        evidence = {}
        for label, url, headers in [
            ('normal', self.marker_url, {}),
            ('cache_busted', self.marker_url + '?probe=' + secrets.token_hex(8), {'Cache-Control': 'no-cache'}),
        ]:
            value, evidence[label] = self.request(urllib.request.Request(url, headers=headers))
            if value != {'fixture': expected}:
                raise ValueError('fixture_marker_not_visible')
        return evidence

    def observe(self):
        runtime, control_cache = self.post('runtime')
        marker, marker_control = self.post('read')
        value = marker.get('marker')
        if value not in [{'fixture': 'replace_a'}, {'fixture': 'replace_b'}]:
            raise ValueError('unexpected_fixture_marker')
        public_cache = self.public_marker(value['fixture'])
        return {'runtime': runtime, 'marker': value, 'control_http': control_cache,
                'marker_control_http': marker_control, 'public_http': public_cache,
                'multi_host_validated': False, 'production_isolation': 'not_guaranteed'}

    def exercise(self, namespace=None):
        if namespace != NAMESPACE or not self.expected_host:
            raise ValueError('fixture_mutation_approval_required')
        initial = self.observe()
        if initial['runtime'].get('sapi') != 'fpm-fcgi':
            raise ValueError('php_fpm_required')
        original = initial['marker']['fixture']
        with ThreadPoolExecutor(max_workers=2) as executor:
            locks = list(executor.map(lambda _: self.post('lock')[0], range(2)))
        if (sum(v.get('status') == 'lock_acquired' for v in locks) != 1
                or sum(v.get('error') == 'publication_busy' for v in locks) != 1):
            raise ValueError('fixture_lock_exclusion_failed')
        observations = []
        try:
            for action in ['replace_b', 'replace_a']:
                self.post(action)
                marker, _ = self.post('read')
                if marker.get('marker') != {'fixture': action}:
                    raise ValueError('fixture_marker_not_visible')
                observations.append(self.public_marker(action))
        finally:
            # The original marker is a validated fixture A/B value, never arbitrary content.
            # This recovery write is included in the separately approved exercise scope.
            try:
                self.post(original)
                recovered, _ = self.post('read')
                if recovered.get('marker') != {'fixture': original}:
                    raise ValueError('fixture_recovery_required')
                self.public_marker(original)
            except Exception:
                raise ValueError('fixture_recovery_required') from None
        return {'status': 'fixture_exercise_completed', 'host': self.expected_host,
                'locks': locks, 'public_http': observations, 'marker_restored': original,
                'multi_host_validated': False, 'production_isolation': 'not_guaranteed'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', nargs='?', default='plan', choices=['plan', 'observe', 'exercise'])
    parser.add_argument('--url')
    parser.add_argument('--fixture-config', type=Path)
    parser.add_argument('--expected-host')
    parser.add_argument('--approved-namespace')
    args = parser.parse_args(argv)
    if args.operation == 'plan':
        print(json.dumps({'namespace': NAMESPACE, 'remote_writes_authorized': False,
                          'observe': ['runtime', 'read', 'GET fixture marker'],
                          'exercise': ['two locks', 'replace_b', 'replace_a', 'restore original marker'],
                          'multi_host_validated': False}))
        return
    if args.operation == 'exercise' and (args.approved_namespace != NAMESPACE or not args.expected_host):
        raise ValueError('fixture_mutation_approval_required')
    if not args.url or not args.fixture_config:
        raise ValueError('fixture_client_configuration_required')
    validate_credentials_file(args.fixture_config)
    config = json.loads(args.fixture_config.read_text(encoding='utf-8'))
    if config.get('fixture_only') is not True or config.get('environment') != 'fixture' or config.get('root') != NAMESPACE:
        raise ValueError('fixture_client_configuration_required')
    client = Client(args.url, bytes.fromhex(config['fixture_key']), args.expected_host)
    print(json.dumps(client.observe() if args.operation == 'observe' else client.exercise(args.approved_namespace)))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'failed', 'error_type': type(error).__name__}))
        raise SystemExit(1)
