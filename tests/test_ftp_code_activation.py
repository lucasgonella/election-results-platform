import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest
from test_ftp_code_artifact import module as packager

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ftp_activation',ROOT/'deploy/scripts/prepare-ftp-code-activation.py')
activation=importlib.util.module_from_spec(spec); spec.loader.exec_module(activation)


def test_control_bundle_is_a_single_syntax_valid_public_entrypoint(tmp_path):
    artifact=packager.package('control',ROOT,tmp_path/'package')
    endpoint=(artifact/'files/election-ftp-control.php').read_text()
    assert "require_once __DIR__ . '/ftp-publication.php'" not in endpoint
    assert 'function fp_validate_release' in endpoint
    for php in (artifact/'files').rglob('*.php'):
        subprocess.run(['php','-l',str(php)],check=True,capture_output=True)
    public=tmp_path/'public'; public.mkdir()
    plan=activation.prepare(artifact,artifact.name,public,tmp_path/'plan')
    assert len(plan['operations'])==1
    assert plan['operations'][0]['target']==str(public/'api/election-ftp-control.php')
    assert not (public/'api').exists()


def test_portal_plan_is_pinned_and_recoverable_without_touching_data(tmp_path):
    repo=tmp_path/'repo'; source=repo/'web/public/eleicoes'; source.mkdir(parents=True)
    (source/'index.html').write_text('<script src="app.js?v=1"></script><a href="composition.html">c</a><a href="goias/raio-x/">g</a>')
    (source/'app.js').write_text('fixture_new')
    (source/'composition.html').write_text('<script src="app.js"></script>')
    public=tmp_path/'public'; portal=public/'eleicoes'; portal.mkdir(parents=True)
    (portal/'index.html').write_text('previous_index')
    (portal/'composition.html').write_text('previous_composition')
    (portal/'app.js').write_text('previous_asset')
    (public/'data').mkdir(); (public/'data/version.json').write_text('preserve_data')
    (portal/'goias').mkdir(); (portal/'goias/preserved').write_text('preserve_goias')
    artifact=packager.package('portal',repo,tmp_path/'package')
    output=tmp_path/'plan'; plan=activation.prepare(artifact,artifact.name,public,output)
    assert (portal/'index.html').read_text()=='previous_index'
    assert '/eleicoes/releases/'+artifact.name+'/app.js?v=1' in (output/'files/index.html').read_text()
    assert '/eleicoes/goias/raio-x/' in (output/'files/index.html').read_text()
    backups={}
    # Simulate only this temp fixture's supervised deployment: assets first,
    # entrypoints last, then restore entrypoint bytes by same-directory rename.
    for op in plan['operations']:
        target=Path(op['target']); target.parent.mkdir(parents=True,exist_ok=True)
        if op['role']=='entrypoint' and target.exists(): backups[target]=target.read_bytes()
        staged=target.with_suffix('.tmp'); shutil.copyfile(output/op['source'],staged); os.replace(staged,target)
    assert '/eleicoes/releases/'+artifact.name in (portal/'index.html').read_text()
    assert (portal/'app.js').read_text()=='previous_asset'
    for target,raw in backups.items():
        staged=target.with_suffix('.tmp'); staged.write_bytes(raw); os.replace(staged,target)
    assert (portal/'index.html').read_text()=='previous_index'
    assert (public/'data/version.json').read_text()=='preserve_data'
    assert (portal/'goias/preserved').read_text()=='preserve_goias'


def test_activation_plan_refuses_modified_or_unapproved_artifact(tmp_path):
    artifact=packager.package('control',ROOT,tmp_path/'package')
    public=tmp_path/'public'; public.mkdir()
    with pytest.raises(ValueError,match='unapproved_artifact'):
        activation.prepare(artifact,'0'*64,public,tmp_path/'plan1')
    (artifact/'files/election-ftp-control.php').write_text('<?php /* corrupt */')
    with pytest.raises(ValueError,match='artifact_integrity_error'):
        activation.prepare(artifact,artifact.name,public,tmp_path/'plan2')
    assert not list(public.iterdir())


def test_activation_plan_cannot_stage_inside_public_root(tmp_path):
    artifact=packager.package('control',ROOT,tmp_path/'package')
    public=tmp_path/'public'; public.mkdir()
    with pytest.raises(ValueError,match='private_output_required'):
        activation.prepare(artifact,artifact.name,public,public/'unsafe')
    assert not list(public.iterdir())
