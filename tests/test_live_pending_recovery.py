"""Execute wrapper only with fake local publishers and synthetic live state."""
import os
from pathlib import Path
import subprocess
import pytest

pytestmark=pytest.mark.skipif(os.name=='nt',reason='Bash execution validated by Linux CI')
SCRIPT=Path(__file__).resolve().parents[1]/'deploy/scripts/run-live-publisher.sh'


@pytest.mark.parametrize('complete',[True,False])
def test_existing_pending_is_never_reprepared_or_committed_after_failure(tmp_path,complete):
    live=tmp_path/'live';pending=live/'pending';stage=live/'stage'
    pending.mkdir(parents=True);stage.mkdir()
    sentinel=pending/'preserved.json';sentinel.write_text('{"fixture":true}')
    if complete:
        (pending/'version.json').write_text('{}');(stage/'version.json').write_text('{}')
    venv=tmp_path/'venv/bin';venv.mkdir(parents=True)
    python=venv/'python';python.write_text('#!/bin/bash\nexit 99\n');python.chmod(0o755)
    publisher=tmp_path/'fake-publish.sh';publisher.write_text('#!/bin/bash\nexit 17\n')
    env=dict(os.environ,ELECTION_APP_DIR=str(tmp_path),ELECTION_VENV_DIR=str(venv.parent),
             LIVE_PUBLISH_STATE_DIR=str(live),LIVE_PUBLISH_SCRIPT=str(publisher))
    result=subprocess.run(['bash',str(SCRIPT)],env=env,capture_output=True,text=True)
    assert result.returncode==(17 if complete else 1)
    assert sentinel.read_text()=='{"fixture":true}'
