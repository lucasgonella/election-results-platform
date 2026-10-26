"""Frozen snapshot: approved main publisher, SSH first and safe FTP alternative."""
import argparse,json,hashlib,os,re,subprocess,sys
from pathlib import Path
SOURCE='05ae559c769dd089fa965dc9caf2d1e3b2ac6a32'
SNAPSHOT='200509221fa0e35599b18a669ef1d30ff299254e14e0e917f0c38f3d33f251f6'
def approved():
 repo=os.environ['GITHUB_REPOSITORY'];rows=json.loads(subprocess.check_output(['gh','api','repos/'+repo+'/commits/'+SOURCE+'/check-runs?per_page=100']))['check_runs'];latest={}
 for row in rows:
  if row['name'] not in latest or row['id']>latest[row['name']]['id']:latest[row['name']]=row
 required={'Python Tests','Frontend FTP validation','Municipal pipeline and browser','Election hardening and recovery','Hosting Python 3.6 filesystem contract','transport (3.13)','transport (3.14)','validate (3.13)','validate (3.14)'}
 if any(n not in latest or latest[n]['status']!='completed' or latest[n]['conclusion']!='success' for n in required):raise RuntimeError('approved_main_checks_required')
 comparison=json.loads(subprocess.check_output(['gh','api','repos/'+repo+'/compare/'+SOURCE+'...main']))
 if comparison['status'] not in {'identical','ahead'}:raise RuntimeError('source_must_be_on_main')
def publish_preferred(state,data,attempts):
 from collector.src import biometry_publish as p
 from collector.src.second_round_publish import load,save
 from deploy.ssh_transport import SSHError
 pending=load(state/'pending-publish.json');selection=load(state/'selected-transport.json')
 if pending and (not selection or selection.get('transport') not in {'ssh','ftp'}):raise RuntimeError('pending_transport_not_proven')
 choices=[selection['transport']] if pending else ['ssh','ftp']
 for chosen in choices:
  t=None;os.environ['PUBLICATION_TRANSPORT']=chosen
  save(state/'selected-transport.json',{'transport':chosen})
  try:
   t=p.connect();publisher=p.Publisher(t,state)
   marker=publisher.marker()
   if marker:
    current=json.loads(publisher.verify(marker))
    if current['totals']['processed']>data['totals']['processed'] or current['generated_at']>data['generated_at']:raise RuntimeError('refuse_older_frozen_snapshot')
   receipt=publisher.publish(data);attempts.append({'transport':chosen,'status':receipt['status']});return receipt,chosen
  except SSHError as error:
   attempts.append({'transport':chosen,'status':'failed','error_code':str(error),'operation':getattr(error,'transport_operation',None)})
   safe=(chosen=='ssh' and not pending and load(state/'pending-publish.json') is None
         and str(error)=='ssh_operation_outcome_unknown' and getattr(error,'transport_operation',None) in {'hello','read','metadata'})
   if not safe:raise
  finally:
   if t is not None:t.ftp.close()
 raise RuntimeError('all_publication_transports_failed')
def main():
 parser=argparse.ArgumentParser()
 for name in ['source','request','state','report']:parser.add_argument('--'+name,type=Path,required=True)
 parser.add_argument('--validate-only',action='store_true');args=parser.parse_args()
 if subprocess.check_output(['git','-C',str(args.source),'rev-parse','HEAD'],text=True).strip()!=SOURCE:raise RuntimeError('unapproved_source')
 sys.path.insert(0,str(args.source.resolve()))
 from collector.src.biometry import canonical,validate
 from collector.src.second_round_publish import local_lock
 request=json.loads((args.request/'request.json').read_text());raw=(args.request/'panel.json').read_bytes();data=validate(json.loads(raw))
 if hashlib.sha256(raw).hexdigest()!=SNAPSHOT or request['snapshot_id']!=SNAPSHOT or request['source_commit']!=SOURCE or request['pending_publication'] is not False or request['size']!=len(raw) or request['totals']!=data['totals'] or data['totals']['expected']!=499248 or canonical(data)!=raw:raise RuntimeError('snapshot_validation_failed')
 report={'source_commit':SOURCE,'snapshot_id':SNAPSHOT,'totals':data['totals'],'attempts':[]}
 if args.validate_only:print(json.dumps(report));return
 approved();args.state.mkdir(mode=0o700,parents=True,exist_ok=True)
 try:
  with local_lock(args.state):report['publication'],report['transport']=publish_preferred(args.state,data,report['attempts'])
 except Exception as error:
  code=str(error) if re.fullmatch('[a-z][a-z0-9_]{1,100}',str(error)) else type(error).__name__
  report.update(status='failed',error_type=type(error).__name__,error_code=code)
  args.report.write_text(json.dumps(report,indent=2));print(json.dumps(report));raise SystemExit(1)
 args.report.write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':main()
