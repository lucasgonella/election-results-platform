"""Verified baseline reconciliation retains the failed candidate and all votes."""
from pathlib import Path

import pytest

from collector.src import static_election_publish as pub
from collector.src import static_election_runner as runner
from collector.src.election_release import canonical, digest, parse, targets, tree
from test_static_election_publish import release
from test_static_election_runner import checkpoint


@pytest.fixture
def interrupted(release, tmp_path, monkeypatch):
    t, before, after, _, http = release
    root = tmp_path/'state'
    desc = pub.descriptor(before)
    sid = digest(canonical(desc))
    previous = root/'generations'/sid
    candidate = root/'cycles'/'interrupted'/'package'
    for package, values in [(previous, before), (candidate, after)]:
        for name, raw in values.items():
            path = package/'candidate'/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        checkpoint(package/'checkpoint', values)
    current = {'snapshot_id': sid, 'descriptor': desc, 'package': str(previous), 'published_at': '2026-10-09T13:00:00+00:00'}
    runner.save(root/'current.json', current)
    runner.save(root/'in-flight.json', {'package': str(candidate), 'selected': ['pi/state-deputy.json'], 'prepared_at': '2026-10-09T14:00:00+00:00'})
    runner.save(root/'health.json', {'status': 'failed', 'error_type': 'ValueError', 'error_code': 'interrupted_job_requires_reconciliation', 'collected_at': '2026-10-09T12:00:00+00:00'})
    t.ftp.files[t.site+'/version.json'] = canonical(parse(before['version.json']) | {'snapshot_id': sid})
    for name, raw in before.items():
        t.ftp.files[t.site+'/releases/'+sid+'/'+name] = raw
    t.ftp.files[t.private+'/current.json'] = canonical(current)
    t.ftp.files[t.private+'/pending.json'] = canonical({'status': 'complete', 'snapshot_id': sid})
    t.ftp.files[t.private+'/watermarks.json'] = canonical({n: parse(before[n]) for n in targets()})
    monkeypatch.setattr(pub, 'http_read', lambda environment, path: http(path))
    return root, t, candidate, current


@pytest.mark.parametrize('remote_status', ['complete', 'restored'])
def test_settled_baseline_reconciles_without_publishing_or_changing_checkpoint(interrupted, remote_status):
    root, t, candidate, current = interrupted
    t.ftp.files[t.private+'/pending.json'] = canonical({'status': remote_status, 'snapshot_id': current['snapshot_id']})
    original = tree(root)
    remote = dict(t.ftp.files)
    result = runner.reconcile_job(root, writer_stopped=True, transport=t)
    assert result['outcome'] == 'baseline_preserved' and result['files'] == 140
    assert parse((root/'current.json').read_bytes()) == current
    assert tree(candidate) == {n.removeprefix('cycles/interrupted/package/'): v for n, v in original.items() if n.startswith('cycles/interrupted/package/')}
    job = parse((root/'in-flight.json').read_bytes())
    assert job['status'] == 'complete' and job['package'] == str(candidate)
    assert job['selected'] == ['pi/state-deputy.json']
    history = next((root/'reconciliations').glob('*.json'))
    assert parse(history.read_bytes())['resolution'] == job
    health = parse((root/'health.json').read_bytes())
    assert health['collected_at'] == '2026-10-09T12:00:00+00:00'
    assert 'error_type' not in health
    assert t.ftp.files == remote and not t.ftp.events
    assert runner.reconcile_job(root, transport=t)['status'] == 'already_reconciled'
    # A new job can occupy in-flight without erasing the completed evidence.
    runner.save(root/'in-flight.json', {'package': 'new-cycle'})
    assert parse(history.read_bytes())['resolution'] == job


def test_new_failure_does_not_inherit_stale_error_code(interrupted, monkeypatch, capsys):
    import sys
    root, _, _, _ = interrupted
    runner.save(root/'in-flight.json', {'status': 'complete', 'snapshot_id': '0'*64})
    monkeypatch.setattr(runner, 'root_path', lambda: root)
    monkeypatch.setattr(runner, 'require_official_runtime', lambda: None)
    def fail(*args): raise RuntimeError('uncontrolled response with private information')
    monkeypatch.setattr(runner, 'run_cycle', fail)
    monkeypatch.setattr(sys, 'argv', ['runner', 'cycle'])
    assert runner.main() == 1
    health = parse((root/'health.json').read_bytes())
    assert health['error_type'] == 'RuntimeError' and 'error_code' not in health
    assert 'private information' not in capsys.readouterr().out


def test_history_conflict_preserves_all_local_state(interrupted):
    root, t, candidate, _ = interrupted
    sid = digest(canonical(pub.descriptor(tree(candidate/'candidate'))))
    folder = root/'reconciliations'
    folder.mkdir()
    runner.save(folder/(sid+'.json'), {'job': {'package': 'different'}, 'resolution': {}})
    original = tree(root)
    with pytest.raises(ValueError, match='reconciliation_history_conflict'):
        runner.reconcile_job(root, writer_stopped=True, transport=t)
    assert tree(root) == original and not t.ftp.events


@pytest.mark.parametrize('fault', ['live_lock', 'writer_running', 'pending_prepared', 'wrong_pending', 'external_marker', 'corrupt_ftp', 'corrupt_https', 'watermarks', 'changed_marker', 'changed_current'])
def test_uncertain_baseline_keeps_job_checkpoint_and_candidate(interrupted, monkeypatch, fault):
    root, t, candidate, current = interrupted
    writer_stopped = True
    if fault == 'live_lock': t.ftp.dirs.add(t.private+'/lock')
    elif fault == 'writer_running': writer_stopped = False
    elif fault in {'pending_prepared', 'wrong_pending'}:
        t.ftp.files[t.private+'/pending.json'] = canonical({'status': 'prepared' if fault == 'pending_prepared' else 'complete', 'snapshot_id': '0'*64})
    elif fault == 'external_marker': t.ftp.files[t.site+'/version.json'] = canonical({'snapshot_id': '0'*64})
    elif fault == 'corrupt_ftp': t.ftp.files[t.site+'/releases/'+current['snapshot_id']+'/pi/state-deputy.json'] = b'{}'
    elif fault == 'corrupt_https': monkeypatch.setattr(pub, 'http_read', lambda *args: b'{}')
    elif fault == 'watermarks': t.ftp.files[t.private+'/watermarks.json'] = b'{}'
    elif fault in {'changed_marker', 'changed_current'}:
        original_verify = runner.verify_public
        def changed(*args, **kwargs):
            result = original_verify(*args, **kwargs)
            path = t.site+'/version.json' if fault == 'changed_marker' else t.private+'/current.json'
            t.ftp.files[path] = b'{}'
            return result
        monkeypatch.setattr(runner, 'verify_public', changed)
    original = tree(root)
    with pytest.raises((ValueError, RuntimeError, KeyError)):
        runner.reconcile_job(root, writer_stopped=writer_stopped, transport=t)
    assert tree(root) == original
    assert not t.ftp.events


def test_already_published_candidate_reconciles_matching_checkpoint(interrupted):
    root, t, candidate, current = interrupted
    values = tree(candidate/'candidate')
    desc = pub.descriptor(values)
    sid = digest(canonical(desc))
    t.ftp.files[t.site+'/version.json'] = canonical(parse(values['version.json']) | {'snapshot_id': sid})
    t.ftp.files[t.private+'/current.json'] = canonical({'snapshot_id': sid, 'descriptor': desc, 'published_at': '2026-10-09T14:00:00+00:00'})
    for name, raw in values.items(): t.ftp.files[t.site+'/releases/'+sid+'/'+name] = raw
    result = runner.reconcile_job(root, transport=t)
    assert result['outcome'] == 'published'
    assert parse((root/'current.json').read_bytes())['snapshot_id'] == sid
    assert not t.ftp.events
