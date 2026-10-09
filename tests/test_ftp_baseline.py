import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import pytest

from collector.src.ftp_baseline import adopt
from collector.src.ftp_delivery import canonical
from test_ftp_publication import env, KEY, dataset, deliver, call

PREPARE=Path(__file__).resolve().parents[1]/'deploy/locaweb/prepare-ftp-baseline.php'


@pytest.fixture
def legacy(env):
    root,cfg=env
    sid='a'*64
    release=dataset(root/'public/data/releases'/sid)
    marker=json.loads((release/'version.json').read_text())|{'snapshot_id':sid}
    (root/'public/data/version.json').write_bytes(canonical(marker))
    state=root/'live/state'; state.mkdir(parents=True)
    for name in ['manifest.json','version.json','alerts.json']:
        shutil.copyfile(release/name,state/name)
    entries=json.loads((state/'manifest.json').read_text())['results']
    targets={'https://fixture.invalid/'+e['path']:{'path':e['path'],'tse_idg':e['tse_idg'],'etag':'fixture'} for e in entries}
    (state/'target-state.json').write_bytes(canonical(targets))
    (state/'state-meta.json').write_text('{"seat_allocation_version":1,"result_alert_version":3}')
    (root/'live/pending').mkdir(); (root/'live/pending/preserved').write_text('not published')
    return env


def prepare(legacy, output='adoption'):
    root,cfg=legacy
    destination=root/output
    script='require $argv[1]; $c=json_decode($argv[2],true); try {$p=fp_baseline_plan($c,$argv[3]); fp_emit_baseline_plan($p,hex2bin($argv[4]),$argv[5]); echo json_encode(["status"=>"prepared"]);} catch(Throwable $e) {echo json_encode(["error"=>$e->getMessage()]);}'
    result=subprocess.run(['php','-r',script,str(PREPARE),json.dumps(cfg),str(root/'live/state'),KEY.hex(),str(destination)],capture_output=True,text=True,check=True)
    return json.loads(result.stdout),destination


def hashes(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def test_adoption_preserves_release_and_state_then_delta_and_rollback(legacy):
    root,cfg=legacy
    before=hashes(root/'public'); state_before=hashes(root/'live/state')
    result,plan=prepare(legacy); assert result['status']=='prepared'
    assert hashes(root/'public')==before
    # Supervised installation simulation in this fixture's private area only.
    certificate=root/'private/adopted-baselines'/('a'*64); certificate.mkdir(parents=True)
    for name in ['inventory.json','inventory.sig']: shutil.copyfile(plan/name,certificate/name)
    shutil.copyfile(plan/'watermarks.json',root/'private/watermarks.json')
    assert adopt(root/'live',plan,root/'public/data/version.json',KEY)['status']=='baseline_adopted'
    assert adopt(root/'live',plan,root/'public/data/version.json',KEY)['status']=='baseline_adopted'
    assert hashes(root/'live/state')==state_before
    assert (root/'live/pending/preserved').exists()
    assert hashes(root/'public')==before
    delta=deliver(legacy,2,'a'*64,True)
    assert call(cfg,'activate',delta.name)['status']=='published'
    assert call(cfg,'rollback',delta.name)['snapshot_id']=='a'*64
    assert hashes(root/'public/data/releases'/('a'*64))=={k.split('data/releases/'+('a'*64)+'/',1)[1]:v for k,v in before.items() if k.startswith('data/releases/'+('a'*64)+'/')}
    assert json.loads((root/'private/watermarks.json').read_text())['ac/president.json']['time']>json.loads((plan/'watermarks.json').read_text())['ac/president.json']['time']


@pytest.mark.parametrize('kind',['state','marker','signature','in_flight'])
def test_adoption_rejects_changed_checkpoint(legacy,kind):
    root,cfg=legacy
    result,plan=prepare(legacy); assert result['status']=='prepared'
    if kind=='state': (root/'live/state/state-meta.json').write_text('{}')
    if kind=='marker': (root/'public/data/version.json').write_text('{}')
    if kind=='signature': (plan/'plan.sig').write_text('0'*64)
    if kind=='in_flight':
        (root/'live/ftp-queue').mkdir(); (root/'live/ftp-queue/current.json').write_text('{}')
    before=hashes(root/'live/state')
    with pytest.raises(ValueError): adopt(root/'live',plan,root/'public/data/version.json',KEY)
    assert hashes(root/'live/state')==before
    assert not (root/'live/ftp-queue/confirmed.json').exists()


def test_plan_rejects_pending_as_baseline(legacy):
    root,cfg=legacy
    target=root/'live/state/target-state.json'; data=json.loads(target.read_text())
    data[next(iter(data))]['tse_idg']='new-unpublished-id'
    target.write_bytes(canonical(data))
    result,plan=prepare(legacy)
    assert result['error']=='state_mismatch'
    assert not plan.exists()


def test_adopted_inventory_cannot_hide_corrupt_release(legacy):
    root,cfg=legacy
    _,plan=prepare(legacy)
    destination=root/'private/adopted-baselines'/('a'*64); destination.mkdir(parents=True)
    for name in ['inventory.json','inventory.sig']: shutil.copyfile(plan/name,destination/name)
    (root/'public/data/releases'/('a'*64)/'ac/president.json').write_text('{}')
    delta=deliver(legacy,2,'a'*64,True)
    assert 'error' in call(cfg,'activate',delta.name)
    assert json.loads((root/'public/data/version.json').read_text())['snapshot_id']=='a'*64


def test_new_publisher_respects_existing_official_lock(env):
    root,cfg=env
    lock=root/'private/official-publish.lock'
    process=subprocess.Popen(['php','-r','$s=fopen($argv[1],"c"); flock($s,LOCK_EX); echo "ready\n"; flush(); sleep(20);',str(lock)],stdout=subprocess.PIPE,text=True)
    try:
        assert process.stdout.readline().strip()=='ready'
        delivery=deliver(env)
        assert call(dict(cfg,legacy_lock=str(lock)),'activate',delivery.name)['error']=='publication_busy'
        assert not (root/'public/data/version.json').exists()
    finally: process.terminate(); process.wait()


def test_real_numeric_idg_representation_is_supported(legacy):
    root,cfg=legacy
    release=root/'public/data/releases'/('a'*64)
    manifest=json.loads((release/'manifest.json').read_text())
    for entry in manifest['results']:
        entry['tse_idg']=1
        path=release/entry['path']; payload=json.loads(path.read_text()); payload['snapshot']['tse_idg']=1
        path.write_bytes(canonical(payload))
    (release/'manifest.json').write_bytes(canonical(manifest))
    (root/'live/state/manifest.json').write_bytes(canonical(manifest))
    target=root/'live/state/target-state.json'; values=json.loads(target.read_text())
    for value in values.values(): value['tse_idg']=1
    target.write_bytes(canonical(values))
    result,plan=prepare(legacy)
    assert result['status']=='prepared'
    assert {v['idg'] for v in json.loads((plan/'watermarks.json').read_text()).values()}=={'1'}


def test_newer_generation_cannot_silently_reopen_finalized_result(env):
    from collector.src.ftp_delivery import freeze
    root,cfg=env
    first_stage=dataset(root/'finalized')
    payload=json.loads((first_stage/'ac/president.json').read_text()); payload['snapshot']['totalization_final']=True
    (first_stage/'ac/president.json').write_bytes(canonical(payload))
    first=freeze(first_stage,root/'spool',KEY,None); shutil.copytree(first,root/'inbox'/first.name)
    assert call(cfg,'activate',first.name)['status']=='published'
    second_stage=dataset(root/'reopened',2,True)
    payload=json.loads((second_stage/'ac/president.json').read_text()); payload['snapshot']['totalization_final']=False
    (second_stage/'ac/president.json').write_bytes(canonical(payload))
    second=freeze(second_stage,root/'spool',KEY,first.name); shutil.copytree(second,root/'inbox'/second.name)
    assert call(cfg,'activate',second.name)['error']=='totalization_reopened_requires_review'
    assert json.loads((root/'public/data/version.json').read_text())['snapshot_id']==first.name


def test_fingerprint_ignores_key_order_capture_and_numeric_idg_representation():
    helper=PREPARE.parent/'ftp-publication.php'
    script='require $argv[1]; $a=["snapshot"=>["tse_idg"=>1,"generated_at"=>"same","captured_at"=>"old"],"candidates"=>[["votes"=>1,"name"=>"fixture"]],"office"=>["code"=>1,"name"=>"office"]]; $b=["office"=>["name"=>"office","code"=>1],"candidates"=>[["name"=>"fixture","votes"=>1]],"snapshot"=>["captured_at"=>"new","generated_at"=>"same","tse_idg"=>"1"]]; echo json_encode(fp_source_fingerprint($a)===fp_source_fingerprint($b));'
    result=subprocess.run(['php','-r',script,str(helper)],capture_output=True,text=True,check=True)
    assert json.loads(result.stdout) is True
