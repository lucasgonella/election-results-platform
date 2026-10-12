"""Synthetic complete releases; no production, database or TSE connections."""
import ftplib
from pathlib import Path
import pytest
from collector.src.election_release import canonical, digest, parse, targets, tree
from collector.src.static_election_publish import Transport, activate, compare, descriptor, recover, rollback
from static_election_fixtures import bundle
from test_frontend_deploy import FakeFTP


class ElectionFTP(FakeFTP):
    def close(self): pass
    def rename(self, old, new):
        if old in self.dirs:
            self.events.append(('rename_directory',new))
            for name in list(self.files):
                if name.startswith(old+'/'): self.files[new+name[len(old):]]=self.files.pop(name)
            for name in list(self.dirs):
                if name==old or name.startswith(old+'/'):
                    self.dirs.add(new+name[len(old):]);self.dirs.remove(name)
            return
        return super().rename(old,new)


@pytest.fixture
def release(tmp_path):
    root=tmp_path/'first';bundle(root,1)
    values=tree(root);ftp=ElectionFTP();transport=Transport(ftp,'staging')
    ftp.dirs.update({'/public_html/__election_static_staging',transport.site,transport.site+'/releases',transport.site+'/releases/'+'a'*64})
    marker=canonical(parse(values['version.json'])|{'snapshot_id':'a'*64})
    ftp.files[transport.site+'/version.json']=marker
    for name,raw in values.items():
        ftp.files[transport.site+'/releases/'+'a'*64+'/'+name]=raw
    def http(path): return ftp.files[transport.site+'/'+path]
    second=tmp_path/'second';bundle(second,2)
    return transport,values,tree(second),marker,http


def test_complete_release_single_marker_then_rollback(release):
    transport,before,after,old,http=release
    with transport.lock(): result=activate(transport,after,reviews={n:digest(after[n]) for n in targets() if n.startswith('am/')},http=http)
    assert result['status']=='published' and result['files']==140
    assert result['multinode_guarantee'] is False
    sid=result['snapshot_id'];root=transport.private+'/transactions/'+result['transaction']
    backup=transport.private+'/backups/'+'a'*64+'/files'
    assert all(transport.ftp.files[backup+'/'+n]==raw for n,raw in before.items())
    events=transport.ftp.events
    promote=next(i for i,e in enumerate(events) if e==('rename_directory',transport.site+'/releases/'+sid))
    marker=next(i for i,e in enumerate(events) if e==('rename',transport.site+'/version.json'))
    assert marker>promote
    previous_events=len(events)
    with transport.lock():again=activate(transport,after,http=http)
    assert again['status']=='unchanged' and again['published_at']==result['published_at']
    assert not any(e[0]=='upload' for e in transport.ftp.events[previous_events:])
    with transport.lock(): rollback(transport,http=http)
    assert transport.ftp.files[transport.site+'/version.json']==old
    assert transport.metadata(transport.private+'/lock/') is None


@pytest.mark.parametrize('kind',['transfer','marker_rename','http'])
def test_interrupted_publication_preserves_previous_and_recovers(release,kind):
    transport,before,after,old,http=release
    if kind=='transfer':transport.ftp.corrupt_upload=True
    if kind=='marker_rename':transport.ftp.fail_rename=transport.site+'/version.json'
    calls=0
    def bad(path):
        nonlocal calls
        calls+=1
        # Before-selection checks succeed; post-selection read fails.
        if kind=='http' and path=='version.json' and parse(transport.ftp.files[transport.site+'/version.json'])['snapshot_id']!='a'*64:
            raise OSError('simulated network loss')
        return http(path)
    with pytest.raises(Exception):
        with transport.lock():activate(transport,after,reviews={n:digest(after[n]) for n in targets() if n.startswith('am/')},http=bad)
    assert transport.metadata(transport.private+'/lock/') is not None
    if kind=='transfer':
        assert transport.ftp.files[transport.site+'/version.json']==old
        return # Failure during initial backup: no journal; operator inspects retained backup.
    recover(transport,http=http)
    assert transport.ftp.files[transport.site+'/version.json']==old


@pytest.mark.parametrize('name',['/public_html/eleicoes/index.html','/public_html/eleicoes/goias/raio-x/data/go-2026.json',
 ' /public_html/data/version.json','/public_html/data/rj/governor.json','/election-static-deploy/production/../../secret'])
def test_bounded_transport_cannot_overwrite_other_components(name):
    with pytest.raises(ValueError):Transport(None).writable(name)


@pytest.mark.parametrize('kind',['identity','path','counts','metadata','negative','duplicate_json'])
def test_invalid_release_fails_before_network_mutations(release,kind):
    transport,before,after,old,http=release
    name='rj/governor.json';value=parse(after[name])
    if kind=='identity':value['scope']['code']='am'
    if kind=='negative':value['candidates'][0]['votes']=-1
    if kind=='counts':value['candidate_count']=2
    if kind in {'identity','negative','counts'}:after[name]=canonical(value)
    if kind=='metadata':after['alerts.json']=canonical({'generated_at':'2020-01-01T00:00:00+00:00'})
    if kind=='path':after['../other.json']=b'{}'
    if kind=='duplicate_json':after[name]=b'{"candidates":[],"candidates":[]}'
    with pytest.raises((ValueError,KeyError)):activate(transport,after,http=http)
    assert transport.ftp.events==[]


def test_idg_does_not_approve_removals_or_am(release):
    transport,before,after,old,http=release
    # AM generation changed even with a matching roster: requires review.
    with pytest.raises(ValueError,match='specific_review'):compare(before,after)
    reviews={n:digest(after[n]) for n in targets() if n.startswith('am/')}
    compare(before,after,reviews)
    name='rj/governor.json';v=parse(after[name]);v['candidates']=[];v['candidate_count']=0;after[name]=canonical(v)
    with pytest.raises(ValueError,match='specific_review'):compare(before,after,reviews)


def test_generation_regression_and_reopening_stay_blocked(release):
    transport,before,after,old,http=release
    name='rj/governor.json';v=parse(after[name]);v['snapshot']['generated_at']='2026-10-01T00:00:00+00:00';after[name]=canonical(v)
    reviews={n:digest(after[n]) for n in targets() if n.startswith('am/')}
    with pytest.raises(ValueError,match='result_regression'):compare(before,after,reviews)
    v['snapshot']['generated_at']='2026-10-09T12:00:02+00:00';v['snapshot']['totalization_final']=False;after[name]=canonical(v)
    with pytest.raises(ValueError,match='totalization_reopened'):compare(before,after,reviews)


def test_static_read_reconnects_after_timeout(monkeypatch):
    from deploy import frontend as wire
    attempts = []
    sessions = [ElectionFTP(), ElectionFTP()]
    def unreliable(self, path, *, optional=False):
        attempts.append(self.ftp)
        if len(attempts) == 1:
            raise TimeoutError("interrupted RETR")
        return b'verified bytes'
    monkeypatch.setattr(wire.Transport, "read", unreliable)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    transport = Transport(sessions[0], "staging", reconnect=lambda: sessions[1])
    path = transport.site + "/version.json"
    assert transport.read(path) == b'verified bytes'
    assert attempts == sessions


def test_static_read_retry_is_bounded(monkeypatch):
    from deploy import frontend as wire
    calls = []
    def always_timeout(self, path, *, optional=False):
        calls.append(path)
        raise TimeoutError("interrupted RETR")
    monkeypatch.setattr(wire.Transport, "read", always_timeout)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    transport = Transport(ElectionFTP(), "staging", reconnect=ElectionFTP)
    with pytest.raises(RuntimeError, match="ftp_read_failed.*attempts=3.*TimeoutError"):
        transport.read(transport.site + "/version.json")
    assert len(calls) == 3


def test_election_ftp_timeout_is_isolated(monkeypatch):
    from collector.src import static_election_publish as pub
    from deploy import frontend as wire

    class Socket:
        def __init__(self):
            self.timeout = None
        def settimeout(self, value):
            self.timeout = value

    class FTP:
        def __init__(self):
            self.timeout = 90
            self.sock = Socket()

    sessions = []
    def original_connect():
        session = FTP()
        sessions.append(session)
        return session

    monkeypatch.setattr(wire, "connect", original_connect)
    transport = pub.connect("staging")
    assert transport.ftp.timeout == 15
    assert transport.ftp.sock.timeout == 15
    assert transport.reconnect is pub.election_ftp_connect
    renewed = transport.reconnect()
    assert renewed.timeout == 15
    assert renewed.sock.timeout == 15
    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]


def test_forward_finalize_published_release_without_rollback(release):
    from collector.src.static_election_publish import finalize_published
    transport,before,after,old,http=release
    reviews={n:digest(after[n]) for n in targets() if n.startswith('am/')}
    with transport.lock():
        result=activate(transport,after,reviews=reviews,http=http)
    sid=result['snapshot_id']
    tx=result['transaction']
    journal_path=transport.private+'/transactions/'+tx+'/journal.json'
    journal=parse(transport.ftp.files[journal_path])
    journal['status']='prepared'
    journal.pop('published_at',None)
    transport.ftp.files[journal_path]=canonical(journal)
    transport.ftp.files[transport.private+'/pending.json']=canonical(journal)
    transport.ftp.dirs.add(transport.private+'/lock')
    finished=finalize_published(transport,sid,http=http)
    assert finished['status']=='forward_finalized'
    assert transport.metadata(transport.private+'/lock/') is None
    assert transport.ftp.files[transport.site+'/version.json']!=old
    assert parse(transport.ftp.files[journal_path])['status']=='published'
    assert parse(transport.ftp.files[transport.private+'/pending.json'])=={'status':'complete','snapshot_id':sid}


def test_forward_finalize_rejects_wrong_snapshot_and_retains_lock(release):
    from collector.src.static_election_publish import finalize_published
    transport,before,after,old,http=release
    transport.ftp.dirs.add(transport.private+'/lock')
    with pytest.raises(ValueError,match='published_snapshot_changed|forward_finalization_state_mismatch'):
        finalize_published(transport,'f'*64,http=http)
    assert transport.metadata(transport.private+'/lock/') is not None
