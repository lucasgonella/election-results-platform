"""Synthetic frontend releases and workflow invariants; no hosting or TSE calls."""
import json
from pathlib import Path

import pytest

from deploy import finance_preflight as p
from deploy import frontend as f
from tools import goias_finance_etl as etl
import test_frontend_deploy as existing


@pytest.fixture
def active():
    case = existing.FrontendTest('test_allowlist_and_immutable_references')
    case.setUp()
    case.publish(component='raio-x')
    case.ftp.events.clear()
    yield case
    case.doCleanups()


def check(case, **kwargs):
    return p.verify_reader(case.transport, root=case.root, http=kwargs.get('http', case.http))


def test_compatible_published_content_passes_without_a_single_remote_write(active):
    files, dirs = dict(active.ftp.files), set(active.ftp.dirs)
    # There is no dependency on the checkout/bot commit matching release commit.
    result = check(active)
    assert result['status'] == 'compatible' and result['commit'] == 'a' * 40
    assert result['ftp_https_verified']
    assert active.ftp.files == files and active.ftp.dirs == dirs
    assert active.ftp.events == []


@pytest.mark.parametrize('reason', ['old_reader', 'missing_fingerprint', 'forged_fingerprint', 'no_manifest'])
def test_unpublished_or_unproven_compatible_reader_fails_closed(active, reason):
    path = f.state_path('raio-x')
    state = f.decode(active.ftp.files[path])
    if reason == 'old_reader':
        (active.root / f.target('raio-x')['source'] / 'app.js').write_text('console.log("new reader")')
    elif reason == 'missing_fingerprint':
        del state['manifest']['source_sha256']
    elif reason == 'forged_fingerprint':
        # A claimed current fingerprint must not authorize different asset bytes.
        state['manifest']['files']['app.js']['sha256'] = 'b' * 64
    else:
        del state['manifest']
    active.ftp.files[path] = f.encode(state)
    with pytest.raises(RuntimeError, match='(?:not_published|no_published)'):
        check(active)
    assert active.ftp.events == []


@pytest.mark.parametrize('component', ['portal', 'raio-x'])
@pytest.mark.parametrize('kind', ['lock', 'prepared', 'unknown', 'empty_pending'])
def test_pending_or_lock_of_either_component_prevents_publication(active, component, kind):
    base = f.PRIVATE + '/' + component
    if kind == 'lock':
        active.ftp.dirs.add(base + '/lock')
    else:
        active.ftp.files[base + '/pending.json'] = f.encode({} if kind == 'empty_pending' else {'status': kind})
    with pytest.raises(RuntimeError, match='requires_recovery'):
        check(active)
    assert active.ftp.events == []


@pytest.mark.parametrize('file', ['app.js', 'styles.css', 'index.html', 'stable', 'directory_index'])
def test_public_assets_entrypoint_and_directory_index_must_match_hashes(active, file):
    root = f.target('raio-x')['url']
    bad_url = (root if file == 'directory_index' else root + 'index.html' if file == 'stable'
               else root + 'frontend-releases/' + 'a' * 40 + '/' + file)
    def http(url):
        return b'corrupt public bytes' if url == bad_url else active.http(url)
    with pytest.raises(RuntimeError, match='checksum_mismatch'):
        check(active, http=http)
    assert active.ftp.events == []


@pytest.mark.parametrize('mutation', ['state', 'portal_lock', 'raiox_pending'])
def test_change_during_verification_cannot_authorize_financial_publication(active, mutation):
    changed = False
    def http(url):
        nonlocal changed
        if not changed:
            changed = True
            if mutation == 'state':
                path = f.state_path('raio-x')
                state = f.decode(active.ftp.files[path]); state['previous_commit'] = 'c' * 40
                active.ftp.files[path] = f.encode(state)
            elif mutation == 'portal_lock':
                active.ftp.dirs.add(f.PRIVATE + '/portal/lock')
            else:
                active.ftp.files[f.PRIVATE + '/raio-x/pending.json'] = f.encode({'status': 'prepared'})
        return active.http(url)
    with pytest.raises(RuntimeError, match='(?:changed_during_preflight|requires_recovery)'):
        check(active, http=http)
    assert active.ftp.events == []


def test_rollback_to_a_previous_reader_is_blocked(active):
    source = active.root / f.target('raio-x')['source'] / 'app.js'
    source.write_text('console.log("compatible current reader")')
    package = active.root / 'compatible'
    manifest = f.build('raio-x', 'b' * 40, package, root=active.root, validate=False)
    files = {name: (package / 'files' / name).read_bytes() for name in manifest['files']}
    with active.transport.lock('raio-x'):
        f.activate(active.transport, manifest, files, 'new-reader', http=active.http)
    assert check(active)['commit'] == 'b' * 40
    with active.transport.lock('raio-x'):
        f.rollback(active.transport, 'raio-x', 'a' * 40, 'rollback-reader', http=active.http)
    active.ftp.events.clear()
    with pytest.raises(RuntimeError, match='not_published'):
        check(active)
    assert active.ftp.events == []


def test_cli_failure_is_sanitized_and_never_dispatches_or_waits(monkeypatch, capsys):
    def fail():
        raise RuntimeError('server response containing secret-test-value')
    monkeypatch.setattr(p, 'verify_live_reader', fail)
    assert p.main() == 1
    report = capsys.readouterr().out
    assert 'secret-test-value' not in report
    assert json.loads(report) == {'status': 'blocked', 'error_type': 'RuntimeError'}


def test_finance_job_cannot_publish_outside_visual_exclusion_or_before_gates():
    workflows = Path(__file__).resolve().parents[1] / '.github/workflows'
    workflow = (workflows / 'goias-finance-data.yml').read_text()
    top, job = workflow.split('jobs:\n', 1)
    assert 'group: goias-finance-etl' in top
    assert "cron: '23 9,15,21 * * *'" in top and 'workflow_dispatch:' in top
    assert "if: github.ref == 'refs/heads/main'" in job
    assert 'ref: ${{ github.sha }}' in job and 'ref: main' not in job
    assert 'group: locaweb-frontend-production' in job
    assert 'queue: max' in job and 'cancel-in-progress: false' in job
    assert 'group: locaweb-frontend-production' in (workflows / 'deploy-frontend-ftp.yml').read_text()
    gates = [i for i, line in enumerate(job.splitlines()) if 'run: python3 -m deploy.finance_preflight' in line]
    lines = job.splitlines()
    download = next(i for i, line in enumerate(lines) if '- name: Download official' in line)
    commit = next(i for i, line in enumerate(lines) if 'git push origin HEAD:main' in line)
    upload = next(i for i, line in enumerate(lines) if 'python3 -m tools.goias_finance_publish' in line)
    assert len(gates) == 2 and gates[0] < download < gates[1] < commit < upload
    assert job.count("LOCAWEB_FTP_PORT: '21'") == 3
    assert "FINANCE_PREFLIGHT_PROTOCOL: '1'" in job
    assert 'needs:' not in job and 'workflow_dispatch' not in job and 'gh workflow' not in job


@pytest.mark.parametrize('protocol', [None, '', '0', '2'])
def test_legacy_actions_definition_cannot_generate_or_commit_new_data(tmp_path, monkeypatch, protocol):
    output = tmp_path / 'data.json'
    output.write_text('previous data')
    monkeypatch.setattr('sys.argv', ['etl', '--candidates', 'c.zip', '--finance', 'f.zip', '--output', str(output)])
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.delenv('FINANCE_PREFLIGHT_PROTOCOL', raising=False)
    if protocol is not None:
        monkeypatch.setenv('FINANCE_PREFLIGHT_PROTOCOL', protocol)
    monkeypatch.setattr(etl, 'build', lambda *args: pytest.fail('must fail before processing'))
    with pytest.raises(RuntimeError, match='financial_preflight_protocol_required'):
        etl.main()
    assert output.read_text() == 'previous data' and not output.with_suffix('.new').exists()


@pytest.mark.parametrize('actions,protocol', [(None, None), ('true', '1')])
def test_local_etl_and_guarded_actions_keep_the_export_contract(tmp_path, monkeypatch, actions, protocol):
    output = tmp_path / 'data.json'
    monkeypatch.setattr('sys.argv', ['etl', '--candidates', 'c.zip', '--finance', 'f.zip', '--output', str(output)])
    for name, value in [('GITHUB_ACTIONS', actions), ('FINANCE_PREFLIGHT_PROTOCOL', protocol)]:
        monkeypatch.delenv(name, raising=False)
        if value is not None:
            monkeypatch.setenv(name, value)
    data = {'financial_schema': 1, 'candidates': [], 'transfers': []}
    monkeypatch.setattr(etl, 'build', lambda *args: data)
    etl.main()
    assert json.loads(output.read_bytes()) == data
