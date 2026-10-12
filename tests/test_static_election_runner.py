"""Synthetic collection callbacks, no TSE or server. Preserves all old trees."""
from pathlib import Path
import pytest
from collector.src.election_release import META, canonical, digest, parse, tree
from collector.src import static_election_publish as pub
from collector.src import static_election_runner as runner
from test_static_election_publish import release


def checkpoint(root, values):
    root.mkdir()
    for name in META:(root/name).write_bytes(values[name])
    rows=parse(values['manifest.json'])['results']
    (root/'target-state.json').write_bytes(canonical({'https://fixture.invalid/'+r['path']:{'path':r['path'],'tse_idg':r['tse_idg']} for r in rows}))
    (root/'state-meta.json').write_bytes(canonical({'result_alert_version':3}))


def test_cycle_keeps_am_and_original_trees_and_adopts_matching_checkpoint(release,tmp_path,monkeypatch):
    transport,before,after,old,http=release
    sid=digest(canonical(pub.descriptor(before)))
    root=tmp_path/'static';package=root/'generations'/sid;package.mkdir(parents=True)
    dest=package/'candidate';dest.mkdir()
    for name,raw in before.items():
        path=dest/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        transport.ftp.files[transport.site+'/releases/'+sid+'/'+name]=raw
    marker=canonical(parse(before['version.json'])|{'snapshot_id':sid});transport.ftp.files[transport.site+'/version.json']=marker
    transport.ftp.dirs.add(transport.site+'/releases/'+sid)
    checkpoint(package/'checkpoint',before)
    runner.save(root/'current.json',{'snapshot_id':sid,'descriptor':pub.descriptor(before),'package':str(package),'published_at':'2026-10-09T13:00:01+00:00'})
    original=tree(package)
    monkeypatch.setattr(runner,'connect',lambda environment:transport)
    monkeypatch.setattr(pub,'http_read',lambda environment,path:http(path))
    def collect(work):
        stage=work/'stage';stage.mkdir()
        for name,raw in after.items():
            p=stage/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        checkpoint(work/'pending',after)
        return {'status':'prepared'}
    health=runner.run_cycle(root,collect=collect)
    assert health['status']=='published'
    assert set(health['review_required'])=={n for n in before if n.startswith('am/')}
    current=parse((root/'current.json').read_bytes());new=tree(Path(current['package'])/'candidate')
    assert len(new)==140
    assert all(new[n]==before[n] for n in before if n.startswith('am/'))
    assert tree(package)==original
    assert parse((root/'in-flight.json').read_bytes())['status']=='complete'


def test_interrupted_job_never_starts_another_collection(tmp_path):
    runner.save(tmp_path/'in-flight.json',{'package':'preserved','prepared_at':'2026-10-10T00:00:00+00:00'})
    def forbidden(work):raise AssertionError('must not collect')
    with pytest.raises(ValueError,match='interrupted_job_requires_reconciliation'):
        runner.run_cycle(tmp_path,collect=forbidden)
