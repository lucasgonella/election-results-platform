"""Synthetic official-shaped data in isolated test FTP only; no public writes."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import ftplib
import threading

import pytest

from collector.src.election_release import canonical, parse, tree
from collector.src.second_round_collection import AwaitingData, build_values, discover
from collector.src.second_round_publish import SITE, PRIVATE, Publisher, Transport, describe, load, local_lock, save
from test_frontend_deploy import FakeFTP
from test_parser import build_payload


class FTP(FakeFTP):
    def close(self): pass
    def cwd(self, path):
        from pathlib import PurePosixPath
        current = getattr(self, '_cwd', '/')
        self._cwd = str(PurePosixPath(current) / path)
        assert self._cwd in self.dirs
    def pwd(self): return getattr(self, '_cwd', '/')
    def mkd(self, path):
        from pathlib import PurePosixPath
        return super().mkd(str(PurePosixPath(self.pwd()) / path))


class Source:
    def __init__(self, *, totalized=50, generation=1):
        config = {'f': 'o', 'pl': [{'c': 'ele2026', 'e': [{'cd': '6260', 't': '2', 'tp': '1',
             'nm': 'Teste', 'abr': [{'cd': 'ac', 'cp': [{'cd': '3', 'ds': 'Governador'}]}]}]}]}
        ea14 = {'f': 'o', 'ele': '6260', 't': '2', 'idg': '1',
                 'abr': [{'tpabr': 'uf', 'cdabr': 'ac'}, {'tpabr': 'uf', 'cdabr': 'go'}]}
        payload = build_payload()
        payload.update(f='o', ele='6260', t='2', dg='25/10/2026', hg=f'12:00:{generation:02d}')
        payload['s']['st'] = str(totalized)
        for candidate in payload['carg'][0]['agr'][0]['par'][0]['cand']:
            candidate.update(st='Não eleito', e='n')
        self.config, self.ea14, self.payload = config, ea14, payload
        self.records = {}

    def fetch_json(self, url):
        value = self.config if '/comum/' in url else self.ea14 if '-ab.json' in url else self.payload
        self.records[url] = {'url': url, 'payload': deepcopy(value), 'sha256': 'a'*64}
        return SimpleNamespace(payload=deepcopy(value), status_code=200)


def package(root, generation=1):
    client = Source(generation=generation)
    values = build_values(client, discover(client))
    root.mkdir()
    for name, raw in values.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return root


@pytest.fixture
def rig(tmp_path):
    ftp = FTP()
    ftp.dirs.update({'/public_html/data', '/public_html/data/turnos', SITE})
    ftp.files['/public_html/data/version.json'] = b'first round unchanged'
    ftp.files['/public_html/eleicoes/goias/raio-x/data/go-2026.json'] = b'finance unchanged'
    transport = Transport(ftp)
    http = lambda path: ftp.files.get(SITE + '/' + path)
    publisher = Publisher(transport, tmp_path / 'state', http=http)
    return publisher, package(tmp_path / 'one'), ftp


def test_inventory_filters_config_coverage_and_ea14():
    plans = discover(Source())
    assert [(t.scope_code,t.office_code) for p in plans for t in p.targets] == [('ac',3)]


@pytest.mark.parametrize('field,value', [('t','1'), ('f','s'), ('ele','6259')])
def test_ea14_wrong_identity_fails(field,value):
    client = Source()
    client.ea14[field] = value
    with pytest.raises(ValueError, match='invalid_second_round_ea14'): discover(client)


def test_no_results_is_informative():
    client = Source(totalized=0)
    with pytest.raises(AwaitingData): build_values(client, discover(client))


def test_deterministic_source_identity():
    a, b = Source(), Source()
    assert build_values(a, discover(a)) == build_values(b, discover(b))


def test_complete_publication_idempotent_and_preserves_others(rig):
    p, package, ftp = rig
    first = p.publish(package)
    events = len(ftp.events)
    assert p.publish(package)['status'] == 'unchanged'
    assert not any(e[0]=='upload' for e in ftp.events[events:])
    assert first['status'] == 'published'
    assert p.status()['checkpoint_matches']
    assert ftp.files['/public_html/data/version.json'] == b'first round unchanged'
    assert ftp.files['/public_html/eleicoes/goias/raio-x/data/go-2026.json'] == b'finance unchanged'
    assert PRIVATE + '/lock' not in ftp.dirs
    assert load(p.job_path) is None


class Crash(BaseException): pass


@pytest.mark.parametrize('boundary', ['after_journal','after_lock','after_file','before_activation',
                                     'after_activation','before_checkpoint','after_checkpoint'])
def test_interruptions_recover_without_replaying_unknown_activation(rig,boundary):
    p, package, ftp = rig
    def fault(point):
        if point == boundary: raise Crash()
    p.fault = fault
    with pytest.raises(Crash): p.publish(package)
    before = sum(e == ('rename', SITE+'/version.json') for e in ftp.events)
    p.fault = lambda _: None
    result = p.recover()
    assert result['status'] == 'published'
    assert sum(e == ('rename', SITE+'/version.json') for e in ftp.events) == 1
    if before: assert before == 1
    assert p.status()['checkpoint_matches']


def test_failed_new_release_preserves_previous(rig,tmp_path):
    p, first, ftp = rig
    p.publish(first)
    marker = ftp.files[SITE + '/version.json']
    second = package(tmp_path/'two',2)
    def crash(point):
        if point == 'before_activation': raise Crash()
    p.fault = crash
    with pytest.raises(Crash): p.publish(second)
    assert ftp.files[SITE + '/version.json'] == marker
    p.fault = lambda _: None
    assert p.recover()['status'] == 'published'
    assert all(name in ftp.files for name in [SITE+'/releases/'+parse(marker)['snapshot_id']+'/ac/governor.json'])


def test_new_data_waits_for_pending(rig,tmp_path):
    p, first, ftp = rig
    p.fault = lambda point: (_ for _ in ()).throw(Crash()) if point == 'before_activation' else None
    with pytest.raises(Crash): p.publish(first)
    p.fault = lambda _: None
    second = package(tmp_path/'two',2)
    assert p.publish(second)['status'] == 'published'
    assert len(list((p.state/'receipts').glob('*.json'))) == 2


def test_visibility_unknown_never_reactivates(rig):
    p, package, ftp = rig
    p.fault = lambda point: (_ for _ in ()).throw(Crash()) if point == 'after_activation' else None
    with pytest.raises(Crash): p.publish(package)
    events = len(ftp.events)
    p.http = lambda path: None
    with pytest.raises(RuntimeError,match='visibility_unknown'): p.recover()
    assert len(ftp.events) == events


def test_external_marker_and_unknown_locks_block(rig):
    p, package, ftp = rig
    ftp.dirs.add(PRIVATE)
    ftp.dirs.add(PRIVATE+'/lock')
    with pytest.raises(RuntimeError,match='orphan_lock'): p.publish(package)
    assert SITE+'/version.json' not in ftp.files


def test_concurrency_local_fence(tmp_path):
    with local_lock(tmp_path/'state'):
        with pytest.raises(RuntimeError,match='writer_busy'):
            with local_lock(tmp_path/'state'): pass


@pytest.mark.parametrize('path', ['/public_html/data/version.json','/public_html/estudos/a.json',
 '/public_html/eleicoes/goias/raio-x/index.html','/public_html/data/turnos/1/version.json',
 SITE+'/../version.json',SITE+'/releases/'+'a'*64+'/../../version.json'])
def test_transport_rejects_other_namespaces(path):
    with pytest.raises(ValueError): Transport(None).writable(path)


@pytest.mark.parametrize('case', ['manifest','round','negative','elected','scope'])
def test_incomplete_or_invalid_release_never_starts(rig,case):
    p, package, ftp = rig
    file = package/'ac/governor.json'
    data = parse(file.read_bytes())
    if case=='manifest': (package/'manifest.json').unlink()
    elif case=='round': data['election']['round']=1
    elif case=='negative': data['candidates'][0]['votes']=-1
    elif case=='elected': data['candidates'][0]['elected']=True
    elif case=='scope': data['scope']['code']='zz'
    file.write_bytes(canonical(data))
    with pytest.raises((ValueError,KeyError)): p.publish(package)
    assert ftp.events == []


def test_corrupt_upload_and_https_timeout_recover(rig):
    p, package, ftp = rig
    original = ftp.storbinary
    failed = False
    def corrupt(command,stream):
        nonlocal failed
        if '/releases/' in command and not failed:
            ftp.corrupt_upload=True
            failed=True
        original(command,stream)
    ftp.storbinary=corrupt
    with pytest.raises(RuntimeError): p.publish(package)
    assert SITE+'/version.json' not in ftp.files
    assert p.recover()['status']=='published'


def test_crash_during_partial_stor_reconciles_owned_temporary(rig):
    p, package, ftp = rig
    original = ftp.storbinary
    def broken(command,stream):
        if '/releases/' in command:
            ftp.files[command.removeprefix('STOR ')]=stream.read()[:12]
            raise Crash()
        original(command,stream)
    ftp.storbinary=broken
    with pytest.raises(Crash): p.publish(package)
    ftp.storbinary=original
    assert p.recover()['status']=='published'


def test_ftp_real_isolated_server(tmp_path):
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
    authorizer=DummyAuthorizer()
    authorizer.add_user('test','synthetic-only',str(tmp_path),perm='elradfmwMT')
    class Handler(FTPHandler): pass
    Handler.authorizer=authorizer
    server=FTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,kwargs={'timeout':0.01},daemon=True)
    thread.start()
    ftp=ftplib.FTP()
    try:
        ftp.connect('127.0.0.1',server.socket.getsockname()[1],timeout=5)
        ftp.login('test','synthetic-only')
        transport=Transport(ftp)
        path=PRIVATE+'/transactions/'+'a'*24+'/descriptor.json'
        transport.put(path,b'isolated transfer')
        assert transport.read(path)==b'isolated transfer'
        transport.put(path,b'isolated rename replacement',replace=True)
        assert transport.read(path)==b'isolated rename replacement'
    finally:
        ftp.close()
        server.close_all()
        thread.join(timeout=5)


def test_owned_committed_orphan_lock_recovered(rig):
    p, package, ftp=rig
    p.fault=lambda point: (_ for _ in ()).throw(Crash()) if point=='after_owner_cleanup' else None
    with pytest.raises(Crash):p.publish(package)
    assert PRIVATE+'/lock' in ftp.dirs
    assert PRIVATE+'/lock/owner.json' not in ftp.files
    p.fault=lambda _:None
    assert p.recover()['status']=='published'
    assert PRIVATE+'/lock' not in ftp.dirs


@pytest.mark.parametrize('boundary',['before_bytes','partial_bytes','all_bytes','rename_done'])
def test_ftp_disconnects_reconcile_actual_remote_bytes(rig,boundary):
    p, package, ftp=rig
    original_stor,original_rename=ftp.storbinary,ftp.rename
    failed=False
    def stor(command,stream):
        nonlocal failed
        if '/releases/' in command and not failed and boundary!='rename_done':
            failed=True
            if boundary=='partial_bytes':ftp.files[command.removeprefix('STOR ')]=stream.read()[:10]
            elif boundary=='all_bytes':original_stor(command,stream)
            raise EOFError('disconnected')
        original_stor(command,stream)
    def rename(old,new):
        nonlocal failed
        original_rename(old,new)
        if '/releases/' in new and boundary=='rename_done' and not failed:
            failed=True
            raise EOFError('reply lost')
    ftp.storbinary,ftp.rename=stor,rename
    # Lost completion response gets byte reconciliation; incomplete transfers leave journal.
    p.t.reconnect=lambda:ftp
    try:result=p.publish(package)
    except Exception:result=p.recover()
    assert result['status']=='published' and p.status()['checkpoint_matches']


def test_https_timeout_keeps_previous_until_verification(rig,tmp_path):
    p,first,ftp=rig
    p.publish(first)
    old=ftp.files[SITE+'/version.json']
    second=package(tmp_path/'two',2)
    good=p.http
    def timeout(path):
        if path.startswith('releases/') and parse(old)['snapshot_id'] not in path:
            raise TimeoutError('HTTPS unavailable')
        return good(path)
    p.http=timeout
    with pytest.raises(TimeoutError):p.publish(second)
    assert ftp.files[SITE+'/version.json']==old
    p.http=good
    assert p.recover()['status']=='published'


def test_remote_checkpoint_divergence_is_not_silently_adopted(rig):
    p,package,ftp=rig
    p.publish(package)
    marker=parse(ftp.files[SITE+'/version.json'])
    save(p.checkpoint_path,{'snapshot_id':'b'*64})
    # Known receipt allows only the already audited remote release to reconcile.
    assert p.reconcile()['snapshot_id']==marker['snapshot_id']
    assert load(p.checkpoint_path)['snapshot_id']==marker['snapshot_id']
    (p.state/'receipts'/(marker['snapshot_id']+'.json')).unlink()
    save(p.checkpoint_path,{'snapshot_id':'b'*64})
    with pytest.raises(RuntimeError,match='unrecognized'):p.reconcile()


def test_publication_metadata_stale_control_socket_reconnects_without_write(monkeypatch):
    from deploy import frontend as wire
    first,second=FTP(),FTP()
    calls=[]
    original=wire.Transport.metadata
    def broken(self,path):
        calls.append(self.ftp)
        if self.ftp is first:raise ConnectionResetError('idle control socket')
        return original(self,path)
    monkeypatch.setattr(wire.Transport,'metadata',broken)
    monkeypatch.setattr('time.sleep',lambda _:None)
    transport=Transport(first,reconnect=lambda:second)
    assert transport.metadata(SITE+'/version.json') is None
    assert calls==[first,second]
    assert first.events==second.events==[]


def test_lost_mkd_response_reconciles_remote_directory_without_replay():
    ftp=FTP();original=ftp.mkd;attempts=[]
    def lost(path):
        attempts.append(path)
        original(path)
        raise EOFError('MKD reply lost')
    ftp.mkd=lost
    t=Transport(ftp,reconnect=lambda:ftp)
    t.directory(PRIVATE)
    assert attempts==[PRIVATE.lstrip('/')]
    assert t.metadata(PRIVATE+'/')['type']=='dir'


def test_private_prefix_collision_fails_closed_without_overwrite():
    from collector.src.second_round_publish import transaction_path
    ftp=FTP();t=Transport(ftp)
    first='a'*64;second='a'*24+'b'*40
    path=transaction_path(first,'descriptor.json')
    assert path==transaction_path(second,'descriptor.json')
    original=canonical({'snapshot_id':first})
    t.put(path,original)
    with pytest.raises(RuntimeError,match='immutable_collision'):
        t.put(transaction_path(second,'descriptor.json'),canonical({'snapshot_id':second}))
    assert t.read(path)==original


def test_connection_timeout_port_passive_and_home_are_pinned(monkeypatch):
    from collector.src.second_round_publish import ftp_connect
    from deploy import frontend as wire
    calls=[]
    class Session:
        def connect(self,host,port,timeout):calls.append(('connect',port,timeout))
        def login(self,user,password):pass
        def set_pasv(self,value):calls.append(('passive',value))
        def pwd(self):return '/'
        def close(self):pass
    monkeypatch.setattr(wire,'PassiveFTP',Session)
    for key in ('HOST','USER','PASSWORD'):monkeypatch.setenv('LOCAWEB_FTP_'+key,'synthetic-only')
    monkeypatch.setenv('LOCAWEB_FTP_PORT','21')
    assert isinstance(ftp_connect(),Session)
    assert calls==[('connect',21,15),('passive',True)]


def test_native_ftp_uses_multicwd_without_credentials_in_argv(monkeypatch):
    from collector.src.second_round_publish import native_transfer
    from types import SimpleNamespace
    calls=[]
    monkeypatch.setenv('LOCAWEB_FTP_HOST','example.invalid')
    monkeypatch.setenv('LOCAWEB_FTP_USER','synthetic-user')
    monkeypatch.setenv('LOCAWEB_FTP_PASSWORD','synthetic-secret')
    def run(command,**kwargs):
        calls.append(command)
        assert 'synthetic-user' not in ' '.join(command)
        assert 'synthetic-secret' not in ' '.join(command)
        return SimpleNamespace(returncode=0,stdout=b'bytes')
    monkeypatch.setattr('subprocess.run',run)
    assert native_transfer(SITE+'/version.json')==b'bytes'
    command=calls[0]
    assert command[command.index('--ftp-method')+1]=='multicwd'
    assert command[command.index('--proto')+1]=='=ftp'
    assert command[-1].startswith('ftp://example.invalid:21/')


def test_long_release_directory_uses_basename_mkd_and_restores_home():
    ftp=FTP()
    ftp.dirs.update({'/public_html/data','/public_html/data/turnos',SITE})
    calls=[];original=ftp.mkd
    def inspect(name):
        calls.append(name)
        assert '/' not in name
        return original(name)
    ftp.mkd=inspect
    t=Transport(ftp)
    t.directory(SITE+'/releases/'+'a'*64)
    assert calls==['releases','a'*64]
    assert ftp.pwd()=='/'
    assert t.metadata(SITE+'/releases/'+'a'*64+'/')['type']=='dir'


def test_production_data_transport_keeps_one_passive_session(monkeypatch):
    from collector.src import second_round_publish as pub
    ftp=FTP()
    monkeypatch.setattr(pub,'ftp_connect',lambda:ftp)
    t=pub.connect()
    assert t.ftp is ftp and t.transfer is None
    assert t.reconnect() is ftp
