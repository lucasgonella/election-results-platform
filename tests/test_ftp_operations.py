import importlib.util
import json
from pathlib import Path
import pytest
import subprocess
from test_ftp_publication import env, deliver, call

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('artifact',ROOT/'deploy/scripts/ftp-code-artifact.py')
artifact=importlib.util.module_from_spec(spec);spec.loader.exec_module(artifact)


@pytest.mark.parametrize('host',[None,'different-host.invalid'])
def test_nfs_host_gate_precedes_any_state_write(env,host):
    cfg=dict(env[1]);cfg.pop('activation_host')
    if host: cfg['activation_host']=host
    before=list((env[0]/'private').iterdir())
    result=call(cfg,'activate','a'*64)
    assert result['error']==('activation_host_mismatch' if host else 'unverified_lock_scope')
    assert list((env[0]/'private').iterdir())==before
    assert not (env[0]/'public/data/version.json').exists()


@pytest.mark.parametrize('component',['portal','control'])
def test_exact_code_artifact_and_mutation_rejection(tmp_path,component):
    package=artifact.package(component,ROOT,tmp_path/'artifacts')
    manifest=artifact.validate_artifact(package,component)
    name=next(iter(manifest['files']))
    (package/'files'/name).write_bytes(b'truncated')
    with pytest.raises(ValueError,match='artifact_integrity_error'):
        artifact.validate_artifact(package,component)


def test_code_artifact_cannot_carry_unlisted_secret(tmp_path):
    package=artifact.package('control',ROOT,tmp_path/'artifacts')
    (package/'files/unlisted.env').write_text('synthetic')
    with pytest.raises(ValueError,match='unsafe_artifact'):artifact.validate_artifact(package,'control')


def test_code_upload_cli_refuses_unapproved_isolation(tmp_path,monkeypatch):
    import sys
    package=artifact.package('control',ROOT,tmp_path/'artifacts')
    monkeypatch.setattr(sys,'argv',['artifact','upload','--component','control','--directory',str(package)])
    monkeypatch.delenv('LOCAWEB_FTP_ISOLATION_APPROVED',raising=False)
    monkeypatch.setattr(artifact,'upload',lambda *a:pytest.fail('must not contact FTP'))
    with pytest.raises(ValueError,match='ftp_isolation_not_approved'):artifact.main()


def test_embedded_readonly_audit_programs_compile():
    spec=importlib.util.spec_from_file_location('audit',ROOT/'deploy/scripts/audit-ftp-migration.py')
    audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
    for code in [audit.LOCAWEB,audit.APP01]:compile(code,'remote_diagnostic','exec')


def test_official_nonfinal_with_full_sections_preserves_final_release(env):
    from collector.src.ftp_delivery import freeze
    from test_ftp_publication import KEY, canonical, dataset
    import shutil
    root,cfg=env
    stage=dataset(root/'final')
    path='am/federal-deputy.json'
    payload=json.loads((stage/path).read_text());payload['snapshot']['totalization_final']=True
    payload['snapshot']['sections']={'total':8157,'totalized':8157,'percentage':100}
    payload['candidates'][0]['elected']=True
    (stage/path).write_bytes(canonical(payload))
    first=freeze(stage,root/'spool',KEY,None);shutil.copytree(first,root/'inbox'/first.name)
    assert call(cfg,'activate',first.name)['status']=='published'
    marker=(root/'public/data/version.json').read_bytes()
    stage=dataset(root/'nonfinal',2)
    payload=json.loads((stage/path).read_text());payload['snapshot']['totalization_final']=False
    payload['snapshot']['sections']={'total':8157,'totalized':8157,'percentage':100}
    payload['candidates'][0]['elected']=False
    (stage/path).write_bytes(canonical(payload))
    second=freeze(stage,root/'spool',KEY,first.name);shutil.copytree(second,root/'inbox'/second.name)
    assert call(cfg,'activate',second.name)['error']=='totalization_reopened_requires_review'
    assert (root/'public/data/version.json').read_bytes()==marker


def test_cutover_override_preserves_timer_and_replaces_entrypoint():
    text=(ROOT/'deploy/systemd/ftp-live-publisher.override.conf.example').read_text()
    assert 'secrets/ftp.env' in text and 'ExecStart=\nExecStart=/bin/bash' in text
    assert '[Timer]' not in text and 'User=' not in text


def test_staging_transfer_inventory_excludes_fixture_secret(tmp_path):
    spec=importlib.util.spec_from_file_location('staging',ROOT/'deploy/scripts/prepare-ftp-staging.py')
    staging=importlib.util.module_from_spec(spec);spec.loader.exec_module(staging)
    root=tmp_path/'ftp-staging-fixture';staging.prepare(root)
    inventory=json.loads((root/'transfer-manifest.json').read_text())
    assert inventory['fixture_only'] is True
    assert inventory['remote_installation_authorized'] is False
    assert inventory['excluded']==['private/staging-config.json']
    expected={path.relative_to(root).as_posix() for path in root.rglob('*')
              if path.is_file() and path.relative_to(root).as_posix()
              not in {'private/staging-config.json','transfer-manifest.json'}}
    assert set(inventory['files'])==expected
    assert len([name for name in expected if name.startswith('fixtures/full/')])==140
    assert len([name for name in expected if name.startswith('fixtures/delta/')])==4
    import hashlib
    for name, digest in inventory['files'].items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest


def test_staging_probe_local_runtime_rename_read_and_lock(tmp_path):
    spec=importlib.util.spec_from_file_location('staging',ROOT/'deploy/scripts/prepare-ftp-staging.py')
    staging=importlib.util.module_from_spec(spec);spec.loader.exec_module(staging)
    root=tmp_path/'ftp-staging-fixture';staging.prepare(root)
    def run(action):
        return json.loads(subprocess.check_output(['php',str(root/'public/probe.php'),action],text=True))
    assert run('runtime')['sapi']=='cli'
    assert run('replace_b')['status']=='replaced'
    assert run('read')['marker']=={'fixture':'replace_b'}
    assert run('replace_a')['status']=='replaced'  # marker recovery fixture
    assert run('read')['marker']=={'fixture':'replace_a'}
    processes=[subprocess.Popen(['php',str(root/'public/probe.php'),'lock'],stdout=subprocess.PIPE,text=True) for _ in range(2)]
    results=[json.loads(p.communicate()[0]) for p in processes]
    assert sum(r.get('status')=='lock_acquired' for r in results)==1
    assert sum(r.get('error')=='publication_busy' for r in results)==1
    with pytest.raises(ValueError):staging.prepare(root)


@pytest.mark.parametrize('host', [None, 'different-host.invalid'])
@pytest.mark.parametrize('action', ['lock', 'replace_b'])
def test_staging_probe_host_gate_precedes_mutation(tmp_path, host, action):
    spec=importlib.util.spec_from_file_location('staging',ROOT/'deploy/scripts/prepare-ftp-staging.py')
    staging=importlib.util.module_from_spec(spec);spec.loader.exec_module(staging)
    root=tmp_path/'ftp-staging-host-gate';staging.prepare(root)
    config_path=root/'private/staging-config.json'
    config=json.loads(config_path.read_text())
    config.pop('activation_host')
    if host is not None:config['activation_host']=host
    config_path.write_text(json.dumps(config),encoding='utf-8')
    marker=(root/'public/probe-marker.json').read_bytes()
    before=sorted(p.name for p in (root/'private').iterdir())
    result=subprocess.run(['php',str(root/'public/probe.php'),action],capture_output=True,text=True)
    assert result.returncode==1
    assert json.loads(result.stdout)['error']==('unverified_lock_scope' if host is None else 'activation_host_mismatch')
    assert (root/'public/probe-marker.json').read_bytes()==marker
    assert sorted(p.name for p in (root/'private').iterdir())==before
