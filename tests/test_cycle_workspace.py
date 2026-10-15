from pathlib import Path
import pytest
from collector.src import static_election_runner as runner
from collector.src import static_election_publish as pub
from collector.src import cycle_retention as retention
from collector.src.election_release import META, canonical, digest, parse, tree
from test_static_election_publish import release
from test_static_election_runner import checkpoint


def setup(root, release, monkeypatch):
    transport,before,after,old,http=release
    sid=digest(canonical(pub.descriptor(before)))
    package=root/'generations'/sid
    for name,raw in before.items():
        path=package/'candidate'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        transport.ftp.files[transport.site+'/releases/'+sid+'/'+name]=raw
    transport.ftp.files[transport.site+'/version.json']=canonical(parse(before['version.json'])|{'snapshot_id':sid})
    checkpoint(package/'checkpoint',before)
    runner.save(root/'current.json',{'snapshot_id':sid,'descriptor':pub.descriptor(before),
        'package':str(package),'published_at':'2026-10-09T13:00:01+00:00'})
    monkeypatch.setattr(runner,'connect',lambda environment:transport)
    monkeypatch.setattr(pub,'http_read',lambda environment,path:http(path))
    monkeypatch.setenv('ELECTION_MIN_FREE_BYTES','1')
    return before,after,package


def test_repeated_review_has_one_compact_evidence_and_unchanged_baseline(release,tmp_path,monkeypatch):
    before,after,package=setup(tmp_path,release,monkeypatch)
    original=tree(package)
    def collect(work):
        for name in {n for n in after if n.startswith('am/')}|META:
            path=work/'stage'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(after[name])
        checkpoint(work/'pending',after)
        return {'errors':[]}
    a=runner.run_cycle(tmp_path,collect=collect)
    first=tree(Path(a['cycle']))
    b=runner.run_cycle(tmp_path,collect=collect)
    assert a['status']==b['status']=='unchanged'
    assert a['cycle']==b['cycle']
    assert tree(Path(a['cycle']))==first
    assert tree(package)==original
    assert len(list((tmp_path/'cycles').iterdir()))==1
    assert not list(tmp_path.glob('.collection-*'))
    assert not (tmp_path/'in-flight.json').exists()
    assert not (Path(a['cycle'])/'collection/state').exists()
    assert not (Path(a['cycle'])/'collection/pending').exists()


def test_no_changes_or_http_304_create_no_durable_cycle(release,tmp_path,monkeypatch):
    before,after,package=setup(tmp_path,release,monkeypatch)
    def collect(work):
        checkpoint(work/'pending',before)
        return {'errors':[],'changed_targets':0}
    for _ in range(2):
        report=runner.run_cycle(tmp_path,collect=collect)
        assert report['status']=='unchanged'
    assert not (tmp_path/'cycles').exists()
    assert not list(tmp_path.glob('.collection-*'))


def test_storage_guard_preserves_pending_job(tmp_path,monkeypatch):
    job=tmp_path/'in-flight.json';job.write_text('{"package":"preserved"}')
    monkeypatch.setattr(retention,'storage',lambda root:{'free_bytes':0,'total_bytes':100,'used_percent':100})
    with pytest.raises(ValueError,match='publisher_storage_limit'):
        runner.run_cycle(tmp_path,collect=lambda work:pytest.fail('must not collect'))
    assert job.read_text()=='{"package":"preserved"}'


def test_http_read_retries_transport_failure_without_accepting_partial_bytes(monkeypatch):
    import time
    attempts=[]
    class Response:
        status=200
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def geturl(self): return 'https://afgnet.com.br/data/version.json'
        def read(self,size):
            if len(attempts)==1: raise TimeoutError()
            return b'complete'
    class Opener:
        def open(self,*args,**kwargs): attempts.append(1);return Response()
    monkeypatch.setattr(pub,'build_opener',lambda *args:Opener())
    monkeypatch.setattr(time,'sleep',lambda delay:None)
    assert pub.http_read('production','version.json')==b'complete'
    assert len(attempts)==2
