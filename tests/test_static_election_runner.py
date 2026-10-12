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


def test_legacy_bootstrap_is_local_only_and_keeps_two_identifiers(release,tmp_path,monkeypatch):
    _,before,_,_,_=release
    from collector.src.static_election_publish import descriptor
    base=tmp_path/'historical';base.mkdir()
    for name,raw in before.items():
        target=base/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    marker=tmp_path/'marker.json'
    historical_id='f'*64
    marker.write_bytes(canonical(parse(before['version.json'])|{'snapshot_id':historical_id}))
    state=tmp_path/'legacy-state'
    checkpoint(state,before)
    monkeypatch.setattr(runner,'LEGACY_PUBLIC_SNAPSHOT',historical_id)
    monkeypatch.setattr(runner,'LEGACY_CONTENT_SNAPSHOT',digest(canonical(descriptor(before))))
    root=tmp_path/'isolated';root.mkdir()
    report=runner.prepare_legacy_bootstrap(root,base,marker,state)
    assert report['status']=='prepared_locally_not_adopted'
    assert report['legacy_snapshot_id']!=report['content_snapshot_id']
    assert tree(root/'bootstrap-legacy'/'candidate')==before
    assert tree(root/'bootstrap-legacy'/'checkpoint')==tree(state)
    assert not (root/'current.json').exists()
    assert not (root/'health.json').exists()
    with pytest.raises(ValueError,match='bootstrap_already_exists'):
        runner.prepare_legacy_bootstrap(root,base,marker,state)


def test_legacy_bootstrap_rejects_unexpected_snapshot(release,tmp_path):
    _,before,_,_,_=release
    base=tmp_path/'baseline';base.mkdir()
    for name,raw in before.items():
        target=base/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    marker=tmp_path/'marker.json';marker.write_bytes(canonical(parse(before['version.json'])|{'snapshot_id':'0'*64}))
    state=tmp_path/'checkpoint';checkpoint(state,before)
    root=tmp_path/'new';root.mkdir()
    with pytest.raises(ValueError,match='unexpected_legacy_snapshot'):
        runner.prepare_legacy_bootstrap(root,base,marker,state)
    assert not (root/'bootstrap-legacy').exists()


def test_remote_legacy_adoption_preserves_public_marker(release,tmp_path,monkeypatch):
    transport,before,_,_,http=release
    historical='f'*64
    content=digest(canonical(pub.descriptor(before)))
    monkeypatch.setattr(runner,'LEGACY_PUBLIC_SNAPSHOT',historical)
    monkeypatch.setattr(runner,'LEGACY_CONTENT_SNAPSHOT',content)
    marker=canonical(parse(before['version.json'])|{'snapshot_id':historical})
    transport.ftp.files[transport.site+'/version.json']=marker
    transport.ftp.dirs.add(transport.site+'/releases/'+historical)
    for name,raw in before.items():
        transport.ftp.files[transport.site+'/releases/'+historical+'/'+name]=raw
    root=tmp_path/'static';root.mkdir()
    base=tmp_path/'base';base.mkdir()
    for name,raw in before.items():
        path=base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    marker_path=tmp_path/'marker.json';marker_path.write_bytes(marker)
    legacy_state=tmp_path/'state'
    checkpoint(legacy_state,before)
    runner.prepare_legacy_bootstrap(root,base,marker_path,legacy_state)
    monkeypatch.setattr(pub,'http_read',lambda environment,path: (
        marker if path=='version.json' else transport.ftp.files[
            transport.site+'/releases/'+historical+'/'+path.removeprefix('releases/'+historical+'/')]
    ))
    report=runner.adopt_legacy_remote(root,transport=transport)
    assert report['status']=='adopted_legacy'
    assert transport.ftp.files[transport.site+'/version.json']==marker
    current=parse(transport.ftp.files[transport.private+'/current.json'])
    assert current['snapshot_id']==historical and current['content_snapshot_id']==content
    assert len(parse(transport.ftp.files[transport.private+'/watermarks.json']))==137
    assert parse((root/'current.json').read_bytes())['snapshot_id']==historical
    with pytest.raises(ValueError,match='static_state_already_adopted'):
        runner.adopt_legacy_remote(root,transport=transport)


def test_remote_legacy_adoption_refuses_changed_public_marker(release,tmp_path,monkeypatch):
    transport,before,_,_,_=release
    historical='f'*64
    monkeypatch.setattr(runner,'LEGACY_PUBLIC_SNAPSHOT',historical)
    monkeypatch.setattr(runner,'LEGACY_CONTENT_SNAPSHOT',digest(canonical(pub.descriptor(before))))
    base=tmp_path/'base';base.mkdir()
    for name,raw in before.items():
        path=base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    marker=tmp_path/'marker.json'
    marker.write_bytes(canonical(parse(before['version.json'])|{'snapshot_id':historical}))
    state=tmp_path/'state';checkpoint(state,before)
    root=tmp_path/'static';root.mkdir()
    runner.prepare_legacy_bootstrap(root,base,marker,state)
    with pytest.raises(ValueError,match='legacy_public_marker_changed'):
        runner.adopt_legacy_remote(root,transport=transport)
    assert transport.private+'/current.json' not in transport.ftp.files
    assert not (root/'current.json').exists()
