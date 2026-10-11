"""Synthetic recovery; no TSE, production, database or remote connections."""
import io
import json
from pathlib import Path
import pytest

from collector.src.ftp_delivery import canonical, freeze
from collector.src.ftp_live_runner import acknowledge
from collector.src.ftp_recovery import META, assert_recovery_resolved, digest, hashes, parse, prepare, queue, targets, tree, verify, verify_public


def bundle(root, generation, changed=None):
    root.mkdir()
    rows=[]
    for name,(scope,office) in targets().items():
        source=generation if changed is None or name in changed else 1
        time=f'2026-10-09T12:00:0{source}+00:00'
        candidate={'tse_candidate_seq':100+office,'votes':source,'vote_percentage':100.0,
                   'result_status':'Não eleito','elected':False,'name':'Fixture','ballot_name':'Fixture'}
        payload={'schema_version':1,'environment':'fixture','scope':{'code':scope,'type':'uf','uf':scope.upper()},
                 'office':{'code':office,'name':'Fixture'},'election':{'code':1,'round':1},
                 'snapshot':{'generated_at':time,'captured_at':time,'tse_idg':source,'totalization_final':True},
                 'candidate_count':1,'candidates':[candidate]}
        row={'path':name,'scope':scope,'office':office,'election_code':1,'round':1,
             'tse_idg':source,'captured_at':time,'candidate_count':1}
        rows.append(row)
        if changed is None or name in changed:
            path=root/name;path.parent.mkdir(exist_ok=True);path.write_bytes(canonical(payload))
    meta={'schema_version':1,'environment':'fixture','generated_at':f'2026-10-09T13:00:0{generation}+00:00'}
    (root/'version.json').write_bytes(canonical(meta))
    (root/'manifest.json').write_bytes(canonical(meta|{'result_count':137,'candidate_count':137,'results':rows}))
    (root/'alerts.json').write_bytes(canonical(meta|{'alerts':[]}))


@pytest.fixture
def recovery(tmp_path):
    baseline=tmp_path/'baseline';stage=tmp_path/'stage';state=tmp_path/'state';pending=tmp_path/'pending'
    bundle(baseline,1);bundle(stage,2,{'rj/governor.json','am/governor.json'})
    for destination,origin in [(state,baseline),(pending,stage)]:
        destination.mkdir()
        for name in META:(destination/name).write_bytes((origin/name).read_bytes())
        rows=parse((origin/'manifest.json').read_bytes())['results']
        (destination/'target-state.json').write_bytes(canonical({'https://fixture.invalid/'+row['path']:{'path':row['path'],'tse_idg':row['tse_idg']} for row in rows}))
        (destination/'state-meta.json').write_bytes(canonical({'result_alert_version':3}))
    marker=tmp_path/'marker.json';marker.write_bytes(canonical(parse((baseline/'version.json').read_bytes())|{'snapshot_id':'a'*64}))
    return {'baseline':baseline,'marker':marker,'stage':stage,'state':state,'pending':pending,
            'output':tmp_path/'package','include':['rj/governor.json']}


def change(path, function):
    value=parse(path.read_bytes());function(value);path.write_bytes(canonical(value))


def test_complete_recovery_preserves_am_and_confirms_only_rj(recovery):
    original={name:tree(recovery[name]) for name in ['baseline','stage','state','pending']}
    plan=prepare(**recovery);package=recovery['output'];verify(package)
    assert len(tree(package/'candidate'))==140
    assert (package/'candidate/am/governor.json').read_bytes()==original['baseline']['am/governor.json']
    assert (package/'candidate/rj/governor.json').read_bytes()==original['stage']['rj/governor.json']
    assert plan['retained_stage_targets']==['am/governor.json']
    cache=parse((package/'checkpoint/target-state.json').read_bytes())
    assert cache['https://fixture.invalid/am/governor.json']['tse_idg']==1
    assert cache['https://fixture.invalid/rj/governor.json']['tse_idg']==2
    assert all(tree(recovery[name])==original[name] for name in original)


@pytest.mark.parametrize('kind,code',[
    ('duplicate','invalid_manifest'),('traversal','invalid_manifest'),('missing','incomplete_release'),
    ('extra','incomplete_release'),('identity','invalid_result_identity'),('idg','invalid_source_id'),
    ('negative_votes','invalid_candidate_result'),('percentage','invalid_candidate_percentage'),
    ('status','inconsistent_candidate_status'),('generation','result_regression'),
    ('reopened','totalization_reopened_requires_review'),('same_generation','result_regression'),
    ('revoke','elected_revocation_requires_review'),('meta','metadata_mismatch'),
    ('pending','pending_stage_mismatch'),('schema','checkpoint_schema_requires_review'),
    ('marker','baseline_marker_mismatch'),('aggregate','aggregate_candidate_count_mismatch'),
    ('duplicate_key','duplicate_json_key'),('source_symlink','symlink')])
def test_reject_invalid_recovery_without_output(recovery,kind,code):
    base=recovery['baseline'];stage=recovery['stage'];result=stage/'rj/governor.json'
    if kind=='duplicate':change(base/'manifest.json',lambda v:v['results'].__setitem__(1,v['results'][0]))
    elif kind=='traversal':change(base/'manifest.json',lambda v:v['results'][0].__setitem__('path','../governor.json'))
    elif kind=='missing':(base/'ac/president.json').unlink()
    elif kind=='extra':(base/'extra.json').write_text('{}')
    elif kind=='identity':change(result,lambda v:v['election'].__setitem__('code',2))
    elif kind=='idg':change(base/'ac/president.json',lambda v:v['snapshot'].__setitem__('tse_idg',-1));change(base/'manifest.json',lambda v:v['results'][0].__setitem__('tse_idg',-1))
    elif kind=='negative_votes':change(result,lambda v:v['candidates'][0].__setitem__('votes',-1))
    elif kind=='percentage':change(result,lambda v:v['candidates'][0].__setitem__('vote_percentage',101))
    elif kind=='status':change(result,lambda v:v['candidates'][0].__setitem__('result_status','Eleito'))
    elif kind=='generation':change(result,lambda v:v['snapshot'].__setitem__('generated_at','2026-10-08T12:00:00+00:00'))
    elif kind=='same_generation':change(result,lambda v:v['snapshot'].__setitem__('generated_at','2026-10-09T12:00:01+00:00'))
    elif kind=='reopened':change(result,lambda v:v['snapshot'].__setitem__('totalization_final',False))
    elif kind=='revoke':change(base/'rj/governor.json',lambda v:v['candidates'][0].update(elected=True,result_status='Eleito'))
    elif kind=='meta':change(stage/'alerts.json',lambda v:v.__setitem__('environment','wrong'))
    elif kind=='pending':change(recovery['pending']/'manifest.json',lambda v:v['results'][0].__setitem__('tse_idg',999))
    elif kind=='schema':change(recovery['pending']/'state-meta.json',lambda v:v.__setitem__('result_alert_version',4))
    elif kind=='marker':change(recovery['marker'],lambda v:v.__setitem__('generated_at','2026-10-09T14:00:00+00:00'))
    elif kind=='aggregate':change(base/'manifest.json',lambda v:v.__setitem__('candidate_count',136))
    elif kind=='duplicate_key':(stage/'version.json').write_text('{"environment":"fixture","environment":"oficial"}')
    elif kind=='source_symlink':
        if __import__('os').name=='nt':pytest.skip('symlinks tested on Linux CI')
        result.unlink();result.symlink_to(base/'rj/governor.json')
    with pytest.raises(ValueError,match=code):prepare(**recovery)
    assert not recovery['output'].exists()


def test_am_selection_stays_blocked_and_retained(recovery):
    recovery['include']=['am/governor.json']
    with pytest.raises(ValueError,match='amazonas_requires_review'):prepare(**recovery)
    assert not recovery['output'].exists()


def test_second_round_to_elected_with_removed_candidate_is_explicit_review(recovery):
    base=recovery['baseline'];stage=recovery['stage']
    change(base/'rj/governor.json',lambda v:v['candidates'][0].update(elected=True,result_status='2º turno'))
    change(stage/'rj/governor.json',lambda v:v['candidates'][0].update(elected=True,result_status='Eleito'))
    def add(v):
        v['candidates'].append(v['candidates'][0]|{'tse_candidate_seq':999,'votes':4,'elected':False,'result_status':'Não eleito','candidate_status':'Anulado sub judice'})
        v['candidate_count']=2
    change(base/'rj/governor.json',add)
    change(base/'manifest.json',lambda v:[v.__setitem__('candidate_count',138),next(r for r in v['results'] if r['path']=='rj/governor.json').__setitem__('candidate_count',2)])
    (recovery['state']/'manifest.json').write_bytes((base/'manifest.json').read_bytes())
    plan=prepare(**recovery)
    assert plan['candidate_review_required']==['rj/governor.json']
    assert {x['kind'] for x in plan['candidate_transitions']['rj/governor.json']}=={'status','removed'}
    alerts=parse((recovery['output']/'candidate/alerts.json').read_bytes())['alerts']
    assert any(alert['kind']=='elected' and alert['scope']=='rj' for alert in alerts)


def test_package_tampering_rejected(recovery):
    prepare(**recovery);(recovery['output']/'candidate/rj/governor.json').write_text('{}')
    with pytest.raises(ValueError,match='recovery_package_changed'):verify(recovery['output'])


def test_queue_gate_precedes_any_live_write(recovery,monkeypatch):
    monkeypatch.delenv('ELECTION_FTP_CUTOVER_APPROVED',raising=False)
    live=recovery['output']/'never-created'
    with pytest.raises(ValueError,match='cutover_not_approved'):queue(live,recovery['output'],'0'*64)
    assert not live.exists()


def test_queue_and_ack_do_not_commit_whole_pending(recovery,monkeypatch,tmp_path):
    import shutil
    prepare(**recovery);package=recovery['output'];live=tmp_path/'live';live.mkdir()
    for name in ['state','pending','stage']:shutil.copytree(recovery[name],live/name)
    queue_root=live/'ftp-queue';queue_root.mkdir();(queue_root/'confirmed.json').write_bytes(canonical({'snapshot_id':'a'*64}))
    original_pending=tree(live/'pending');original_stage=tree(live/'stage')
    key=tmp_path/'fixture.key';key.write_text('ab'*32)
    monkeypatch.setattr('collector.src.ftp_safety.validate_runner_environment',lambda env:None)
    monkeypatch.setenv('LIVE_PUBLISH_STATE_DIR',str(live));monkeypatch.setenv('ELECTION_HMAC_KEY_FILE',str(key))
    with pytest.raises(ValueError,match='specific_recovery_plan_review_required'):queue(live,package,'0'*64)
    queued=queue(live,package,digest((package/'recovery-plan.json').read_bytes()))
    with pytest.raises(ValueError,match='delivery_in_flight'):queue(live,package,digest((package/'recovery-plan.json').read_bytes()))
    job=parse((queue_root/'current.json').read_bytes());job['receipt']={'snapshot_id':queued['delivery_id']}
    acknowledge(live,job)
    assert tree(live/'state')==tree(package/'checkpoint')
    assert tree(live/'pending')==original_pending and tree(live/'stage')==original_stage
    assert parse((live/'state/target-state.json').read_bytes())['https://fixture.invalid/am/governor.json']['tse_idg']==1
    with pytest.raises(ValueError,match='recovery_residual_targets_require_review'):assert_recovery_resolved(queue_root)
    assert parse((queue_root/'recovery-hold.json').read_bytes())['retained_stage_targets']==['am/governor.json']


class Response(io.BytesIO):
    status=200
    def __init__(self,raw,url):super().__init__(raw);self.url=url
    def geturl(self):return self.url


class PublicFixture:
    def __init__(self,delivery,kind=None):self.delivery=delivery;self.kind=kind;self.requests=[];self.markers=0
    def open(self,request,timeout):
        from urllib.parse import urlsplit
        self.requests.append(request);path=urlsplit(request.full_url).path
        assert request.method=='GET' and not any('signature' in key.casefold() for key in request.headers)
        if path=='/data/version.json':
            self.markers+=1;marker={'snapshot_id':self.delivery.name,'delivery_id':self.delivery.name}
            if self.kind=='wrong_marker' or (self.kind=='changed_marker' and self.markers==2):marker['snapshot_id']='b'*64
            raw=canonical(marker)
        else:
            relative=path.split('/'+self.delivery.name+'/',1)[1];raw=(self.delivery/'files'/relative).read_bytes()
            if self.kind=='corrupt' and relative=='rj/governor.json':raw=b'{}'
        response=Response(raw,request.full_url)
        if self.kind=='redirect':response.url='https://elsewhere.invalid/data/version.json'
        if self.kind=='unexpected_status':response.status=201
        return response


@pytest.mark.parametrize('kind,code',[(None,None),('corrupt','public_checksum_mismatch'),('wrong_marker','public_selection_mismatch'),
                                     ('changed_marker','public_selection_changed'),('redirect','unexpected_public_response'),('unexpected_status','unexpected_public_response')])
def test_full_public_verification(recovery,tmp_path,kind,code):
    prepare(**recovery);delivery=freeze(recovery['output']/'candidate',tmp_path/'spool',b'x'*32,'a'*64)
    receipt={'status':'published','snapshot_id':delivery.name,'delivery_id':delivery.name};web=PublicFixture(delivery,kind)
    if code:
        with pytest.raises(ValueError,match=code):verify_public(delivery,'https://fixture.invalid/api/election-ftp-control.php',receipt,web)
    else:
        assert verify_public(delivery,'https://fixture.invalid/api/election-ftp-control.php',receipt,web)['files']==140
        assert len(web.requests)==142
