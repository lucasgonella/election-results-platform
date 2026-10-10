"""HTTP probe client tests with fake responses: no network, keys or real files."""
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import threading
import urllib.request

import pytest

spec = importlib.util.spec_from_file_location(
    'web_probe', Path(__file__).resolve().parents[1] / 'deploy/scripts/probe-ftp-web.py')
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)
KEY = b'f' * 32
URL = 'https://fixture.invalid/probe.php'


class Response:
    headers = {'Cache-Control': 'no-store'}
    def __init__(self, value):
        self.raw = json.dumps(value).encode()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit): return self.raw[:limit]


class Opener:
    def __init__(self):
        self.marker = 'replace_a'
        self.requests = []
        self.lock_count = 0
        self.mutex = threading.Lock()
        self.sapi = 'fpm-fcgi'
        self.fail_read = False
    def open(self, request, timeout):
        with self.mutex:
            self.requests.append(request)
            if request.data is None:
                return Response({'fixture': self.marker})
            action = json.loads(request.data)['action']
            value = {'host': 'fixture-host', 'sapi': self.sapi, 'php': '8.4.0'}
            if action == 'lock':
                self.lock_count += 1
                return Response(dict(value, status='lock_acquired') if self.lock_count == 1
                                else {'error': 'publication_busy'})
            if action.startswith('replace_'):
                self.marker = action
                value['status'] = 'replaced'
            if action == 'read':
                if self.fail_read and self.marker == 'replace_b':
                    raise TimeoutError()
                value['marker'] = {'fixture': self.marker}
            return Response(value)


@pytest.mark.parametrize('url', ['http://fixture.invalid/probe.php',
    'https://user:password@fixture.invalid/probe.php', 'https://fixture.invalid/api/election-ftp-control.php',
    URL + '?redirect=1', 'https://fixture.invalid/../probe.php'])
def test_reject_unsafe_or_wrong_endpoint(url):
    with pytest.raises(ValueError, match='invalid_fixture_url'):
        web.Client(url, KEY)


def test_default_plan_never_loads_key_or_connects(monkeypatch, capsys):
    monkeypatch.setattr(web, 'validate_credentials_file', lambda _: pytest.fail('no key access'))
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *a: pytest.fail('no network'))
    web.main([])
    assert json.loads(capsys.readouterr().out)['remote_writes_authorized'] is False


def test_signature_is_compatible_and_observation_does_not_mutate():
    opener = Opener()
    result = web.Client(URL, KEY, 'fixture-host', opener).observe()
    assert result['multi_host_validated'] is False
    assert opener.marker == 'replace_a'
    for request in opener.requests:
        if request.data is not None:
            headers = {name.lower(): value for name, value in request.header_items()}
            signed = headers['x-timestamp'].encode() + b'\n' + request.data
            assert headers['x-signature'] == hmac.new(KEY, signed, 'sha256').hexdigest()
            assert json.loads(request.data)['action'] in {'runtime', 'read'}
        else:
            assert (request.full_url == 'https://fixture.invalid/probe-marker.json'
                    or request.full_url.startswith('https://fixture.invalid/probe-marker.json?probe='))


def test_redirect_cannot_replay_authenticated_request():
    with pytest.raises(ValueError, match='fixture_redirect_blocked'):
        web.NoRedirect().redirect_request(None, None, 307, '', {}, URL)


@pytest.mark.parametrize('host,namespace', [(None, web.NAMESPACE), ('fixture-host', None)])
def test_exercise_approval_precedes_requests(host, namespace):
    opener = Opener()
    with pytest.raises(ValueError, match='fixture_mutation_approval_required'):
        web.Client(URL, KEY, host, opener).exercise(namespace)
    assert opener.requests == []


def test_host_mismatch_prevents_mutations():
    opener = Opener()
    with pytest.raises(ValueError, match='fixture_host_mismatch'):
        web.Client(URL, KEY, 'wrong-host', opener).exercise(web.NAMESPACE)
    assert len(opener.requests) == 1


def test_cli_runtime_cannot_be_presented_as_fpm_validation():
    opener = Opener()
    opener.sapi = 'cli'
    with pytest.raises(ValueError, match='php_fpm_required'):
        web.Client(URL, KEY, 'fixture-host', opener).exercise(web.NAMESPACE)
    assert opener.lock_count == 0


def test_exercise_checks_lock_visibility_and_restores_original():
    opener = Opener()
    opener.marker = 'replace_b'
    result = web.Client(URL, KEY, 'fixture-host', opener).exercise(web.NAMESPACE)
    assert result['marker_restored'] == opener.marker == 'replace_b'
    assert result['multi_host_validated'] is False
    assert len(result['public_http']) == 2


def test_failure_after_replacement_recovers_original_marker():
    opener = Opener()
    opener.fail_read = True
    with pytest.raises(TimeoutError):
        web.Client(URL, KEY, 'fixture-host', opener).exercise(web.NAMESPACE)
    assert opener.marker == 'replace_a'


def test_cacheable_control_or_oversized_response_is_rejected():
    class Bad:
        def open(self, *a, **k):
            r = Response({})
            r.headers = {}
            return r
    with pytest.raises(ValueError, match='fixture_control_cacheable'):
        web.Client(URL, KEY, opener=Bad()).post('runtime')
    class Huge:
        def open(self, *a, **k):
            r = Response({})
            r.raw = b'x' * (web.LIMIT + 1)
            return r
    with pytest.raises(ValueError, match='fixture_response_too_large'):
        web.Client(URL, KEY, opener=Huge()).post('runtime')


def test_stale_normal_http_cache_is_detected_and_original_restored():
    class Cached(Opener):
        def open(self, request, timeout):
            if request.data is None and '?' not in request.full_url:
                return Response({'fixture': 'replace_a'})
            return super().open(request, timeout)
    opener = Cached()
    with pytest.raises(ValueError, match='fixture_marker_not_visible'):
        web.Client(URL, KEY, 'fixture-host', opener).exercise(web.NAMESPACE)
    assert opener.marker == 'replace_a'


def test_unexpected_response_fields_are_not_relayed_into_report():
    class Extra(Opener):
        def open(self, request, timeout):
            response = super().open(request, timeout)
            value = json.loads(response.raw)
            if request.data is not None:
                value['fixture_key'] = KEY.hex()
            return Response(value)
    result = web.Client(URL, KEY, 'fixture-host', Extra()).observe()
    assert KEY.hex() not in json.dumps(result)
