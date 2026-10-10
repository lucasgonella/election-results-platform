"""Disposable files and PHP CLI only; no provider/TSE/database access."""
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
CLIENT=ROOT/'deploy/scripts/ftp-staging-exercise.php'

def php(code,*args):
    if not shutil.which('php'):pytest.fail('PHP CLI required')
    return subprocess.run(['php','-r',code,*map(str,args)],capture_output=True,text=True)

def library(code,*args):
    return php("define('FTP_STAGING_CLIENT_LIBRARY',true);require $argv[1];"+code,CLIENT,*args)

def route(tmp_path):
    private=tmp_path/'ftp-staging-pr75/private';private.mkdir(parents=True)
    public=tmp_path/'public_html/eleicoes/__staging_pr75';public.mkdir(parents=True)
    shutil.copyfile(ROOT/'deploy/locaweb/ftp-staging-probe.php',public/'probe.php')
    shutil.copyfile(ROOT/'deploy/locaweb/ftp-publication.php',private/'ftp-publication.php')
    (public/'probe-marker.json').write_bytes(b'{"fixture":"replace_a"}\n')
    cfg={'fixture_only':True,'environment':'fixture','root':str(private.parent.resolve()),'public_root':str(public.resolve()),
         'fixture_key':'ab'*32,'allowed_actions':['runtime','read','lock','replace_a','replace_b'],'activation_host':socket.gethostname()}
    (private/'staging-config.json').write_text(json.dumps(cfg))
    return private,public,cfg

def call(public,action):
    return subprocess.run(['php',str(public/'probe.php'),action],capture_output=True,text=True)

def test_key_free_template_restores_exact_pretty_config_bytes(tmp_path):
    raw=json.dumps({'fixture_key':'ab'*32,'allowed_actions':['runtime','read'],'activation_host':''},indent=2)+'\n'
    source=tmp_path/'config';source.write_text(raw)
    result=library("$raw=file_get_contents($argv[2]);$t=fx_template($raw,str_repeat('ab',32));echo json_encode(['template'=>$t,'exact'=>fx_rebuild($t,str_repeat('ab',32))===$raw]);",source)
    assert result.returncode==0,result.stderr
    value=json.loads(result.stdout)
    assert value['exact'] and 'ab'*32 not in json.dumps(value['template'])

def test_atomic_failure_cleans_only_its_temporary_and_preserves_target(tmp_path):
    target=tmp_path/'target';target.mkdir();(target/'existing').write_bytes(b'original')
    result=library("try {fx_atomic($argv[2],'synthetic',0600);} catch(Throwable $e){echo $e->getMessage();}",target)
    assert result.stdout=='fixture_write_failed'
    assert sorted(p.name for p in tmp_path.iterdir())==['target']
    assert (target/'existing').read_bytes()==b'original'

def test_recovery_disables_writes_first_and_preserves_exact_original_bytes(tmp_path):
    original=json.dumps({'fixture_key':'ab'*32,'allowed_actions':['runtime','read'],'activation_host':''},indent=2)+'\n'
    config=tmp_path/'config';config.write_text(original)
    marker=tmp_path/'marker';marker.write_bytes(b'{"fixture":"replace_a"}\n')
    code="$original=file_get_contents($argv[2]);$marker=file_get_contents($argv[3]);$t=fx_template($original,str_repeat('ab',32));"
    code+="fx_atomic($argv[2],json_encode(['allowed_actions'=>FX_TEST,'activation_host'=>'fixture']),0600);fx_atomic($argv[3],'{\"fixture\":\"replace_b\"}',0644);"
    code+="try {fx_restore_pair($argv[2],$argv[3],$t,str_repeat('ab',32),$marker,static function(){fx_fail('simulated_failure');});} catch(Throwable $e) {}"
    code+="$disabled=file_get_contents($argv[2])===$original;fx_restore_pair($argv[2],$argv[3],$t,str_repeat('ab',32),$marker);echo json_encode(['disabled_before_marker'=>$disabled,'marker_exact'=>file_get_contents($argv[3])===$marker]);"
    result=library(code,config,marker)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={'disabled_before_marker':True,'marker_exact':True}
    assert config.read_text()==original and marker.read_bytes()==b'{"fixture":"replace_a"}\n'

def test_fp_write_rename_failure_does_not_leave_public_temporary(tmp_path):
    target=tmp_path/'target';target.mkdir()
    result=php("require $argv[1];try{fp_write($argv[2],['fixture'=>'replace_b']);}catch(Throwable $e){echo $e->getMessage();}",ROOT/'deploy/locaweb/ftp-publication.php',target)
    assert result.stdout=='storage_error'
    assert sorted(p.name for p in tmp_path.iterdir())==['target']

def test_wrong_host_and_symlink_are_rejected_before_writes(tmp_path):
    private,public,cfg=route(tmp_path)
    cfg['activation_host']='not-this-host';(private/'staging-config.json').write_text(json.dumps(cfg))
    marker=(public/'probe-marker.json').read_bytes()
    assert json.loads(call(public,'replace_b').stdout)['error']=='activation_host_mismatch'
    assert not (private/'probe.lock').exists()
    if not hasattr(Path,'symlink_to'):pytest.skip('symlinks unavailable')
    outside=tmp_path/'outside';outside.write_text('preserve')
    try:(private/'probe.lock').symlink_to(outside)
    except OSError:pytest.skip('symlinks unavailable')
    cfg['activation_host']=socket.gethostname();(private/'staging-config.json').write_text(json.dumps(cfg))
    assert json.loads(call(public,'replace_b').stdout)['error']=='fixture_namespace_required'
    assert outside.read_text()=='preserve' and (public/'probe-marker.json').read_bytes()==marker

def test_replacements_share_lock_and_read_reports_exact_marker_hash(tmp_path):
    private,public,cfg=route(tmp_path)
    result=call(public,'replace_b');assert result.returncode==0,result.stderr
    raw=(public/'probe-marker.json').read_bytes()
    read=json.loads(call(public,'read').stdout)
    assert read['marker_sha256']==hashlib.sha256(raw).hexdigest() and read['marker_bytes']==len(raw)
    assert (private/'probe.lock').stat().st_mode&0o777==0o600
    code="$h=fopen($argv[1],'r+');flock($h,LOCK_EX);echo 'ready';fflush(STDOUT);fgets(STDIN);"
    holder=subprocess.Popen(['php','-r',code,str(private/'probe.lock')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        assert holder.stdout.read(5)==b'ready'
        assert json.loads(call(public,'replace_a').stdout)['error']=='publication_busy'
        assert (public/'probe-marker.json').read_bytes()==raw
    finally:holder.communicate(b'\n',timeout=5)

@pytest.mark.parametrize('leaf',['staging-config.json','ftp-publication.php','probe-marker.json'])
def test_symlink_to_external_fixture_cannot_be_loaded(tmp_path,leaf):
    private,public,cfg=route(tmp_path)
    target=(public if leaf=='probe-marker.json' else private)/leaf
    target.unlink();outside=tmp_path/'outside';outside.write_bytes(b'not-a-config-preserve')
    try:target.symlink_to(outside)
    except OSError:pytest.skip('symlinks unavailable')
    assert json.loads(call(public,'runtime').stdout)['error']=='fixture_namespace_required'
    assert outside.read_bytes()==b'not-a-config-preserve'

def test_unknown_action_set_cannot_enable_state_changes(tmp_path):
    private,public,cfg=route(tmp_path);cfg['allowed_actions']=['runtime','read','publish']
    (private/'staging-config.json').write_text(json.dumps(cfg))
    marker=(public/'probe-marker.json').read_bytes()
    assert json.loads(call(public,'replace_b').stdout)['error']=='fixture_configuration_required'
    assert not (private/'probe.lock').exists() and (public/'probe-marker.json').read_bytes()==marker

def test_server_client_rejects_redirect_status_before_using_response():
    result=library("try{fx_response(302,'{}',[],'runtime','fixture');}catch(Throwable $e){echo $e->getMessage();}")
    assert result.stdout=='fixture_http_status_invalid'

def test_default_server_plan_never_reads_config_or_connects():
    result=subprocess.run(['php',str(CLIENT)],capture_output=True,text=True)
    assert result.returncode==0
    value=json.loads(result.stdout)
    assert value['remote_writes_authorized'] is False and value['max_concurrency']==2

def test_run_requires_exact_namespace_and_host_before_config_access():
    result=subprocess.run(['php',str(CLIENT),'run','wrong-root','wrong-host'],capture_output=True,text=True)
    assert result.returncode==1 and json.loads(result.stdout)['reason']=='fixture_specific_approval_required'
