"""The exact offline recovery candidate passes the real FTP activation engine."""
import shutil

from collector.src.ftp_delivery import canonical, freeze
from collector.src.ftp_recovery import parse, prepare, tree
from test_ftp_publication import KEY, call, env
from test_ftp_recovery import recovery


def test_complete_recovery_candidate_activation_and_rollback(env,recovery):
    root,cfg=env
    baseline=freeze(recovery['baseline'],root/'spool',KEY,None)
    shutil.copytree(baseline,root/'inbox'/baseline.name)
    assert call(cfg,'activate',baseline.name)['status']=='published'
    marker=parse(recovery['marker'].read_bytes())|{'snapshot_id':baseline.name}
    recovery['marker'].write_bytes(canonical(marker))
    original_pending=tree(recovery['pending']);original_stage=tree(recovery['stage'])
    prepare(**recovery)
    candidate=freeze(recovery['output']/'candidate',root/'spool',KEY,baseline.name)
    shutil.copytree(candidate,root/'inbox'/candidate.name)
    assert call(cfg,'activate',candidate.name)['status']=='published'
    release=root/'public/data/releases'/candidate.name
    assert (release/'rj/governor.json').read_bytes()==original_stage['rj/governor.json']
    assert (release/'am/governor.json').read_bytes()==(recovery['baseline']/'am/governor.json').read_bytes()
    assert len(list(release.glob('*/*.json')))==137
    assert call(cfg,'rollback',candidate.name)['snapshot_id']==baseline.name
    assert tree(recovery['pending'])==original_pending and tree(recovery['stage'])==original_stage
