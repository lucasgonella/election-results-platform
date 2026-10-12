"""Offline monitoring regressions: no network, credentials or operational calls."""
from datetime import datetime, timedelta, timezone
import hashlib
import pytest

from collector.src.election_release import canonical
from collector.src.election_release import parse, tree
from collector.src.publication_health import assess, get_public, inspect, main, origin, write_report
from static_election_fixtures import bundle


@pytest.fixture
def public(tmp_path):
    root = tmp_path / 'release'
    bundle(root, 1)
    values = tree(root)
    marker = parse(values['version.json']) | {'snapshot_id': 'a' * 64}
    expected = {'snapshot_id': 'a' * 64, 'files': {
        name: {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
        for name, raw in values.items()}}
    def read(path):
        if path == 'version.json':
            return canonical(marker)
        return values[path.split('/', 2)[2]]
    now = datetime.fromisoformat(marker['generated_at']) + timedelta(seconds=10)
    return values, marker, expected, read, now


def test_full_inventory_and_137_identities_are_verified(public):
    values, marker, expected, read, now = public
    result = inspect('https://fixture.invalid', full=True, expected=expected, read=read, now=now)
    assert result['status'] == 'ok'
    assert result['files_verified'] == 140 and result['results_verified'] == 137
    assert result['checksums_match_reviewed_inventory'] is True
    assert result['last_successful_publication_at'] is None
    assert result['remote_writes'] is False and result['live_state_writes'] is False


def test_stale_publication_and_pending_are_alerts(public):
    values, marker, expected, read, now = public
    rj = parse(values['rj/governor.json'])
    pending = marker | {'generated_at': (now + timedelta(seconds=1)).isoformat()}
    result = assess(marker, rj, {'pending': pending}, now + timedelta(hours=1), 900)
    assert set(result['alerts']) == {'publication_generation_overdue',
                                    'prepared_generation_unpublished', 'collection_generation_overdue'}
    assert result['last_prepared_generation_at'] == pending['generated_at']


def test_old_tse_source_alone_is_not_publication_failure(public):
    values, marker, expected, read, now = public
    rj = parse(values['rj/governor.json'])
    rj['snapshot']['generated_at'] = '2026-01-01T00:00:00+00:00'
    result = assess(marker, rj, {'state': marker}, now, 900)
    assert result['status'] == 'ok'
    assert result['rj']['source_age_seconds'] > 900


@pytest.mark.parametrize('kind', ['hash', 'identity', 'missing', 'metadata', 'duplicate_json'])
def test_public_corruption_cannot_report_success(public, kind):
    values, marker, expected, read, now = public
    if kind == 'hash':
        values['rj/governor.json'] += b' '
    elif kind == 'identity':
        value = parse(values['am/governor.json']); value['election']['code'] = 2
        values['am/governor.json'] = canonical(value)
    elif kind == 'missing':
        del values['am/governor.json']
    elif kind == 'metadata':
        value = parse(values['alerts.json']); value['environment'] = 'wrong'
        values['alerts.json'] = canonical(value)
    else:
        values['manifest.json'] = b'{"results":[],"results":[]}'
    with pytest.raises((ValueError, KeyError)):
        inspect('https://fixture.invalid', full=True, expected=expected, read=read, now=now)


def test_changed_selection_during_reads_is_rejected(public):
    values, marker, expected, read, now = public
    calls = 0
    def changed(path):
        nonlocal calls
        if path == 'version.json':
            calls += 1
            if calls == 2:
                return canonical(marker | {'snapshot_id': 'b' * 64})
        return read(path)
    with pytest.raises(ValueError, match='public_selection_changed'):
        inspect('https://fixture.invalid', full=True, read=changed, now=now)


@pytest.mark.parametrize('url', ['http://example.com', 'https://user:secret@example.com',
                              'https://example.com/api', 'https://example.com/?key=secret'])
def test_only_credential_free_https_origin(url):
    with pytest.raises(ValueError, match='invalid_public_origin'):
        origin(url)


def test_future_and_local_mismatch(public):
    values, marker, expected, read, now = public
    rj = parse(values['rj/governor.json'])
    with pytest.raises(ValueError, match='future_public_generation'):
        assess(marker, rj, {}, now - timedelta(hours=1), 900)
    result = assess(marker, rj, {'state': marker | {'generated_at': '2026-10-08T12:00:00+00:00'}}, now, 900)
    assert result['alerts'] == ['local_public_generation_mismatch', 'collection_generation_overdue']


def test_pending_has_time_to_publish_before_alert(public):
    values, marker, expected, read, now = public
    pending = marker | {'generated_at': now.isoformat()}
    result = assess(marker, parse(values['rj/governor.json']), {'state': marker, 'pending': pending}, now, 900)
    assert result['status'] == 'ok'


def test_report_cannot_overwrite_live_state(tmp_path):
    live = tmp_path / 'live'; live.mkdir()
    protected = live / 'pending.json'; protected.write_bytes(b'original')
    with pytest.raises(ValueError, match='report_overlaps_live_state'):
        write_report(protected, {'status': 'alert'}, live)
    assert protected.read_bytes() == b'original'
    report = tmp_path / 'monitor.json'
    write_report(report, {'status': 'alert'}, live)
    assert parse(report.read_bytes()) == {'status': 'alert'}


def test_cli_failures_alert_without_logging_response_or_secret(monkeypatch, capsys):
    import collector.src.publication_health as health
    monkeypatch.setattr('sys.argv', ['health'])
    def failed(*args, **kwargs):
        raise ValueError('password=SHOULD_NEVER_APPEAR')
    monkeypatch.setattr(health, 'inspect', failed)
    assert main() == 2
    output = capsys.readouterr().out
    assert 'SHOULD_NEVER_APPEAR' not in output
    assert parse(output)['alerts'] == ['publication_verification_failed']


def test_http_response_on_another_origin_is_refused(monkeypatch):
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def geturl(self): return 'https://other.invalid/data/version.json'
    class Opener:
        def open(self, *args, **kwargs): return Response()
    monkeypatch.setattr('collector.src.publication_health.build_opener', lambda *args: Opener())
    with pytest.raises(ValueError, match='unexpected_public_response'):
        get_public('https://fixture.invalid', 'version.json')


def test_supplied_local_root_cannot_silently_lose_state(public, tmp_path):
    values, marker, expected, read, now = public
    with pytest.raises(ValueError, match='unsafe_live_root'):
        inspect('https://fixture.invalid', live_root=tmp_path/'missing', read=read, now=now)
    live = tmp_path/'live'; live.mkdir()
    with pytest.raises(ValueError, match='local_state_missing'):
        inspect('https://fixture.invalid', live_root=live, read=read, now=now)
