"""Publish one validated snapshot with the unchanged approved main publisher."""
import argparse,base64,hashlib,json,os,shlex,subprocess,sys
from pathlib import Path
SOURCE='4a67643483eacd3069592982c23083b3bb42d678'
SNAPSHOT='607d602f5824960437c3b4852ebd9590a21391d3cfabb7f724a73e5a5c199e09'
KEYS={'actions':'SHA256:BXzAxa303HyBbocnamepihSPtgjyD1ihwNMWI3FvsMw','first':'SHA256:IaciekAoWWuF/My/Ne+Rwr94JBzFHKBI+nClPgDxCUE','second':'SHA256:bZ3ut7qM1gUehV9pv3jzb9KzbGriS0xFkGjHfEUS2h0'}
def approved():
 repo=os.environ['GITHUB_REPOSITORY']
 rows=json.loads(subprocess.check_output(['gh','api','repos/'+repo+'/commits/'+SOURCE+'/check-runs?per_page=100']))['check_runs']
 required={'Python Tests','Frontend FTP validation','Municipal pipeline and browser','Election hardening and recovery','Hosting Python 3.6 filesystem contract','transport (3.13)','transport (3.14)'}
 latest={}
 for row in rows:
  if row['name'] not in latest or row['id']>latest[row['name']]['id']:latest[row['name']]=row
 if any(n not in latest or latest[n]['status']!='completed' or latest[n]['conclusion']!='success' for n in required):raise RuntimeError('approved_main_checks_required')
 ancestry=json.loads(subprocess.check_output(['gh','api','repos/'+repo+'/compare/'+SOURCE+'...main']))
 if ancestry['status'] not in {'identical','ahead'}:raise RuntimeError('source_must_be_on_main')
def inspect_keys():
 from deploy.ssh_transport import SSHSession
 session=SSHSession('biometry-2')
 try:
  public=subprocess.check_output(['ssh-keygen','-y','-P','','-f',str(session.identity)])
  fingerprint='SHA256:'+base64.b64encode(hashlib.sha256(base64.b64decode(public.split()[1],validate=True)).digest()).decode().rstrip('=')
  code="""import os,json,shlex,hashlib,base64
found=[]
with open(os.path.expanduser('~/.ssh/authorized_keys')) as stream:
 for line in stream:
  fields=shlex.split(line,comments=True)
  for i,field in enumerate(fields[:-1]):
   if field in ('ssh-ed25519','ssh-rsa','ecdsa-sha2-nistp256','ecdsa-sha2-nistp384','ecdsa-sha2-nistp521'):
    raw=base64.b64decode(fields[i+1],validate=True)
    found.append('SHA256:'+base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('='))
    break
print(json.dumps({'fingerprints':found}))
"""
  result=subprocess.run(session.options+[session.destination,'/usr/bin/python3 -c '+shlex.quote(code)],capture_output=True,timeout=45)
  if result.returncode:return {'status':'inspection_failed','runner_fingerprint':fingerprint}
  found=json.loads(result.stdout)['fingerprints']
  return {'status':'verified','runner_fingerprint':fingerprint,'runner_matches_app01_actions':fingerprint==KEYS['actions'],'authorized_keys_present':{name:fp in found for name,fp in KEYS.items()},'authorized_key_count':len(found)}
 finally:session.shutdown()
def main():
 parser=argparse.ArgumentParser()
 for name in ['source','request','state','report']:parser.add_argument('--'+name,type=Path,required=True)
 parser.add_argument('--validate-only',action='store_true');args=parser.parse_args()
 if subprocess.check_output(['git','-C',str(args.source),'rev-parse','HEAD'],text=True).strip()!=SOURCE:raise RuntimeError('unapproved_publisher_source')
 sys.path.insert(0,str(args.source.resolve()))
 from collector.src.biometry import canonical,validate
 from collector.src.biometry_publish import publish
 from collector.src.second_round_publish import local_lock
 raw=(args.request/'panel.json').read_bytes();request=json.loads((args.request/'request.json').read_bytes());data=validate(json.loads(raw))
 if hashlib.sha256(raw).hexdigest()!=SNAPSHOT or request['snapshot_id']!=SNAPSHOT or request['source_commit']!=SOURCE or request['pending_publication'] is not False or request['size']!=len(raw) or request['totals']!=data['totals'] or data['totals']['expected']!=499248 or canonical(data)!=raw:raise RuntimeError('snapshot_validation_failed')
 report={'source_commit':SOURCE,'snapshot_id':SNAPSHOT,'totals':data['totals']}
 if args.validate_only:print(json.dumps(report));return
 approved();args.state.mkdir(mode=0o700,parents=True,exist_ok=True)
 with local_lock(args.state):report['publication']=publish(args.state,data)
 args.report.write_text(json.dumps(report,indent=2));print(json.dumps(report))
 try:report['ssh_keys']=inspect_keys()
 except Exception as error:report['ssh_keys']={'status':'inspection_failed','error_type':type(error).__name__}
 args.report.write_text(json.dumps(report,indent=2));print(json.dumps({'ssh_keys':report['ssh_keys']}))
if __name__=='__main__':main()
