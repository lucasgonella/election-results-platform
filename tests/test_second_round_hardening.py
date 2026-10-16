"""Faults use isolated fake FTP and invented election fixtures only."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import io
import json
from pathlib import Path
import subprocess
import shutil
import time

import pytest

from collector.src.election_release import canonical, digest, tree
from collector.src.second_round_collection import build_values, discover, write_values
from collector.src.second_round_metrics import policy
from collector.src.second_round_publish import Publisher, SITE, PRIVATE, Transport, describe, marker_for, load, save
from collector.src.second_round_runner import cycle, proof, verify_proof, legacy_rollback
from collector.src.second_round_retention import plan, archive_one
from collector.src.second_round_monitor import assess, publish_status, notify, run
from test_second_round_transactions import Source, FTP, package


def setup(state, name, source=None, *, portal=True):
    source = source or Source()
    values = build_values(source, discover(source), include_portal=portal)
    dest = state / 'cycles' / name / 'package'
    write_values(dest, values)
    save(dest.parent / 'source-proof.json', proof(values, source))
    return dest, describe(values)


def test_bundle_bound_to_marker_and_all_individual_results(tmp_path):
    dest, valid = setup(tmp_path, 'a' * 32)
    values = tree(dest)
    marker = json.loads(marker_for(valid))
    assert marker['portal']['sha256'] == digest(values['portal.json'])
    bad = json.loads(values['portal.json'])
    bad['files']['ac/governor.json']['candidates'][0]['votes'] += 1
    values['portal.json'] = canonical(bad)
    with pytest.raises(ValueError, match='portal_bundle_mismatch'): describe(values)


def test_legacy_proof_and_release_remain_valid(tmp_path):
    dest, valid = setup(tmp_path, 'a' * 32, portal=False)
    assert verify_proof(dest)['snapshot_id'] == valid['snapshot_id']
    assert 'portal' not in json.loads(marker_for(valid))


def test_unchanged_cycle_creates_no_additional_durable_cycle(tmp_path, monkeypatch):
    ftp = FTP(); ftp.dirs.update({'/public_html/data', '/public_html/data/turnos', SITE})
    factory = lambda transport, state: Publisher(transport, state, http=lambda path: ftp.files.get(SITE + '/' + path))
    monkeypatch.setattr('collector.src.second_round_runner.Publisher', factory)
    state = tmp_path / 'state'
    connector = lambda: Transport(ftp)
    first = cycle(state, client=Source(totalized=0), connector=connector)
    health = load(state / 'health.json'); health['retry_after_epoch'] = 0; save(state / 'health.json', health)
    before = len(list((state / 'cycles').iterdir()))
    second = cycle(state, client=Source(totalized=0), connector=connector)
    assert second['status'] == 'unchanged'
    assert len(list((state / 'cycles').iterdir())) == before == 1
    assert second['last_source_success_at'] > first['last_source_success_at']
    assert second['last_publication_at'] == first['last_publication_at']
    assert 'collection' in second['metrics'] and 'publication' in second['metrics']


def test_inventory_change_during_collection_never_creates_package(tmp_path):
    class Changing(Source):
        n = 0
        def fetch_json(self, url):
            if '/comum/' in url:
                self.n += 1
                if self.n > 1: self.config['pl'][0]['e'][0]['abr'][0]['cd'] = 'go'
            return super().fetch_json(url)
    with pytest.raises(ValueError, match='inventory_changed'): cycle(tmp_path, dry_run=True, client=Changing())
    assert not (tmp_path / 'cycles').exists()
    assert not (tmp_path / 'checkpoint.json').exists()


def test_adaptive_policy_uses_official_sections_and_stability():
    roster = build_values(Source(totalized=0), discover(Source(totalized=0)))
    counting = build_values(Source(totalized=50), discover(Source(totalized=50)))
    assert policy(roster, {}, 'a')['election_state'] == 'official_data_available'
    assert policy(counting, {}, 'a')['election_state'] == 'counting_in_progress'
    previous = {'source_fingerprint': 'a', 'stable_cycles': 10}
    stable = policy(counting, previous, 'a')
    assert stable['election_state'] == 'counting_stable' and stable['poll_after_seconds'] <= 120
    assert policy(counting, previous, 'b')['election_state'] == 'counting_in_progress'


def test_retention_archives_duplicate_preserves_journal_and_can_replay_protected_package(tmp_path):
    duplicate, valid = setup(tmp_path, 'a' * 32)
    protected, _ = setup(tmp_path, 'b' * 32)
    receipt = {'status': 'published', 'snapshot_id': valid['snapshot_id'], 'verified_at': datetime.now(timezone.utc).isoformat()}
    save(tmp_path / 'checkpoint.json', receipt)
    save(tmp_path / 'receipts' / (valid['snapshot_id'] + '.json'), receipt)
    save(tmp_path / 'journals' / (valid['snapshot_id'] + '.json'), {'package': str(protected)})
    selected = plan(tmp_path, min_age_hours=0)
    assert [x['cycle'] for x in selected['eligible']] == ['a' * 32]
    class Remote:
        files = {}
        def upload(self, name, stream, size, sha256):
            raw = stream.read(); assert len(raw) == size and digest(raw) == sha256
            self.files[name] = raw
    remote = Remote()
    archive_one(tmp_path, selected['eligible'][0], remote)
    assert not duplicate.exists() and protected.exists()
    assert verify_proof(protected)['snapshot_id'] == valid['snapshot_id']
    assert any(name.endswith('.tar.gz') for name in remote.files)
    assert '"state":"deleted"' in (tmp_path / 'retention-manifest.jsonl').read_text()


def test_retention_does_not_delete_after_failed_remote_verification(tmp_path):
    dest, valid = setup(tmp_path, 'a' * 32)
    class Corrupt:
        def upload(self, *args): raise ValueError('backup_hash_mismatch')
    with pytest.raises(ValueError, match='backup_hash'):
        archive_one(tmp_path, {'cycle': 'a' * 32, 'snapshot_id': valid['snapshot_id']}, Corrupt())
    assert dest.exists()
    save(tmp_path / 'pending.json', {'phase': 'unknown', 'package': str(dest)})
    with pytest.raises(ValueError, match='unknown_round2_transaction'): plan(tmp_path, min_age_hours=0)


def test_public_status_is_honest_before_results_and_during_source_outage():
    now = datetime.now(timezone.utc)
    health = {'status': 'unchanged', 'last_source_success_at': now.isoformat(), 'election_state': 'official_data_available'}
    cp = {'snapshot_id': 'a' * 64, 'verified_at': (now - timedelta(days=2)).isoformat()}
    marker = {'snapshot_id': 'a' * 64}
    status = assess(health, cp, None, marker)
    assert status['state'] == 'awaiting_results' and not status['reasons']
    late = assess(health, cp, None, marker, epoch=now.timestamp() + 1000)
    assert late['state'] == 'collection_late'
    bad = assess(health, cp, None, {'snapshot_id': 'b' * 64})
    assert 'checkpoint_publication_inconsistency' in bad['reasons']
    pending = {'snapshot_id': 'b' * 64, 'created_at': now.isoformat(), 'phase': 'verified'}
    assert assess(health, cp, pending, {'snapshot_id': 'b' * 64})['state'] == 'updating'


def test_status_partial_upload_recovers_only_known_journal(tmp_path):
    ftp = FTP(); ftp.dirs.update({'/public_html/data', '/public_html/data/turnos', SITE})
    transport = Transport(ftp)
    ftp.files[SITE + '/status.json.upload'] = b'unknown'
    with pytest.raises(RuntimeError, match='unknown_public_status_temporary'):
        publish_status(transport, tmp_path, {'state': 'awaiting_results'})
    assert ftp.files[SITE + '/status.json.upload'] == b'unknown'
    save(tmp_path / 'status-pending.json', {'raw': canonical({'state': 'prior'}).hex(), 'before': None})
    publish_status(transport, tmp_path, {'state': 'current'})
    assert json.loads(ftp.files[SITE + '/status.json']) == {'state': 'current'}
    assert load(tmp_path / 'status-pending.json') is None


def test_notification_failure_does_not_hide_monitor_health(tmp_path, monkeypatch):
    monkeypatch.setenv('ELECTION_ROUND2_NTFY_URL', 'http://127.0.0.1/isolated-test')
    monkeypatch.setattr('collector.src.second_round_monitor.notify', lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()))
    output = tmp_path / 'monitor' / 'status.json'
    status = run(tmp_path, output, timer_active=False, public_reader=lambda _: None, test_alert=True)
    assert output.exists() and status['notification']['sent'] is False
    assert 'collector_timer_inactive' in status['reasons']


def test_reader_cache_dedup_bundle_hash_retry_after_and_etag(tmp_path):
    node = shutil.which('node'); assert node
    source = Source(); values = build_values(source, discover(source)); valid = describe(values)
    fixtures = {name: raw.decode() for name, raw in values.items()}
    data = tmp_path / 'values.json'; data.write_text(json.dumps({'values': fixtures, 'marker': json.loads(marker_for(valid))}))
    script = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),{create}=require('./web/public/eleicoes/live-data.js');
const f=JSON.parse(fs.readFileSync(process.argv[1])),base='/data/turnos/2/releases/'+f.marker.snapshot_id;
let time=10000,calls=[];
const reader=create(async(url,options)=>{calls.push({url,options,time});return new Response(url.endsWith('/version.json')?JSON.stringify(f.marker):f.values['portal.json'],{headers:{ETag:'"version"'}});},
 {clock:()=>time,sleep:async ms=>{time+=ms;},random:()=>0,spacingMs:0});
(async()=>{
 await reader.fetch('/data/turnos/2/version.json');
 const result=await Promise.all([reader.fetch(base+'/manifest.json'),reader.fetch(base+'/ac/governor.json'),reader.fetch(base+'/alerts.json')]);
 assert.equal((await result[1].json()).election.round,2);assert.equal(calls.length,2);
 assert.equal(calls[1].url,base+'/portal.json');
 let tries=0,starts=[];
 const limited=create(async()=>{starts.push(time);return ++tries===1?new Response('',{status:429,headers:{'Retry-After':'3'}}):new Response('{}');},
 {clock:()=>time,sleep:async ms=>{time+=ms;},random:()=>0,spacingMs:0});
 assert((await limited.fetch('/data/turnos/2/status.json')).ok);
 assert(starts[1]-starts[0]>=3000);assert.equal(limited.stats.http429,1);
 assert.equal(limited.retryAfter('7200'),7200000);
 let checked=0;
 const conditional=create(async(url,options)=>{checked++;if(checked===2){assert.equal(options.headers['If-None-Match'],'"same"');return new Response(null,{status:304});}
 return new Response('{}',{headers:{ETag:'"same"'}});},
 {clock:()=>time,sleep:async ms=>{time+=ms;},random:()=>0,spacingMs:0});
 await conditional.fetch('/data/turnos/2/status.json');time+=6000;
 assert.deepEqual(await (await conditional.fetch('/data/turnos/2/status.json')).json(),{});
 const broken=create(async url=>new Response(url.endsWith('version.json')?JSON.stringify({...f.marker,portal:{...f.marker.portal,sha256:'a'.repeat(64)}}):f.values['portal.json']),
 {clock:()=>time,sleep:async ms=>{time+=ms;},random:()=>0,spacingMs:0});
 await broken.fetch('/data/turnos/2/version.json');
 await assert.rejects(broken.fetch(base+'/manifest.json'),/integrity/);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result = subprocess.run([node, '-e', script, str(data)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_parallel_disjoint_files_and_failure_preserve_previous_marker(tmp_path, monkeypatch):
    from hardening_fixtures import FullSource
    ftp = FTP(); ftp.dirs.update({'/public_html/data', '/public_html/data/turnos', SITE})
    def connection():
        child = FTP(); child.files, child.dirs, child.events = ftp.files, ftp.dirs, ftp.events
        return child
    transport = Transport(ftp, reconnect=connection)
    pub = Publisher(transport, tmp_path / 'state', http=lambda path: ftp.files.get(SITE + '/' + path))
    source = FullSource(totalized=0)
    values = build_values(source, discover(source)); dest = tmp_path / 'package'; write_values(dest, values)
    assert describe(values)['targets'] == 35
    assert pub.publish(dest)['status'] == 'published'
    original = ftp.files[SITE + '/version.json']
    second = FullSource(generation=2)
    changed = build_values(second, discover(second)); next_package = tmp_path / 'next'; write_values(next_package, changed)
    def unavailable(): raise TimeoutError('isolated FTP outage')
    pub.fault = lambda point: setattr(transport, 'reconnect', unavailable) if point == 'after_journal' else None
    with pytest.raises(TimeoutError): pub.publish(next_package)
    assert ftp.files[SITE + '/version.json'] == original
    assert load(pub.job_path)
    transport.reconnect = connection
    pub.fault = lambda _: None
    assert pub.recover()['status'] == 'published'
    assert pub.status()['checkpoint_matches']


def test_actual_ntfy_http_contract_in_loopback_only(tmp_path, monkeypatch):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            requests.append(self.rfile.read(int(self.headers['Content-Length'])))
            body = b'{"id":"isolated-confirmed-message"}'
            self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        monkeypatch.setenv('ELECTION_ROUND2_NTFY_URL', 'http://127.0.0.1:' + str(server.server_port) + '/test')
        result = notify({'state': 'test', 'reasons': [], 'last_source_success_at': None}, test=True)
        assert result['sent'] and result['message_id'] == 'isolated-confirmed-message'
        assert b'Ensaio controlado' in requests[0]
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


def test_legacy_code_rollback_changes_no_official_result_and_preserves_reactivation_audit(tmp_path):
    ftp = FTP(); ftp.dirs.update({'/public_html/data', '/public_html/data/turnos', SITE})
    pub = Publisher(Transport(ftp), tmp_path, http=lambda path: ftp.files.get(SITE + '/' + path))
    original, valid = setup(tmp_path, 'a' * 32)
    pub.publish(original)
    active_bytes = {k: v for k, v in tree(original).items() if k != 'portal.json'}
    assert legacy_rollback(pub, tmp_path)['status'] == 'published'
    marker = pub.marker()
    assert 'portal' not in json.loads(marker)
    assert pub.release(marker)[0] == active_bytes
    # Select the original immutable representation again without losing its
    # first journal, receipt or before-marker backup.
    pub.publish(original)
    assert pub.status()['snapshot_id'] == valid['snapshot_id']
    assert len(list((tmp_path / 'journals').glob('*.json'))) == 3
    assert list((tmp_path / 'receipt-history').glob('*.json'))


def test_retention_lock_defers_timer_cycle_without_false_service_failure(tmp_path, monkeypatch, capsys):
    from collector.src.second_round_publish import local_lock
    from collector.src.second_round_runner import main
    import sys
    monkeypatch.setattr(sys, 'argv', ['round2', 'cycle', '--state', str(tmp_path)])
    monkeypatch.setattr('collector.src.second_round_runner.credentials', lambda: None)
    with local_lock(tmp_path):
        assert main() == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'writer_busy_cycle_deferred'
    assert not (tmp_path / 'health.json').exists()
