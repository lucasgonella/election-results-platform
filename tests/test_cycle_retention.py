import json
from pathlib import Path
import pytest
from collector.src import cycle_retention as retention
from collector.src.election_release import META


def cycle(root, number, review=None):
    path = root/'cycles'/f'20260101T000000-{number:08x}'
    (path/'collection/stage').mkdir(parents=True)
    for name in META:
        (path/'collection/stage'/name).write_text('{}')
    (path/'review-required.json').write_text(json.dumps(review or {}))
    return path


def test_reference_package_unique_review_and_unknown_preservation(tmp_path):
    a,b,c,d,e,f = [cycle(tmp_path, n) for n in range(6)]
    (tmp_path/'recovery.json').write_text(json.dumps({'nested':[{'path':str(a/'collection')}]}))
    (b/'package').mkdir()
    review = {'am/governor.json':{'source_sha256':'a'*64,'reason':'review'}}
    for path in (c,d):
        (path/'review-required.json').write_text(json.dumps(review))
    (e/'.env').write_text('never upload')
    (f/'review-required.json').unlink()
    selected = retention.plan(tmp_path, min_age_hours=0)
    assert selected['eligible'] == [c.name]
    assert selected['total'] == 6


def test_corrupt_control_and_symlink_block_cleanup(tmp_path):
    a=cycle(tmp_path, 1)
    (tmp_path/'health.json').write_text('{')
    with pytest.raises((ValueError, json.JSONDecodeError)):
        retention.plan(tmp_path)
    (tmp_path/'health.json').unlink()
    (a/'secret.json').symlink_to('/etc/passwd')
    assert retention.plan(tmp_path,min_age_hours=0)['eligible'] == []


class Remote:
    def __init__(self, fail=False): self.files={}; self.fail=fail
    def upload(self, name, stream, size, sha256):
        raw=stream.read()
        assert len(raw)==size and retention.digest(raw)==sha256
        if self.fail: raise ValueError('backup_hash_mismatch')
        self.files[name]=raw


def test_archive_verified_before_removal_with_manifest(tmp_path):
    a=cycle(tmp_path, 1); remote=Remote()
    retention.archive_one(tmp_path,a.name,remote)
    assert not a.exists()
    assert a.name+'.tar.gz' in remote.files
    records=[json.loads(line) for line in (tmp_path/'archive-manifest.jsonl').read_text().splitlines()]
    assert [r['state'] for r in records]==['verified','deleted']
    assert records[0]['sha256']==retention.digest(remote.files[a.name+'.tar.gz'])


def test_failed_backup_never_deletes_source(tmp_path):
    a=cycle(tmp_path,1)
    with pytest.raises(ValueError,match='backup_hash_mismatch'):
        retention.archive_one(tmp_path,a.name,Remote(fail=True))
    assert a.exists()
    assert not (tmp_path/'archive-manifest.jsonl').exists()


def test_reference_appearing_during_backup_preserves_cycle(tmp_path):
    a=cycle(tmp_path,1)
    class ChangingRemote(Remote):
        def upload(self,*args):
            super().upload(*args)
            (tmp_path/'in-flight.json').write_text(json.dumps({'package':str(a/'package')}))
    with pytest.raises(ValueError,match='cycle_changed_after_backup'):
        retention.archive_one(tmp_path,a.name,ChangingRemote())
    assert a.exists()


@pytest.mark.parametrize('actual,size,sha256',[
    (b'partial',20,retention.digest(b'complete')),
    (b'corrupt!',8,retention.digest(b'complete')),
])
def test_download_verification_rejects_partial_or_corrupt_bytes(actual,size,sha256):
    remote=retention.ArchiveFTP.__new__(retention.ArchiveFTP)
    class FTP:
        def size(self,name): return size
    remote.ftp=FTP()
    remote.transfer=lambda name:actual
    with pytest.raises(ValueError,match='backup_(size|hash)_mismatch'):
        remote.verified('synthetic.tar.gz',size,sha256)


def test_dry_run_never_connects_or_deletes(tmp_path,monkeypatch):
    a=cycle(tmp_path,1)
    monkeypatch.setattr('sys.argv',['retention','--root',str(tmp_path),'--min-age-hours','0'])
    monkeypatch.setattr(retention,'ArchiveFTP',lambda:pytest.fail('no FTP in dry-run'))
    assert retention.main()==0
    assert a.exists()
