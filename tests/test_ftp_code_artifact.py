import importlib.util
import json
from pathlib import Path
import pytest

SCRIPT=Path(__file__).resolve().parents[1]/'deploy/scripts/ftp-code-artifact.py'
spec=importlib.util.spec_from_file_location('ftp_code_artifact',SCRIPT)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_portal_artifact_excludes_data_and_other_component(tmp_path):
    root=tmp_path/'repo'; source=root/'web/public/eleicoes'; source.mkdir(parents=True)
    (source/'index.html').write_text('fixture')
    (source/'goias').mkdir(); (source/'goias/finance.js').write_text('other component')
    (source/'results.json').write_text('{}')
    artifact=module.package('portal',root,tmp_path/'package')
    files=json.loads((artifact/'artifact.json').read_text())['files']
    assert set(files)=={'index.html'}
    assert (artifact/'READY').read_text()==artifact.name


def test_artifact_refuses_hidden_secret_file(tmp_path):
    root=tmp_path/'repo'; source=root/'web/public/eleicoes'; source.mkdir(parents=True)
    (source/'index.html').write_text('fixture')
    (source/'.env').write_text('SYNTHETIC_FIXTURE')
    with pytest.raises(ValueError,match='unsafe_artifact'):
        module.package('portal',root,tmp_path/'package')
