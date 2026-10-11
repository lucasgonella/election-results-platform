"""No network/TSE/database. Real PHP engine, synthetic 137-target fixtures."""
import hashlib
import hmac
import json
from pathlib import Path
import shutil
import subprocess
import socket
import ftplib
import pytest

from collector.src.ftp_delivery import canonical, freeze, publish, upload
from collector.src.ftp_live_runner import acknowledge

KEY = b'k' * 32
HELPER = Path(__file__).resolve().parents[1] / 'deploy/locaweb/ftp-publication.php'
UFS = 'ac al ap am ba ce df es go ma mt ms mg pa pb pr pe pi rj rn rs ro rr sc sp se to'.split()


def targets():
    values = [(u, 1, 'president') for u in UFS + ['br','zz']]
    for u in UFS:
        values += [(u, c, s) for c, s in [(3,'governor'),(5,'senator'),(6,'federal-deputy')]]
        values.append((u, 8 if u == 'df' else 7, 'district-deputy' if u == 'df' else 'state-deputy'))
    return values


def dataset(root, generation=1, delta=False):
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    for index, (scope, office, slug) in enumerate(targets()):
        changed = not delta or index == 0
        source = generation if changed else 1
        stamp = f'2026-10-09T12:00:{source:02d}+00:00'
        payload = {'schema_version':1, 'environment':'fixture', 'scope':{'code':scope}, 'office':{'code':office},
                   'election':{'code':1, 'round':1}, 'snapshot':{'generated_at':stamp,'tse_idg':str(source),'captured_at':stamp},
                   'candidate_count':1, 'candidates':[{'votes': source}]}
        path = f'{scope}/{slug}.json'
        if changed:
            (root / scope).mkdir(exist_ok=True)
            (root / path).write_bytes(canonical(payload))
        entries.append({'path':path,'scope':scope,'office':office,'election_code':1,'round':1,'tse_idg':str(source),'captured_at':stamp,'candidate_count':1})
    meta = {'environment':'fixture','generated_at':f'2026-10-09T13:00:{generation:02d}+00:00'}
    (root/'manifest.json').write_bytes(canonical(meta | {'results':entries}))
    (root/'version.json').write_bytes(canonical(meta))
    (root/'alerts.json').write_bytes(canonical(meta | {'alerts':[]}))
    return root


@pytest.fixture
def env(tmp_path):
    if not shutil.which('php'):
        pytest.fail('PHP CLI required for FTP publication tests')
    for directory in ['public/data','private','inbox','spool']:
        (tmp_path/directory).mkdir(parents=True)
    config = {'site':str(tmp_path/'public/data'),'public_root':str(tmp_path/'public'),
              'private':str(tmp_path/'private'),'inbox':str(tmp_path/'inbox'),'key':KEY.hex(),'enabled':True,'environment':'fixture','round':1,'activation_host':socket.gethostname()}
    return tmp_path, config


def call(config, action, delivery, fault=False):
    request = dict(config, fault_before_activation=fault)
    script = 'require $argv[1]; $c=json_decode($argv[2],true); $c["key"]=hex2bin($c["key"]); try {echo json_encode(fp_run($c,$argv[3],$argv[4]));} catch(Throwable $e) {echo json_encode(["error"=>$e->getMessage()]);}'
    result = subprocess.run(['php','-r',script,str(HELPER),json.dumps(request),action,delivery],capture_output=True,text=True,check=True)
    return json.loads(result.stdout)


def deliver(env, generation=1, baseline=None, delta=False):
    root, cfg = env
    stage = dataset(root/f'stage-{generation}', generation, delta)
    frozen = freeze(stage, root/'spool', KEY, baseline)
    shutil.copytree(frozen, root/'inbox'/frozen.name)
    return frozen


def test_full_incremental_idempotent_and_rollback(env):
    first = deliver(env)
    assert call(env[1],'activate',first.name)['status'] == 'published'
    second = deliver(env,2,first.name,True)
    assert call(env[1],'activate',second.name)['status'] == 'published'
    assert len(list((env[0]/'public/data/releases'/second.name).glob('*/*.json'))) == 137
    assert call(env[1],'activate',second.name) == call(env[1],'status',second.name)
    assert call(env[1],'rollback',second.name)['snapshot_id'] == first.name
    assert call(env[1],'rollback',second.name)['status'] == 'rolled_back'
    assert json.loads((env[0]/'public/data/version.json').read_text())['snapshot_id'] == first.name


@pytest.mark.parametrize('kind',['partial','hash','signature','missing_ready'])
def test_reject_corrupt_transfer(env,kind):
    delivery = deliver(env)
    inbox = env[0]/'inbox'/delivery.name
    if kind == 'partial': (inbox/'files/ac/president.json').write_bytes(b'{')
    if kind == 'hash': (inbox/'files/ac/president.json').write_bytes(b'x'*len((inbox/'files/ac/president.json').read_bytes()))
    if kind == 'signature': (inbox/'delivery.sig').write_text('0'*64)
    if kind == 'missing_ready': (inbox/'READY').unlink()
    assert 'error' in call(env[1],'activate',delivery.name)
    assert not (env[0]/'public/data/version.json').exists()


def test_missing_baseline(env):
    delivery = deliver(env,2,None,True)
    assert call(env[1],'activate',delivery.name)['error'] == 'baseline_absent'


@pytest.mark.parametrize('corrupt',['missing','hash','inventory'])
def test_corrupt_baseline_preserves_marker(env,corrupt):
    first=deliver(env); call(env[1],'activate',first.name)
    second=deliver(env,2,first.name,True)
    base=env[0]/'public/data/releases'/first.name
    if corrupt=='missing': (base/'ac/president.json').unlink()
    elif corrupt=='hash': (base/'ac/president.json').write_text('{}')
    else: (base/'inventory.sig').write_text('0'*64)
    assert 'error' in call(env[1],'activate',second.name)
    assert json.loads((env[0]/'public/data/version.json').read_text())['snapshot_id']==first.name


def test_failure_before_activation_and_retry(env):
    first=deliver(env); call(env[1],'activate',first.name)
    second=deliver(env,2,first.name,True)
    assert call(env[1],'activate',second.name,True)['error']=='injected_before_activation'
    assert json.loads((env[0]/'public/data/version.json').read_text())['snapshot_id']==first.name
    assert call(env[1],'activate',second.name)['status']=='published'


def test_regression_after_rollback(env):
    first=deliver(env); call(env[1],'activate',first.name)
    second=deliver(env,3,first.name,True); call(env[1],'activate',second.name)
    call(env[1],'rollback',second.name)
    older=deliver(env,2,first.name,True)
    assert call(env[1],'activate',older.name)['error']=='result_regression'


def test_concurrent_activations(env):
    first=deliver(env); second=deliver(env,2)
    cfg=env[1]
    script='require $argv[1]; $c=json_decode($argv[2],true); $c["key"]=hex2bin($c["key"]); try {echo json_encode(fp_run($c,"activate",$argv[3]));} catch(Throwable $e) {echo json_encode(["error"=>$e->getMessage()]);}'
    processes=[subprocess.Popen(['php','-r',script,str(HELPER),json.dumps(cfg),d.name],stdout=subprocess.PIPE,text=True) for d in [first,second]]
    results=[json.loads(p.communicate()[0]) for p in processes]
    assert sum(r.get('status')=='published' for r in results)==1
    assert any(r.get('error') in {'publication_busy','baseline_conflict'} for r in results)


def test_lost_response_reconciles(env):
    delivery=deliver(env)
    class Control:
        def request(self,action,id):
            response=call(env[1],action,id)
            if action=='activate': raise TimeoutError()
            return response
    transferred=[]
    assert publish(delivery,Control(),lambda:transferred.append(1))['status']=='published'
    assert publish(delivery,Control(),lambda:transferred.append(1))['status']=='published'
    assert transferred==[1]


def test_state_ack_recovery(tmp_path):
    queue=tmp_path/'ftp-queue'; queue.mkdir()
    (tmp_path/'state').mkdir(); (tmp_path/'state/old').write_text('old')
    (queue/'state-abc').mkdir(); (queue/'state-abc/new').write_text('new')
    job={'id':'abc','receipt':{'snapshot_id':'abc'}}
    (queue/'current.json').write_text(json.dumps(job))
    (tmp_path/'state').replace(queue/'previous-abc')  # crash between renames
    acknowledge(tmp_path,job)
    assert (tmp_path/'state/new').read_text()=='new'
    assert (queue/'previous-abc/old').exists()


def test_ftp_failure_never_marks_ready(tmp_path):
    delivery=freeze(dataset(tmp_path/'stage'),tmp_path/'spool',KEY,None)
    sent=[]
    class BrokenFTP:
        def sendcmd(self,command): raise ftplib.error_perm('550 unavailable')
        def connect(self,host,port,timeout): assert port==21
        def login(self,*args): pass
        def set_pasv(self,value): pass
        def mkd(self,path): pass
        def storbinary(self,command,stream): sent.append(command); raise OSError('fixture')
        def close(self): pass
    with pytest.raises(OSError): upload(delivery,'private/inbox','fixture','user','fixture',BrokenFTP)
    assert not any('READY' in name for name in sent)


def test_ftp_roundtrip_and_completion_last(tmp_path):
    delivery=freeze(dataset(tmp_path/'stage'),tmp_path/'spool',KEY,None)
    stored={}; renamed=[]
    class FTP:
        def sendcmd(self,command): raise ftplib.error_perm('550 unavailable')
        def connect(self,host,port,timeout): assert port==21
        def login(self,*args): pass
        def set_pasv(self,value): assert value is True
        def mkd(self,path): pass
        def storbinary(self,command,stream): stored[command[5:]]=stream.read()
        def retrbinary(self,command,callback): callback(stored[command[5:]])
        def rename(self,source,target): stored[target]=stored.pop(source); renamed.append(target)
        def close(self): pass
    upload(delivery,'private/inbox','fixture','user','fixture',FTP)
    assert renamed[-1].endswith('/READY')
    assert not any('/version.json' == name for name in renamed)
    assert all(name.startswith('private/inbox/'+delivery.name+'/') for name in renamed)
    # Retrying exactly the same delivery preserves bytes and ID.
    original=dict(stored)
    upload(delivery,'private/inbox','fixture','user','fixture',FTP)
    assert stored==original


@pytest.mark.parametrize('kind',['identity','duplicate','incomplete','wrong_environment'])
def test_signed_inconsistent_payload_is_rejected(env,kind):
    root,cfg=env
    stage=dataset(root/'bad-stage')
    if kind=='identity':
        payload=json.loads((stage/'ac/president.json').read_text()); payload['office']['code']=3
        (stage/'ac/president.json').write_bytes(canonical(payload))
    elif kind=='wrong_environment':
        payload=json.loads((stage/'ac/president.json').read_text()); payload['environment']='production'
        (stage/'ac/president.json').write_bytes(canonical(payload))
    else:
        manifest=json.loads((stage/'manifest.json').read_text())
        if kind=='duplicate': manifest['results'][-1]=manifest['results'][0]
        else: manifest['results'].pop()
        (stage/'manifest.json').write_bytes(canonical(manifest))
    delivery=freeze(stage,root/'spool',KEY,None)
    shutil.copytree(delivery,root/'inbox'/delivery.name)
    assert 'error' in call(cfg,'activate',delivery.name)
    assert not (root/'public/data/version.json').exists()


def test_correction_can_reduce_votes(env):
    first=deliver(env); call(env[1],'activate',first.name)
    root,cfg=env
    stage=dataset(root/'correction',2,True)
    payload=json.loads((stage/'ac/president.json').read_text()); payload['candidates'][0]['votes']=0
    (stage/'ac/president.json').write_bytes(canonical(payload))
    delivery=freeze(stage,root/'spool',KEY,first.name)
    shutil.copytree(delivery,root/'inbox'/delivery.name)
    assert call(cfg,'activate',delivery.name)['status']=='published'


def test_marker_without_receipt_is_reconciled(env):
    first=deliver(env); call(env[1],'activate',first.name)
    (env[0]/'private/receipts'/f'{first.name}.json').unlink()
    assert call(env[1],'status',first.name)['status']=='published'
    assert call(env[1],'activate',first.name)['status']=='published'


def test_control_contains_no_result_bytes(monkeypatch):
    from collector.src.ftp_delivery import Control
    import urllib.request
    captured=[]
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self): return b'{"status":"unknown"}'
    class Opener:
        def open(self,request,timeout): captured.append(request); return Response()
    monkeypatch.setattr(urllib.request,'build_opener',lambda *args:Opener())
    Control('https://fixture.invalid/control',KEY).request('status','a'*64)
    request=captured[0]
    assert json.loads(request.data)=={'action':'status','delivery_id':'a'*64}
    headers={k.lower():v for k,v in request.headers.items()}
    signed=(headers['x-timestamp']+'\n'+headers['x-nonce']+'\n').encode()+request.data
    assert headers['x-signature']==hmac.new(KEY,signed,'sha256').hexdigest()


def test_rollback_refuses_corrupt_previous_release(env):
    first=deliver(env); call(env[1],'activate',first.name)
    second=deliver(env,2,first.name,True); call(env[1],'activate',second.name)
    (env[0]/'public/data/releases'/first.name/'ac/president.json').write_text('{}')
    assert 'error' in call(env[1],'rollback',second.name)
    assert json.loads((env[0]/'public/data/version.json').read_text())['snapshot_id']==second.name


def test_public_inbox_configuration_is_rejected(env):
    root,cfg=env
    unsafe=root/'public/inbox'; unsafe.mkdir()
    cfg=dict(cfg,inbox=str(unsafe))
    assert call(cfg,'status','a'*64)['error']=='private_storage_required'


def test_disabled_activation(env):
    delivery=deliver(env)
    assert call(dict(env[1],enabled=False),'activate',delivery.name)['error']=='activation_disabled'
    assert not (env[0]/'public/data/version.json').exists()
