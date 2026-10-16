"""No network: an Actions owner must be proven finished before lock recovery."""
import importlib.util
from pathlib import Path
import pytest
from deploy import frontend as f
import test_frontend_deploy as existing

spec = importlib.util.spec_from_file_location('owned_recovery', Path(__file__).resolve().parents[1] / 'deploy/scripts/recover-frontend-owned-actions.py')
owned = importlib.util.module_from_spec(spec); spec.loader.exec_module(owned)


@pytest.fixture
def pending_case():
    case = existing.FrontendTest('test_allowlist_and_immutable_references'); case.setUp()
    case.publish(commit='a' * 40, transaction='actions-100-1')
    source = case.root / f.target('portal')['source']
    (source / 'app.js').write_text('console.log("changed fixture")')
    output = case.root / 'changed-package'
    manifest = f.build('portal', 'b' * 40, output, root=case.root, validate=False)
    contents = {name: (output / 'files' / name).read_bytes() for name in manifest['files']}
    store = case.ftp.storbinary
    def interrupted(command, stream):
        if '/frontend-releases/' + 'b' * 40 in command: raise KeyboardInterrupt()
        return store(command, stream)
    case.ftp.storbinary = interrupted
    try:
        with pytest.raises(KeyboardInterrupt):
            with case.transport.lock('portal'):
                f.activate(case.transport, manifest, contents, 'actions-123-1', http=case.http)
        case.ftp.storbinary = store
        yield case
    finally: case.doCleanups()


def finished():
    return {'id': 123, 'run_attempt': 1, 'status': 'completed', 'conclusion': 'failure',
        'head_sha': 'b' * 40, 'head_branch': 'main', 'repository': {'full_name': owned.REPO},
        'path': '.github/workflows/deploy-portal-ftp.yml'}


def test_abandoned_actions_journal_recovery_preserves_all_other_data(pending_case):
    case = pending_case
    protected = case.ftp.files['/public_html/data/version.json']
    result = owned.recover_owned(case.transport, owned.REPO, lambda *_: finished(), http=case.http)
    assert result[0]['status'] == 'recovered'
    assert '/frontend-deploy/portal/lock' not in case.ftp.dirs
    assert f.decode(case.transport.read(f.state_path('portal')))['commit'] == 'a' * 40
    assert case.ftp.files['/public_html/data/version.json'] == protected


@pytest.mark.parametrize('mutation', [{'status': 'in_progress'}, {'conclusion': 'success'},
    {'head_sha': 'c' * 40}, {'run_attempt': 2}, {'head_branch': 'other'},
    {'repository': {'full_name': 'someone/else'}}, {'path': '.github/workflows/untrusted.yml'}])
def test_live_foreign_or_unproven_owner_never_recovered(pending_case, mutation):
    case = pending_case; before = dict(case.ftp.files); value = {**finished(), **mutation}
    with pytest.raises(RuntimeError, match='not_verified_abandoned'):
        owned.recover_owned(case.transport, owned.REPO, lambda *_: value, http=case.http)
    assert '/frontend-deploy/portal/lock' in case.ftp.dirs
    assert case.ftp.files == before


def test_external_entrypoint_prevents_any_recovery_write(pending_case):
    case = pending_case
    case.ftp.files['/public_html/eleicoes/index.html'] = b'unrelated replacement'
    before = dict(case.ftp.files)
    with pytest.raises(RuntimeError, match='external_frontend_entrypoint'):
        owned.recover_owned(case.transport, owned.REPO, lambda *_: finished(), http=case.http)
    assert case.ftp.files == before


def test_long_absolute_rename_is_replaced_by_verified_basename(tmp_path):
    class LongPathFTP(existing.FakeFTP):
        arguments = []
        def rename(self, old, new):
            self.arguments.append((old, new, self.pwd()))
            if len(old) > 128: raise TimeoutError('isolated absolute path limit')
            return super().rename(old, new)
    ftp = LongPathFTP(); t = f.Transport(ftp)
    path = '/public_html/eleicoes/frontend-releases/' + 'b' * 40 + '/brazil-states.js'
    t.put(path, b'verified content')
    assert ftp.files[path] == b'verified content'
    assert len(ftp.arguments) == 1
    assert '/' not in ftp.arguments[0][0] and '/' not in ftp.arguments[0][1]
    assert ftp.pwd() == '/'
