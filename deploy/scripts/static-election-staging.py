"""Authorized bounded real FTP/HTTPS staging, synthetic data only. Retains files."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import threading
import time
import io

REPO=Path(__file__).resolve().parents[2]
ROOT=Path(os.environ['RUNNER_TEMP'])/'election-static-staging'
ROOT.mkdir(exist_ok=True)
sys.path.insert(0,str(REPO));sys.path.insert(0,str(REPO/'tests'))
from collector.src import static_election_publish as pub
from collector.src.election_release import canonical,digest,parse,tree,targets
from static_election_fixtures import bundle
from deploy.frontend import error_report

folder=ROOT/'staging-fixtures'
folder.mkdir(exist_ok=True)
if not (folder/'baseline').exists():bundle(folder/'baseline',1)
if not (folder/'candidate').exists():bundle(folder/'candidate',2)
before,after=tree(folder/'baseline'),tree(folder/'candidate')
desc=pub.descriptor(before);sid=digest(canonical(desc));after_id=digest(canonical(pub.descriptor(after)))
old_marker=canonical(parse(before['version.json'])|{'snapshot_id':sid})
reviews={name:digest(raw) for name,raw in after.items() if name.startswith('am/')}
transport=pub.connect('staging');records={'started_at':datetime.now(timezone.utc).isoformat(),'environment':'fixture','production_writes':False,'events':[]}
stop=threading.Event();observations=[]
def observe():
    while not stop.is_set():
        try:
            value=parse(pub.http_read('staging','version.json'))
            if value['snapshot_id'] not in (sid,after_id):raise ValueError('unexpected_fixture_marker')
            observations.append({'snapshot_id':value['snapshot_id']})
        except Exception as error:observations.append(error_report(error))
        stop.wait(0.2)
observer=None
try:
    if transport.metadata(transport.private+'/') is not None:
        raise ValueError('staging_namespace_already_exists')
    print('STAGING: initialize synthetic baseline 137+3',flush=True)
    for index,(name,raw) in enumerate(before.items(),1):
        path=transport.site+'/releases/'+sid+'/'+name
        meta=transport.metadata(path+'.upload')
        pending=(b'' if meta and int(meta.get('size','-1'))==0 else transport.read(path+'.upload',optional=True))
        if pending is not None:
            if not raw.startswith(pending):raise ValueError('unknown_fixture_temporary_bytes')
            if pending==raw and transport.read(path,optional=True) is None:
                transport.ftp.rename(path+'.upload',path)
            else:
                # Own known fixture temporary from the interrupted initialization.
                transport.ftp.delete(path+'.upload')
        transport.put(path,raw)
        if index%25==0:print('Baseline fixture files: '+str(index)+'/140',flush=True)
    transport.put(transport.site+'/version.json',old_marker)
    records['baseline']=pub.verify_public(transport,old_marker,desc)
    transport.directory(transport.private)
    # Two real FTP sessions try the same lock; the second must be refused.
    transport.ftp.mkd(transport.private+'/lock')
    second=pub.connect('staging')
    try:
        try:second.ftp.mkd(second.private+'/lock')
        except Exception as error:records['concurrent_lock_refused']=error_report(error)
        else:raise RuntimeError('duplicate_remote_lock_accepted')
    finally:second.ftp.close()
    transport.ftp.rmd(transport.private+'/lock')
    observer=threading.Thread(target=observe,daemon=True);observer.start()
    print('STAGING: actual truncated fixture transfer, then recovery',flush=True)
    normal=transport.ftp.storbinary;injected=False
    def interrupted(command,stream,*args,**kwargs):
        global injected
        if not injected and '/staging/' in command and '/files/' in command:
            injected=True
            raw=stream.read();normal(command,io.BytesIO(raw[:max(1,len(raw)//2)]),*args,**kwargs)
            raise RuntimeError('injected_fixture_transfer_interruption')
        return normal(command,stream,*args,**kwargs)
    transport.ftp.storbinary=interrupted
    try:
        with transport.lock():pub.activate(transport,after,reviews=reviews)
    except Exception as error:
        if not injected:raise
        records['interrupted_transfer']=error_report(error)
    else:raise RuntimeError('fixture_interruption_not_detected')
    transport.ftp.storbinary=normal
    if transport.read(transport.site+'/version.json')!=old_marker:raise RuntimeError('failure_changed_fixture_marker')
    records['recovery']=pub.recover(transport)
    print('STAGING: publish complete release and verify all 140',flush=True)
    with transport.lock():records['publication']=pub.activate(transport,after,reviews=reviews)
    with transport.lock():records['idempotent_retry']=pub.activate(transport,after,reviews=reviews)
    print('STAGING: rollback and verify all original 140',flush=True)
    with transport.lock():records['rollback']=pub.rollback(transport)
    if transport.read(transport.site+'/version.json')!=old_marker:raise RuntimeError('rollback_fixture_marker_mismatch')
    records['final_baseline']=pub.verify_public(transport,old_marker,desc)
    records['status']='passed'
except Exception as error:
    records['status']='failed';records['error']=error_report(error)
finally:
    stop.set()
    if observer:observer.join(25)
    records['observations']={'count':len(observations),'ids':sorted({r['snapshot_id'] for r in observations if 'snapshot_id' in r}),
        'errors':[r for r in observations if 'snapshot_id' not in r]}
    if records['observations']['errors']:records['status']='failed'
    records['finished_at']=datetime.now(timezone.utc).isoformat()
    transport.ftp.close()
    (ROOT/'staging-trial.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    print(json.dumps(records),flush=True)
raise SystemExit(0 if records['status']=='passed' else 1)
