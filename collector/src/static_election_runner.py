"""Single app01 writer with preserved legacy state and per-cycle workspaces."""
from __future__ import annotations
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil

from deploy.frontend import error_report
from .election_release import META, canonical, digest, entries, hashes, parse, prepare, source, targets, tree, validate_release
from .static_election_publish import activate, compare, connect, descriptor, verify_public


def save(path, value):
    temporary=path.with_name(path.name+'.'+secrets.token_hex(8)+'.tmp')
    with temporary.open('xb') as stream:
        stream.write(canonical(value));stream.flush();os.fsync(stream.fileno())
    temporary.replace(path)


def root_path():
    root=Path(os.environ['ELECTION_STATIC_STATE_DIR'])
    legacy=Path(os.environ.get('ELECTION_LEGACY_STATE_DIR','/var/lib/election-results-platform/live')).resolve()
    if (root.is_symlink() or root.resolve().is_relative_to(legacy) or legacy.is_relative_to(root.resolve())):
        raise ValueError('static_state_overlaps_legacy')
    return root


def accept_checkpoint(root, package, receipt):
    values=tree(package/'candidate');desc=descriptor(values)
    sid=digest(canonical(desc))
    if receipt['snapshot_id']!=sid or receipt['files']!=140:
        raise ValueError('local_receipt_mismatch')
    destination=root/'generations'/sid
    if not destination.exists():
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copytree(package,destination)
    elif tree(destination)!=tree(package):
        raise ValueError('local_immutable_collision')
    save(root/'current.json',{'snapshot_id':sid,'descriptor':desc,'package':str(destination),
        'published_at':receipt.get('published_at',receipt['verified_at'])})
    save(root/'health.json',{'status':'published','snapshot_id':sid,'published_at':receipt.get('published_at',receipt['verified_at']),
        'public_verified_at':receipt['verified_at'],'collected_at':desc['generated_at'],'eligible_changes':0})


def run_cycle(root, *, collect=None):
    current=parse((root/'current.json').read_bytes())
    previous=Path(current['package'])
    if not previous.resolve().is_relative_to((root/'generations').resolve()):
        raise ValueError('unsafe_checkpoint_location')
    baseline=previous/'candidate';before=tree(baseline)
    desc=descriptor(before)
    if desc!=current['descriptor'] or digest(canonical(desc))!=current['snapshot_id']:
        raise ValueError('local_release_mismatch')
    cycle=root/'cycles'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+secrets.token_hex(4))
    cycle.mkdir(parents=True,exist_ok=False)
    work=cycle/'collection';work.mkdir()
    # prepare may remove pending/stage; both are absent in this brand-new workspace.
    # The original /live directories and all previous cycles remain untouched.
    shutil.copytree(previous/'checkpoint',work/'state')
    if collect is None:
        from . import live_publisher
        original=os.environ.get('LIVE_PUBLISH_STATE_DIR')
        try:
            os.environ['LIVE_PUBLISH_STATE_DIR']=str(work)
            collection=live_publisher.prepare()
        finally:
            if original is None:os.environ.pop('LIVE_PUBLISH_STATE_DIR',None)
            else:os.environ['LIVE_PUBLISH_STATE_DIR']=original
    else:
        collection=collect(work)
    stage=tree(work/'stage');rows=entries(parse(stage['manifest.json']))
    from .election_release import validate_result
    selected=[];quarantine={}
    for name in stage.keys()-META:
        validate_result(name,parse(stage[name]),rows[name],desc['environment'],desc['round'])
        if source(parse(before[name]))==source(parse(stage[name])):continue
        proposed=before|{name:stage[name]}
        try:compare(before,proposed)
        except ValueError as error:
            quarantine[name]={'reason':str(error),'before':parse(before[name])['snapshot'],
                'proposed':parse(stage[name])['snapshot'],'proposed_sha256':digest(stage[name])}
        else:selected.append(name)
    save(cycle/'review-required.json',quarantine)
    transport=connect('production')
    try:
        marker=transport.read(transport.site+'/version.json')
        if parse(marker)['snapshot_id']!=current['snapshot_id']:
            raise ValueError('reconcile_local_public_state_before_collection_commit')
        if selected:
            marker_file=cycle/'baseline-marker.json';marker_file.write_bytes(marker)
            package=cycle/'package'
            prepare(baseline=baseline,marker=marker_file,stage=work/'stage',state=work/'state',pending=work/'pending',
                    output=package,include=selected)
            # No network transfer until the complete release and checkpoint are saved.
            save(root/'in-flight.json',{'package':str(package),'selected':selected,'prepared_at':parse(stage['version.json'])['generated_at']})
            with transport.lock():receipt=activate(transport,tree(package/'candidate'))
            accept_checkpoint(root,package,receipt)
            # Keep completed job information; no directory or pending file is deleted.
            save(root/'in-flight.json',{'status':'complete','snapshot_id':receipt['snapshot_id']})
        else:
            receipt=verify_public(transport,marker,desc)
        health={'status':'published' if selected else 'unchanged','snapshot_id':receipt['snapshot_id'],
            'published_at':parse((root/'current.json').read_bytes())['published_at'],
            'public_verified_at':receipt['verified_at'],'collected_at':parse(stage['version.json'])['generated_at'],
            'eligible_changes':0,'review_required':quarantine,'selected':selected,'cycle':str(cycle)}
        save(root/'health.json',health)
        return health
    finally:transport.ftp.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['adopt','cycle','reconcile'])
    parser.add_argument('--package',type=Path)
    args=parser.parse_args()
    root=root_path();root.mkdir(parents=True,exist_ok=True)
    import fcntl
    with (root/'runner.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            job=root/'in-flight.json'
            if args.operation!='reconcile' and job.exists() and parse(job.read_bytes()).get('status')!='complete':
                raise ValueError('interrupted_job_requires_reconciliation')
            if args.operation=='adopt':
                if (root/'current.json').exists():raise ValueError('static_state_already_adopted')
                values=tree(args.package/'candidate');desc=descriptor(values);sid=digest(canonical(desc))
                transport=connect('production')
                try:
                    marker=transport.read(transport.site+'/version.json')
                    if parse(marker)['snapshot_id']!=sid:raise ValueError('adoption_public_mismatch')
                    receipt=verify_public(transport,marker,desc)
                    remote=parse(transport.read(transport.private+'/current.json'))
                    if remote['snapshot_id']!=sid:raise ValueError('adoption_remote_checkpoint_mismatch')
                    receipt['published_at']=remote['published_at']
                    accept_checkpoint(root,args.package,receipt);result={'status':'adopted','snapshot_id':sid}
                finally:transport.ftp.close()
            elif args.operation=='reconcile':
                queued=parse(job.read_bytes());package=Path(queued['package'])
                if not package.resolve().is_relative_to((root/'cycles').resolve()):raise ValueError('unsafe_reconciliation_package')
                values=tree(package/'candidate');desc=descriptor(values);sid=digest(canonical(desc))
                transport=connect('production')
                try:
                    if transport.metadata(transport.private+'/lock/') is not None:raise ValueError('recover_remote_transaction_first')
                    marker=transport.read(transport.site+'/version.json')
                    if parse(marker)['snapshot_id']!=sid:raise ValueError('reconciliation_requires_matching_published_job')
                    receipt=verify_public(transport,marker,desc)
                    remote=parse(transport.read(transport.private+'/current.json'))
                    if remote['snapshot_id']!=sid:raise ValueError('remote_checkpoint_not_confirmed')
                    receipt['published_at']=remote['published_at'];accept_checkpoint(root,package,receipt)
                    save(job,{'status':'complete','snapshot_id':sid});result={'status':'reconciled','snapshot_id':sid}
                finally:transport.ftp.close()
            else:result=run_cycle(root)
            print(json.dumps(result));return 0
        except Exception as error:
            previous=parse((root/'health.json').read_bytes()) if (root/'health.json').exists() else {}
            result=previous|{'status':'failed','failed_at':datetime.now(timezone.utc).isoformat(),**error_report(error)}
            save(root/'health.json',result);print(json.dumps(result));return 1


if __name__=='__main__':
    raise SystemExit(main())
