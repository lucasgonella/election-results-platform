"""Local filesystem fault trials. Never SSH to a real host in automated tests."""
import json
import os
from pathlib import Path
import secrets
import threading
from unittest.mock import patch

import pytest

from deploy import frontend as f, ssh_remote as remote
from deploy.ssh_transport import SSHError, SSHOperations, SSHSession, selection, transport
from collector.src import static_election_publish as first
from collector.src.election_release import canonical, digest, parse, targets, tree
from static_election_fixtures import bundle


class LocalSession(SSHSession):
    def __init__(self, scope, root):
        self.scope, self.root, self.checker = scope, root, None
        self.metrics = {'files_sent': 0, 'files_reused': 0}
        self.fail, self.corrupt, self.lost_commit = None, False, False

    def rpc(self, op, **args):
        if self.fail == op: raise SSHError('ssh_operation_outcome_unknown')
        result = remote.handle({'scope': self.scope, 'op': op, **args}, str(self.root))
        if op == 'commit' and self.lost_commit:
            self.lost_commit = False
            raise SSHError('ssh_operation_outcome_unknown')
        return result

    def upload(self, raw):
        name = self.rpc('reserve', nonce=secrets.token_hex(16))
        (self.root / name.lstrip('/')).write_bytes(raw + (b'bad' if self.corrupt else b''))
        self.metrics['files_sent'] += 1
        return name

    def upload_many(self, values): return {digest(raw):self.upload(raw) for raw in values}

    def close(self): pass


def local(policy, scope, root, *args):
    session = LocalSession(scope, root)
    value = type('LocalSSHTransport', (SSHOperations, policy), {})(session, *args, reconnect=None)
    session.checker = value
    return value


@pytest.fixture
def staging(tmp_path):
    (tmp_path / 'public_html').mkdir()
    (tmp_path / 'public_html/__election_static_staging').mkdir()
    return local(first.Transport, 'first-staging', tmp_path, 'staging')


def test_selection_explicit_no_fallback(monkeypatch):
    monkeypatch.delenv('PUBLICATION_TRANSPORT', raising=False)
    assert selection() == 'ftp'
    monkeypatch.setenv('PUBLICATION_TRANSPORT', 'ssh')
    with patch('deploy.ssh_transport.transport', side_effect=SSHError('ssh_failure')):
        with patch.object(first, 'election_ftp_connect') as ftp:
            with pytest.raises(SSHError): first.connect('production')
            ftp.assert_not_called()
    monkeypatch.setenv('PUBLICATION_TRANSPORT', 'automatic')
    with pytest.raises(ValueError): selection()


@pytest.mark.parametrize('failed_attempts',[1,2,3])
def test_only_readonly_ssh_hello_has_bounded_reconnection(failed_attempts):
    from unittest.mock import Mock
    sessions=[]
    for i in range(3):
        s=Mock();s.metrics={'ssh_failures':int(i<failed_attempts),'connections':1}
        if i<failed_attempts:
            failure=SSHError('ssh_operation_outcome_unknown');failure.transport_operation='hello'
            s.connect.side_effect=failure
        sessions.append(s)
    with patch('deploy.ssh_transport.SSHSession',side_effect=sessions) as factory, patch('time.sleep'), patch.object(f,'connect') as ftp:
        if failed_attempts==3:
            with pytest.raises(SSHError) as failure:transport(f.Transport,'portal')
            assert failure.value.connection_attempts==3
            assert factory.call_count==3
        else:
            t=transport(f.Transport,'portal')
            assert t.ftp is sessions[failed_attempts]
            assert t.ftp.metrics['connect_retries']==failed_attempts
            assert t.ftp.metrics['ssh_failures']==failed_attempts
        ftp.assert_not_called()
    assert all(s.shutdown.call_count==1 for s in sessions[:failed_attempts])


def test_ssh_home_failure_is_not_retried():
    from unittest.mock import Mock
    s=Mock();s.metrics={};s.connect.side_effect=SSHError('ssh_home_mismatch')
    with patch('deploy.ssh_transport.SSHSession',return_value=s) as factory:
        with pytest.raises(SSHError):transport(f.Transport,'portal')
        assert factory.call_count==1


def test_unknown_write_response_is_not_replayed_or_reconnected():
    import subprocess,sys,tempfile
    from unittest.mock import Mock
    s=SSHSession.__new__(SSHSession)
    s.scope,s.checker,s.metrics='benchmark',None,{'ssh_failures':0,'hash_failures':0}
    s.guard,s.buffer=threading.RLock(),bytearray()
    s.directory=tempfile.TemporaryDirectory()
    s.connect=Mock(side_effect=AssertionError('unknown write must not reconnect'))
    s.process=subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.readline();sys.exit(1)'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
    try:
        with pytest.raises(SSHError) as failure:s.rpc('commit',path='/election-ssh-benchmark/marker.json')
        assert failure.value.transport_operation=='commit'
        assert s.metrics['operations']['commit']==1
        s.connect.assert_not_called()
    finally:s.close();s.directory.cleanup()


@pytest.mark.parametrize('mode', [0o644, 0o660, 0o777])
def test_private_key_permissions_fail_closed(tmp_path, mode):
    key = tmp_path / 'key'; key.write_bytes(b'fixture'); key.chmod(mode)
    with pytest.raises(ValueError): SSHSession._file(str(key), private=True)


@pytest.mark.parametrize('file_uid,file_mode,parent_uid,parent_mode,managed', [
    (0,0o440,0,0o550,True),
    (0,0o440,0,0o577,False),
    (0,0o460,0,0o550,False),
    (999,0o440,0,0o550,False),
    (0,0o440,999,0o550,False),
])
def test_systemd_acl_mask_requires_root_managed_readonly_credentials(monkeypatch,file_uid,file_mode,parent_uid,parent_mode,managed):
    import stat
    from types import SimpleNamespace
    p=Path('/run/credentials/fixture.service/locaweb_ssh_key')
    def metadata(path):
        if path==p:return SimpleNamespace(st_mode=stat.S_IFREG|file_mode,st_uid=file_uid)
        return SimpleNamespace(st_mode=stat.S_IFDIR|parent_mode,st_uid=parent_uid)
    monkeypatch.setattr(Path,'lstat',metadata)
    monkeypatch.setattr(Path,'resolve',lambda path:path)
    if managed: assert SSHSession._file(str(p),private=True,credentials_directory=str(p.parent))==p
    else:
        with pytest.raises(ValueError):SSHSession._file(str(p),private=True,credentials_directory=str(p.parent))
    with pytest.raises(ValueError):SSHSession._file(str(p),private=True)


@pytest.mark.parametrize('name', ['/../secret', '/public_html/estudos/index.html',
    '/public_html/data/turnos/2/version.json', '/public_html//data/a', '/public_html/data/./a',
    '/public_html/data/a;id', '/public_html/data/a\n', 'relative'])
def test_namespace_rejects_traversal_other_turn_and_shell(staging, name):
    with pytest.raises(ValueError): staging.put(name, b'x')


def test_symlink_ancestor_is_rejected(staging, tmp_path):
    p = tmp_path / 'public_html/__election_static_staging/data'
    p.symlink_to(tmp_path / 'elsewhere')
    with pytest.raises(ValueError, match='symlink'): staging.metadata(staging.site + '/version.json')


def test_transfer_hash_failure_never_selects(staging):
    staging.ftp.corrupt = True
    with pytest.raises(ValueError, match='hash_mismatch'):
        staging.put(staging.site + '/version.json', b'candidate', replace=True)
    assert staging.read(staging.site + '/version.json', optional=True) is None


def test_idempotent_upload_and_immutable_collision(staging):
    path = staging.private + '/current.json'
    staging.put(path, b'one')
    staging.put(path, b'one')
    assert staging.ftp.metrics == {'files_sent': 1, 'files_reused': 1}
    with pytest.raises(ValueError, match='immutable'): staging.put(path, b'two')
    assert staging.read(path) == b'one'
    staging.put(path, b'two', replace=True)
    assert staging.read(path) == b'two'


def test_lock_is_exclusive_and_failed_operation_retains_lock(staging):
    with pytest.raises((SSHError, FileExistsError)):
        with staging.lock():
            with staging.lock(): pass
    assert staging.metadata(staging.private + '/lock')['type'] == 'dir'


def test_atomic_no_replace_preserves_existing_directory(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir(); b.mkdir(); (b / 'saved').write_bytes(b'original')
    with pytest.raises((OSError, ValueError)): remote.rename_exclusive(a, b)
    assert (b / 'saved').read_bytes() == b'original' and a.exists()


def test_external_writer_between_transfer_and_commit_is_not_overwritten(staging):
    path = staging.private + '/current.json'
    staging.put(path, b'old')
    real = staging.ftp.upload
    def raced(raw):
        result = real(raw)
        (staging.ftp.root / path.lstrip('/')).write_bytes(b'external')
        return result
    staging.ftp.upload = raced
    with pytest.raises(ValueError, match='external_writer'): staging.put(path, b'new', replace=True)
    assert staging.read(path) == b'external'


def test_ssh_options_and_rsync_command_have_no_unsafe_flags(tmp_path):
    key, known = tmp_path / 'key', tmp_path / 'known_hosts'
    key.touch(mode=0o600); known.touch(mode=0o600)
    with patch('deploy.ssh_transport.verify_known_hosts'):
        s = SSHSession('benchmark', environment={'LOCAWEB_SSH_IDENTITY_FILE': str(key), 'LOCAWEB_SSH_KNOWN_HOSTS_FILE': str(known)})
    try:
        options = ' '.join(s.options)
        assert 'StrictHostKeyChecking=yes' in options and 'IdentitiesOnly=yes' in options
        assert 'GlobalKnownHostsFile=/dev/null' in options
        assert '-F /dev/null' in options and s.destination == 'afgnet1@ftp.afgnet.com.br'
        with patch.object(s, 'rpc', side_effect=[None, '/election-ssh-staging/benchmark/' + 'a'*32 + '/payload', digest(b'abc'), 'cached-object']):
            with patch('subprocess.run') as run:
                run.return_value.returncode = 0
                run.return_value.stdout = b''
                s.upload(b'abc')
                command = run.call_args.args[0]
                assert command[0] == 'rsync'
                assert not {'--delete', '--inplace', '--append', '--ignore-errors'} & set(command)
                assert '--protect-args' in command and run.call_args.kwargs['timeout'] == 60
    finally: s.directory.cleanup()


@pytest.mark.parametrize('failure', ['none', 'before_marker', 'after_marker', 'lost_commit'])
def test_full_first_round_transaction_recovery_and_rollback(staging, tmp_path, failure):
    a, b = tmp_path / 'a', tmp_path / 'b'
    bundle(a, 1); bundle(b, 2)
    before, after = tree(a), tree(b)
    sid = 'a'*64
    marker = canonical(parse(before['version.json']) | {'snapshot_id': sid})
    for name, raw in {**{staging.site+'/releases/'+sid+'/'+n: v for n,v in before.items()}, staging.site+'/version.json': marker}.items():
        p = tmp_path / name.lstrip('/'); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)
    def http(path): return staging.read(staging.site + '/' + path)
    def injected(path):
        current = staging.read(staging.site + '/version.json')
        if failure == 'before_marker' and path.startswith('releases/') and current == marker and sid not in path:
            raise TimeoutError('fixture')
        if failure == 'after_marker' and path == 'version.json' and current != marker: raise TimeoutError('fixture')
        return http(path)
    real_rpc = staging.ftp.rpc
    def lost(op, **args):
        result = real_rpc(op, **args)
        if failure == 'lost_commit' and op == 'commit' and args.get('path') == staging.site + '/version.json':
            raise SSHError('ssh_operation_outcome_unknown')
        return result
    staging.ftp.rpc = lost
    reviews = {n:digest(after[n]) for n in targets() if n.startswith('am/')}
    if failure == 'none':
        with staging.lock(): result = first.activate(staging, after, reviews=reviews, http=http)
        assert result['files'] == 140
        with staging.lock(): assert first.activate(staging, after, http=http)['status'] == 'unchanged'
        with staging.lock(): first.rollback(staging, http=http)
    else:
        with pytest.raises((SSHError, TimeoutError)):
            with staging.lock(): first.activate(staging, after, reviews=reviews, http=injected)
        assert staging.metadata(staging.private+'/lock') is not None
        staging.ftp.rpc = real_rpc
        first.recover(staging, http=http)
    assert staging.read(staging.site+'/version.json') == marker
    assert all(staging.read(staging.site+'/releases/'+sid+'/'+n) == raw for n,raw in before.items())
    assert staging.metadata(staging.private+'/lock') is None


def test_remote_errors_do_not_print_server_details():
    assert f.error_report(SSHError('rsync_transfer_failed')) == {
        'error_type':'SSHError', 'transport':'ssh_rsync', 'error_code':'rsync_transfer_failed'}


@pytest.mark.parametrize('crash_at', ['none', 'after_file', 'before_activation', 'after_activation', 'after_checkpoint'])
def test_second_round_preserves_transaction_and_recovers(tmp_path, crash_at):
    from collector.src import second_round_publish as second
    from test_second_round_transactions import package
    root = tmp_path / 'remote'; root.mkdir()
    (root / 'public_html/data/turnos/2').mkdir(parents=True)
    sentinel = root / 'public_html/data/version.json'; sentinel.write_bytes(b'first unchanged')
    t = local(second.Transport, 'second', root)
    class Crash(BaseException): pass
    def fault(phase):
        if phase == crash_at: raise Crash()
    p = second.Publisher(t, tmp_path/'state', http=lambda name:t.read(second.SITE+'/'+name, optional=True), fault=fault)
    pkg = package(tmp_path/'package')
    if crash_at == 'none':
        assert p.publish(pkg)['status'] == 'published'
    else:
        with pytest.raises(Crash): p.publish(pkg)
        p.fault = lambda _:None
        p.recover()
    assert p.status()['checkpoint_matches']
    assert p.publish(pkg)['status'] == 'unchanged'
    assert t.metadata(second.PRIVATE+'/lock') is None
    assert sentinel.read_bytes() == b'first unchanged'


@pytest.mark.parametrize('component', ['portal', 'raio-x'])
def test_frontend_deploy_status_and_rollback_use_same_journals(tmp_path, component):
    root = tmp_path / 'remote'; root.mkdir()
    for path in ['public_html/eleicoes', 'public_html/eleicoes/goias/raio-x']:
        (root/path).mkdir(parents=True, exist_ok=True)
    t = local(f.Transport, component, root)
    source = tmp_path / 'source' / f.target(component)['source']
    source.mkdir(parents=True)
    for name in f.target(component)['entrypoints']:
        (source/name).write_text('<!doctype html><html><head><link href="styles.css"></head><body><script src="app.js"></script></body></html>')
        (root/(f.target(component)['ftp_root']+'/'+name).lstrip('/')).write_bytes(b'bootstrap')
    (source/'app.js').write_text('console.log("fixture")')
    (source/'styles.css').write_text('body {color:black}')
    out = tmp_path/'package'
    manifest = f.build(component, 'a'*40, out, root=tmp_path/'source', validate=False)
    contents = {name:(out/'files'/name).read_bytes() for name in manifest['files']}
    def http(url):
        relative = url.split('afgnet.com.br/',1)[1]
        return (root/'public_html'/ (relative + ('index.html' if relative.endswith('/') else ''))).read_bytes()
    with t.lock(component): assert f.activate(t, manifest, contents, 'first', http=http)['status'] == 'published'
    assert f.status(t, component, http=http)['commit'] == 'a'*40
    with t.lock(component): assert f.rollback(t, component, 'previous', 'restore', http=http)['status'] == 'restored_bootstrap'


@pytest.mark.parametrize('phase', ['normal', 'lost_activation', 'corrupt_backup'])
def test_finance_ssh_bytes_journal_and_recovery(tmp_path, phase):
    from deploy import ssh_finance as finance
    root = tmp_path/'remote'; root.mkdir()
    p = root/finance.PUBLIC.lstrip('/'); p.parent.mkdir(parents=True);p.write_bytes(b'{"total":123}')
    before = p.read_bytes()
    t = local(finance.Policy, 'finance', root)
    actual = t.ftp.rpc
    def interrupted(op, **args):
        result = actual(op, **args)
        if op == 'commit' and args.get('path') == finance.PUBLIC: raise SSHError('ssh_operation_outcome_unknown')
        return result
    with patch.object(finance, 'transport', return_value=t):
        if phase == 'normal':
            assert finance.publish(b'{"total":456}', p.read_bytes)['status'] == 'published'
            assert finance.publish(b'{"total":456}', p.read_bytes)['status'] == 'unchanged'
            assert t.metadata(finance.PRIVATE+'/lock') is None
        else:
            t.ftp.rpc = interrupted
            with pytest.raises(SSHError): finance.publish(b'{"total":456}', p.read_bytes)
            t.ftp.rpc = actual
            if phase == 'corrupt_backup':
                job=f.decode(t.read(finance.PRIVATE+'/pending.json'))
                backup=root/(finance.PRIVATE+'/transactions/'+job['transaction']+'/before.json').lstrip('/')
                backup.write_bytes(b'corrupt')
                with pytest.raises(ValueError,match='backup_corrupt'): finance.recover(t,p.read_bytes)
                assert p.read_bytes() == b'{"total":456}'
            else:
                assert finance.recover(t,p.read_bytes)['status'] == 'recovered'
                assert p.read_bytes() == before


def test_partial_directory_promotion_resumes_only_owned_inventory(staging, tmp_path):
    source = staging.private+'/staging/'+'b'*64+'/files'
    dest = staging.site+'/releases/'+'b'*64
    files = {}
    for i in range(140):
        name=f'go/file-{i}.json'; raw=canonical({'file':i})
        p=tmp_path/(source+'/'+name).lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        files[name]={'sha256':digest(raw),'size':len(raw)}
    (tmp_path/dest.lstrip('/')).parent.mkdir(parents=True,exist_ok=True)
    (tmp_path/'election-ssh-staging/first-staging').mkdir(parents=True)
    real = os.link
    count=0
    def interrupted(*args,**kwargs):
        nonlocal count
        count+=1
        if count==2: raise OSError('fixture interruption')
        return real(*args,**kwargs)
    with patch.object(os,'link',interrupted):
        with pytest.raises(OSError): staging.promote_release(source,dest,files)
    staging.promote_release(source,dest,files)
    assert not (tmp_path/source.lstrip('/')).exists()
    assert all(digest((tmp_path/(dest+'/'+n).lstrip('/')).read_bytes())==e['sha256'] for n,e in files.items())
    assert all((tmp_path/(dest+'/'+n).lstrip('/')).stat().st_mode & 0o777 == 0o644 for n in files)


@pytest.mark.parametrize('scope,path', [
    ('first-production','/public_html/data/turnos/2/version.json'),
    ('portal','/public_html/eleicoes/goias/raio-x/index.html'),
    ('raio-x','/public_html/eleicoes/goias/raio-x/data/go-2026.json')])
def test_server_repeats_component_and_round_guards(tmp_path,scope,path):
    with pytest.raises(ValueError):remote.path_for(path,scope,str(tmp_path))


def test_real_stdio_protocol_returns_bounded_sanitized_errors(tmp_path):
    import subprocess,sys,tempfile
    source=Path(remote.__file__).read_text().replace("HOME = '/home/storage/4/b7/e0/afgnet1'",'HOME = '+repr(str(tmp_path)))
    s=SSHSession.__new__(SSHSession)
    s.scope,s.checker,s.metrics='benchmark',None,{'ssh_failures':0,'hash_failures':0}
    s.guard,s.buffer=threading.RLock(),bytearray()
    s.directory=tempfile.TemporaryDirectory()
    s.process=subprocess.Popen([sys.executable,'-u','-c',source],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
    try:
        assert s.rpc('hello')['home']==str(tmp_path)
        with pytest.raises(SSHError) as failure:s.rpc('read',path='/public_html/estudos/private-secret')
        assert f.error_report(failure.value)['error_code']=='ssh_outside_scope'
        assert 'private-secret' not in json.dumps(f.error_report(failure.value))
    finally:s.close();s.directory.cleanup()


def test_archive_ssh_verifies_full_download_and_preserves_collision(tmp_path):
    import io
    from deploy import ssh_archive as archive
    root=tmp_path/'remote';root.mkdir()
    dest='/backup/election-results-platform/round2-cycles'
    t=local(archive.Policy,'archive-second',root,dest)
    with patch.object(archive,'transport',return_value=t):
        a=archive.ArchiveSSH(destination=dest)
        raw=b'archive-fixture'*10000
        a.upload('fixture.tar.gz',io.BytesIO(raw),len(raw),digest(raw))
        assert a.verified('fixture.tar.gz',len(raw),digest(raw))
        with pytest.raises(ValueError,match='hash_mismatch'):
            a.upload('fixture.tar.gz',io.BytesIO(b'X'*len(raw)),len(raw),digest(b'X'*len(raw)))
        assert (root/(dest+'/fixture.tar.gz').lstrip('/')).read_bytes()==raw
