"""Synthetic failure points only. No network, provider, TSE or database access."""
import ftplib
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from collector.src.ftp_delivery import freeze, publish, upload
from collector.src.ftp_live_runner import acknowledge
from test_ftp_publication import KEY, HELPER, call, dataset, deliver, env


class MemoryFTP:
    """Real uploader, bounded in-memory FTP; no actual socket is opened."""
    def __init__(self, fault=None):
        self.fault = fault
        self.files = {}
        self.renamed = []
        self.stored = []

    def connect(self, host, port, timeout):
        assert host == 'fixture.invalid' and port == 21

    def login(self, *args): pass
    def set_pasv(self, value): assert value is True
    def close(self): pass
    def mkd(self, path): pass
    def sendcmd(self, command): raise ftplib.error_perm('550 fixture hidden')

    def storbinary(self, command, stream):
        path = command.removeprefix('STOR ')
        raw = stream.read()
        self.stored.append(path)
        self.files[path] = raw[:max(1, len(raw)//2)] if self.fault == 'upload' else raw
        if self.fault == 'upload': raise ConnectionResetError('synthetic interruption')

    def retrbinary(self, command, callback):
        raw = self.files[command.removeprefix('RETR ')]
        callback(raw[:-1] if self.fault == 'readback' else raw)

    def rename(self, source, target):
        if self.fault == 'rename': raise OSError('synthetic rename failure')
        self.files[target] = self.files.pop(source)
        self.renamed.append(target)


@pytest.mark.parametrize('fault', ['upload', 'readback', 'rename'])
def test_interrupted_transport_never_activates_and_same_id_retry_recovers(tmp_path, fault):
    delivery = freeze(dataset(tmp_path/'stage'), tmp_path/'spool', KEY, None)
    ftp = MemoryFTP(fault)
    class Control:
        def request(self, action, ident):
            assert ident == delivery.name and action == 'status'
            return {'status': 'unknown', 'delivery_id': ident}
    transfer = lambda: upload(delivery, 'private/inbox', 'fixture.invalid', 'fixture', 'fixture', lambda: ftp)
    with pytest.raises((OSError, ValueError)): publish(delivery, Control(), transfer)
    assert not any(path.endswith('/READY') for path in ftp.renamed)
    assert all(path.startswith('private/inbox/'+delivery.name+'/') for path in ftp.files)
    ftp.fault = None
    transfer()
    assert ftp.renamed[-1].endswith('/READY')
    assert ftp.files[ftp.renamed[-1]] == delivery.name.encode()
    assert not any(path.endswith('.part') for path in ftp.files)


def test_completed_upload_retry_interrupted_preserves_identical_committed_bytes(tmp_path):
    delivery = freeze(dataset(tmp_path/'stage'), tmp_path/'spool', KEY, None)
    ftp = MemoryFTP()
    args = (delivery, 'private/inbox', 'fixture.invalid', 'fixture', 'fixture', lambda: ftp)
    upload(*args)
    original = dict(ftp.files)
    ftp.fault = 'upload'
    with pytest.raises(ConnectionResetError): upload(*args)
    assert {key: value for key, value in ftp.files.items() if not key.endswith('.part')} == original
    ftp.fault = None
    upload(*args)
    assert ftp.files == original


def test_ambiguous_status_failure_preserves_delivery_for_later_reconciliation(tmp_path):
    delivery = freeze(dataset(tmp_path/'stage'), tmp_path/'spool', KEY, None)
    before = {p.relative_to(delivery): p.read_bytes() for p in delivery.rglob('*') if p.is_file()}
    transfers = []
    class BrokenControl:
        def request(self, action, ident):
            if action == 'activate': raise TimeoutError('synthetic lost response')
            if transfers: raise OSError('synthetic unavailable storage')
            return {'status': 'unknown'}
    with pytest.raises(OSError): publish(delivery, BrokenControl(), lambda: transfers.append(1))
    assert transfers == [1]
    assert {p.relative_to(delivery): p.read_bytes() for p in delivery.rglob('*') if p.is_file()} == before
    class RecoveredControl:
        def request(self, action, ident):
            assert action == 'status'
            return {'status': 'published', 'delivery_id': ident, 'snapshot_id': ident}
    assert publish(delivery, RecoveredControl(), lambda: pytest.fail('must not reupload'))['status'] == 'published'


def test_pending_state_survives_confirmation_write_failure(tmp_path, monkeypatch):
    import collector.src.ftp_live_runner as runner
    queue = tmp_path/'ftp-queue'; queue.mkdir()
    (tmp_path/'state').mkdir(); (tmp_path/'state/old').write_text('old')
    (queue/'state-fixture').mkdir(); (queue/'state-fixture/new').write_text('new')
    job = {'id': 'fixture', 'receipt': {'snapshot_id': 'fixture'}}
    (queue/'current.json').write_text(json.dumps(job))
    original_save = runner.save
    monkeypatch.setattr(runner, 'save', lambda *args: (_ for _ in ()).throw(OSError('synthetic disk error')))
    with pytest.raises(OSError): acknowledge(tmp_path, job)
    assert (queue/'current.json').exists() and (queue/'previous-fixture/old').exists()
    assert (tmp_path/'state/new').exists() and not (queue/'confirmed.json').exists()
    monkeypatch.setattr(runner, 'save', original_save)
    acknowledge(tmp_path, job)
    assert json.loads((queue/'confirmed.json').read_text())['snapshot_id'] == 'fixture'
    assert not (queue/'current.json').exists() and (queue/'previous-fixture/old').exists()


def storage_call(cfg, action, ident, fault='none'):
    """PHP namespace interception, never a fault switch in deployed code."""
    script = r'''
namespace FixtureStorage;
$GLOBALS['fault']=$argv[5];$GLOBALS['events']=[];
function fixture_fault(string $path,string $point):bool {
    return $GLOBALS['fault']===$point && ($point!=='sealed_write'||str_contains($path,'/sealed/'));
}
function gethostname():string {return $GLOBALS['fault']==='other_host'?'other-fixture-host':\gethostname();}
function fsync($stream):bool {
    $path=stream_get_meta_data($stream)['uri'];$dir=is_dir($path);
    $GLOBALS['events'][]=['op'=>'fsync','path'=>$path,'directory'=>$dir];
    if($GLOBALS['fault']==='file_sync'&&!$dir&&str_contains($path,'/sealed/'))return false;
    if($GLOBALS['fault']==='directory_sync'&&$dir)return false;
    if($GLOBALS['fault']==='marker_directory_sync'&&$dir&&is_file($path.'/version.json')&&isset(json_decode(\file_get_contents($path.'/version.json'),true)['delivery_id']))return false;
    return \fsync($stream);
}
function fwrite($stream,string $bytes):int|false {
    $path=stream_get_meta_data($stream)['uri'];
    if(fixture_fault($path,'sealed_write'))return false;
    return \fwrite($stream,$bytes);
}
function file_put_contents(string $path,mixed $bytes):int|false {
    if(fixture_fault($path,'sealed_write'))return false;
    return \file_put_contents($path,$bytes);
}
function file_get_contents(string $path,...$args):string|false {
    if($GLOBALS['fault']==='baseline_read'&&str_contains($path,'/releases/')&&str_ends_with($path,'/ac/president.json'))return false;
    return \file_get_contents($path,...$args);
}
function rename(string $from,string $to):bool {
    $GLOBALS['events'][]=['op'=>'rename','path'=>$to];
    if($GLOBALS['fault']==='marker_rename'&&str_ends_with($to,'/data/version.json'))return false;
    if($GLOBALS['fault']==='after_activation'&&str_contains($to,'/receipts/'))throw new \RuntimeException('fixture_interrupted_after_activation');
    return \rename($from,$to);
}
$source=\file_get_contents($argv[1]);$source=substr($source,strlen("<?php\n"));
$source=preg_replace('/declare\(strict_types=1\);/','',$source,1);
eval('namespace FixtureStorage;'.$source);
$cfg=json_decode($argv[2],true);$cfg['key']=hex2bin($cfg['key']);
try{$result=fp_run($cfg,$argv[3],$argv[4]);}catch(\Throwable $e){$result=['error'=>$e->getMessage()];}
echo json_encode(['result'=>$result,'events'=>$GLOBALS['events']]);
'''
    result = subprocess.run(['php', '-r', script, str(HELPER), json.dumps(cfg), action, ident, fault],
                            capture_output=True, text=True, check=True, timeout=20)
    return json.loads(result.stdout)


def marker_bytes(root): return (root/'public/data/version.json').read_bytes()


@pytest.mark.parametrize('kind', ['missing', 'empty', 'incomplete', 'older'])
def test_missing_or_stale_watermarks_fail_closed_without_regression(env, kind):
    root, cfg = env
    first = deliver(env); assert call(cfg, 'activate', first.name)['status'] == 'published'
    water_path = root/'private/watermarks.json'; older = water_path.read_bytes()
    second = deliver(env, 3, first.name, True); assert call(cfg, 'activate', second.name)['status'] == 'published'
    previous = marker_bytes(root)
    if kind == 'missing': water_path.unlink()
    elif kind == 'empty': water_path.write_text('{}')
    elif kind == 'incomplete':
        water = json.loads(water_path.read_text()); water.pop('ac/president.json'); water_path.write_text(json.dumps(water))
    else: water_path.write_bytes(older)
    regressed = deliver(env, 2, second.name, True)
    result = call(cfg, 'activate', regressed.name)
    assert result['error'] in {'watermarks_missing_requires_review', 'watermarks_inconsistent_requires_review'}
    assert marker_bytes(root) == previous


@pytest.mark.parametrize('fault', ['sealed_write', 'file_sync', 'directory_sync', 'baseline_read', 'marker_rename'])
def test_storage_failures_before_commit_preserve_marker_and_allow_same_id_recovery(env, fault):
    root, cfg = env
    first = deliver(env); assert call(cfg, 'activate', first.name)['status'] == 'published'
    second = deliver(env, 2, first.name, True); previous = marker_bytes(root)
    result = storage_call(cfg, 'activate', second.name, fault)
    assert result['result']['error'] == 'storage_error'
    assert marker_bytes(root) == previous
    assert not (root/'private/receipts'/f'{second.name}.json').exists()
    assert call(cfg, 'activate', second.name)['status'] == 'published'
    assert call(cfg, 'status', second.name)['snapshot_id'] == second.name


def test_files_and_directory_barriers_precede_marker_commit(env):
    root, cfg = env
    delivery = deliver(env)
    result = storage_call(cfg, 'activate', delivery.name)
    assert result['result']['status'] == 'published'
    events = result['events']
    commit = next(i for i, e in enumerate(events) if e['op'] == 'rename' and e['path'] == str(root/'public/data/version.json'))
    earlier = events[:commit]
    assert sum(e['op']=='fsync' and not e.get('directory',False) and '/sealed/' in e['path'] for e in earlier) == 140
    assert sum(e['op']=='fsync' and not e.get('directory',False) and '/releases/.build-' in e['path'] for e in earlier) == 142
    release_rename = next(i for i, e in enumerate(events) if e['op']=='rename' and e['path']==str(root/'public/data/releases'/delivery.name))
    assert any(e['op']=='fsync' and e.get('directory') and e['path']==str(root/'public/data/releases') for e in events[release_rename+1:commit])


def test_interruption_after_marker_before_receipt_reconciles_without_reupload(env):
    root, cfg = env
    first = deliver(env); assert call(cfg, 'activate', first.name)['status'] == 'published'
    second = deliver(env, 2, first.name, True)
    result = storage_call(cfg, 'activate', second.name, 'after_activation')['result']
    assert result['error'] == 'fixture_interrupted_after_activation'
    assert json.loads(marker_bytes(root))['delivery_id'] == second.name
    assert not (root/'private/receipts'/f'{second.name}.json').exists()
    assert publish(second, type('Control', (), {'request':lambda self, action, ident:call(cfg, action, ident)})(),
                   lambda:pytest.fail('must reconcile without reupload'))['status']=='published'
    assert call(cfg, 'activate', second.name)['status']=='published'
    assert call(cfg, 'rollback', second.name)['snapshot_id']==first.name


def test_directory_sync_failure_after_marker_is_ambiguous_and_status_must_not_acknowledge(env):
    root, cfg = env
    delivery = deliver(env)
    assert storage_call(cfg, 'activate', delivery.name, 'marker_directory_sync')['result']['error']=='storage_error'
    assert json.loads(marker_bytes(root))['delivery_id']==delivery.name
    assert storage_call(cfg, 'status', delivery.name, 'marker_directory_sync')['result']['error']=='storage_error'
    assert call(cfg, 'status', delivery.name)['status']=='published'


def test_corrupt_historical_receipt_is_not_accepted_as_confirmation(env):
    root, cfg = env
    first = deliver(env); assert call(cfg, 'activate', first.name)['status']=='published'
    second = deliver(env, 2, first.name, True); assert call(cfg, 'activate', second.name)['status']=='published'
    (root/'private/receipts'/f'{first.name}.json').write_text(json.dumps({'status':'published','delivery_id':first.name,'snapshot_id':second.name}))
    assert call(cfg, 'status', first.name)['error']=='invalid_receipt'


def test_same_identifier_attempts_preserve_release_and_marker_bytes(env):
    root, cfg = env
    delivery=deliver(env); assert call(cfg,'activate',delivery.name)['status']=='published'
    original=marker_bytes(root)
    release=root/'public/data/releases'/delivery.name
    hashes={p.relative_to(release):hashlib.sha256(p.read_bytes()).hexdigest() for p in release.rglob('*') if p.is_file()}
    for _ in range(2): assert call(cfg,'activate',delivery.name)['snapshot_id']==delivery.name
    assert marker_bytes(root)==original
    assert {p.relative_to(release):hashlib.sha256(p.read_bytes()).hexdigest() for p in release.rglob('*') if p.is_file()}==hashes


def test_other_nfs_host_is_rejected_before_any_state_creation(env):
    root,cfg=env
    delivery=deliver(env)
    assert storage_call(cfg,'activate',delivery.name,'other_host')['result']['error']=='activation_host_mismatch'
    assert list((root/'private').iterdir())==[] and not (root/'public/data/version.json').exists()
