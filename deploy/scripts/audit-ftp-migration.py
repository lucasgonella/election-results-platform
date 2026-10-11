"""Read-only SSH/HTTP/FTP diagnostics; prints metadata, never credentials.

No collectors, endpoints, remote writes or systemd mutations are executed.
FTP login is optional and uses existing process environment credentials only.
"""
import argparse
import concurrent.futures
import ftplib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request
from dotenv import dotenv_values


LOCAWEB = r'''
import hashlib,json,os,pathlib,subprocess
home=pathlib.Path.home(); site=home/'public_html/data'
marker_raw=(site/'version.json').read_bytes(); marker=json.loads(marker_raw)
sid=marker.get('snapshot_id','')
if len(sid)!=64 or any(c not in '0123456789abcdef' for c in sid): raise RuntimeError('invalid_marker')
release=site/'releases'/sid
manifest=json.loads((release/'manifest.json').read_bytes())
items={}; problems=[]
for item in manifest['results']:
 p=item['path']
 if len(pathlib.PurePosixPath(p).parts)!=2 or '..' in pathlib.PurePosixPath(p).parts: raise RuntimeError('invalid_path')
 raw=(release/p).read_bytes(); payload=json.loads(raw)
 items[p]={'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw),'manifest':item,'snapshot':payload['snapshot'],'election':payload['election'],'scope':payload['scope'],'office_code':payload['office']['code'],'candidate_count':len(payload['candidates'])}
 snapshot=dict(payload['snapshot']); snapshot.pop('captured_at',None); snapshot['tse_idg']=str(snapshot['tse_idg'])
 items[p]['source_hash']=hashlib.sha256(json.dumps([snapshot,payload['candidates'],payload['office']],sort_keys=True,separators=(',',':')).encode()).hexdigest()
 if payload['snapshot']['tse_idg']!=item['tse_idg'] or payload['snapshot']['captured_at']!=item['captured_at']: problems.append(p)
meta={}
for p in ['manifest.json','version.json','alerts.json']:
 raw=(release/p).read_bytes(); value=json.loads(raw)
 meta[p]={'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw),'environment':value.get('environment'),'generated_at':value.get('generated_at')}
 if p=='alerts.json': meta[p]['alerts_sha256']=hashlib.sha256(json.dumps(value.get('alerts'),sort_keys=True,separators=(',',':')).encode()).hexdigest()
processes=[]
for entry in pathlib.Path('/proc').iterdir():
 if not entry.name.isdigit(): continue
 try:
  if (entry/'comm').read_text().strip()=='php-fpm':
   processes.append({'pid':entry.name,'uid':(entry/'status').read_text().split('Uid:')[1].splitlines()[0].strip(),'executable':os.readlink(str(entry/'exe'))})
 except (OSError,IndexError): pass
paths={}
for name in ['public_html','public_html/data','.election-publisher','.election-publisher/hmac.key','.election-publisher/staging','.election-publisher/backups','includes']:
 p=home/name
 if p.exists():
  s=p.stat(); paths[name]={'resolved':str(p.resolve()),'uid':s.st_uid,'gid':s.st_gid,'mode':oct(s.st_mode&0o777),'device':s.st_dev,'inode':s.st_ino}
print(json.dumps({'home':str(home),'paths':paths,'marker':marker,'marker_sha256':hashlib.sha256(marker_raw).hexdigest(),'release':str(release),'results':items,'metadata':meta,'mismatches':problems,'stable_marker':marker_raw==(site/'version.json').read_bytes(),'php_processes':processes,'inventories_present':[(release/p).exists() for p in ['inventory.json','inventory.sig']]}))
'''

APP01 = r'''
import hashlib,json,pathlib,subprocess
root=pathlib.Path('/var/lib/election-results-platform/live')
out={}
for name in ['state','pending','stage']:
 directory=root/name; values={}; hashes={}
 for p in directory.glob('*.json'):
  raw=p.read_bytes(); hashes[p.name]=hashlib.sha256(raw).hexdigest()
  if p.name=='manifest.json': values['manifest']=json.loads(raw)
  if p.name=='version.json': values['version']=json.loads(raw)
  if p.name=='state-meta.json': values['state_meta']=json.loads(raw)
  if p.name=='alerts.json': values['alerts_sha256']=hashlib.sha256(json.dumps(json.loads(raw).get('alerts'),sort_keys=True,separators=(',',':')).encode()).hexdigest()
  if p.name=='target-state.json':
   values['targets']={v['path']:{k:v.get(k) for k in ['tse_idg','path','etag','last_modified']} for v in json.loads(raw).values() if 'path' in v}
 values['hashes']=hashes
 values['stable'] = all(hashlib.sha256((directory/p).read_bytes()).hexdigest()==h for p,h in hashes.items())
 values['result_files']={str(p.relative_to(directory)):hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.glob('*/*.json')}
 values['sources']={}
 for p in directory.glob('*/*.json'):
  payload=json.loads(p.read_bytes()); snapshot=dict(payload['snapshot']); snapshot.pop('captured_at',None); snapshot['tse_idg']=str(snapshot['tse_idg'])
  values['sources'][str(p.relative_to(directory))]={'snapshot':snapshot,'source_hash':hashlib.sha256(json.dumps([snapshot,payload['candidates'],payload['office']],sort_keys=True,separators=(',',':')).encode()).hexdigest()}
 out[name]=values
env=pathlib.Path('/etc/election-results-platform/collector.env')
allowed=['TSE_ENVIRONMENT','TSE_CYCLE','TSE_ROUND','LIVE_PUBLISH_STATE_DIR','LIVE_PUBLISH_STAGE_DIR','LIVE_PUBLISH_SCRIPT','PUBLISH_AFTER_COLLECT','ELECTION_HTTPS_KEY_FILE','ELECTION_HMAC_KEY_FILE','ELECTION_HTTPS_URL']
values={}
for line in env.read_text().splitlines():
 if '=' not in line or line.startswith('#'): continue
 k,v=line.split('=',1)
 if k in allowed: values[k]=v.strip().strip('"').strip("'")
out['operational']=values
out['ftp_variable_presence']={k: any(line.startswith(k+'=') for line in env.read_text().splitlines()) for k in ['LOCAWEB_FTP_HOST','LOCAWEB_FTP_USER','LOCAWEB_FTP_PASSWORD','LOCAWEB_FTP_ELECTION_INBOX_DIR']}
out['configuration_hashes']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [env,pathlib.Path('/etc/systemd/system/election-live-publisher.service.d/https.conf')] if p.exists()}
def unit(name):
 lines=subprocess.check_output(['systemctl','cat',name],universal_newlines=True).splitlines()
 return '\n'.join(line if not line.startswith('Environment=') or line.split('=',2)[1] in ['LIVE_PUBLISH_SCRIPT','PYTHONDONTWRITEBYTECODE','PYTHONUNBUFFERED'] else 'Environment=<redacted>' for line in lines)
out['unit']=unit('election-live-publisher.service')
out['collector_unit']=unit('election-collector.service')
out['timer']=unit('election-live-publisher.timer')
out['crontabs']={}
for user in ['root','gonella','electioncollector']:
 result=subprocess.run(['crontab','-u',user,'-l'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
 lines=[line for line in result.stdout.splitlines() if line.strip() and not line.startswith('#')]
 out['crontabs'][user]={'returncode':result.returncode,'entries':len(lines),'election_entries':sum('election' in line or 'publish-results' in line for line in lines)}
out['cron_files']=[str(p) for directory in ['cron.d','cron.daily','cron.hourly','cron.weekly','cron.monthly'] for p in (pathlib.Path('/etc')/directory).glob('*') if p.is_file() and any(word in p.read_text(errors='replace') for word in ['election-results-platform','publish-results','live-publisher'])]
out['php_cli_available']=subprocess.run(['sh','-c','command -v php'],stdout=subprocess.PIPE,stderr=subprocess.PIPE).returncode==0
key=pathlib.Path('/etc/election-results-platform/secrets/hmac.key')
if key.exists():
 s=key.stat(); out['key_metadata']={'mode':oct(s.st_mode&0o777),'uid':s.st_uid,'gid':s.st_gid}
print(json.dumps(out))
'''


def ssh(host, source, sudo=False):
    command = 'sudo -n /usr/bin/python3 -' if sudo else '/usr/bin/python3 -'
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', host, command],
                            input=source, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError('ssh_audit_failed_' + host)  # don't echo arbitrary remote stderr
    return json.loads(result.stdout)


def ftp_readonly(credentials_file=None):
    names=['LOCAWEB_FTP_HOST','LOCAWEB_FTP_USER','LOCAWEB_FTP_PASSWORD']
    values=dotenv_values(credentials_file,interpolate=False) if credentials_file else os.environ
    if str(values.get('LOCAWEB_FTP_PORT','21')) != '21':
        return {'status':'invalid_port'}
    if not all(values.get(name) for name in names):
        # This public host is the existing SSH alias's hostname. No login attempt
        # and no PWD inference are made without the existing credentials.
        probe=ftplib.FTP()
        try:
            probe.connect('ftp.afgnet.com.br',21,timeout=20)
            try: features=probe.sendcmd('FEAT').splitlines()
            except ftplib.all_errors: features=[]
            return {'status':'credentials_not_available_in_session','port21_reachable':True,'features':features}
        except ftplib.all_errors:
            return {'status':'credentials_not_available_in_session','port21_reachable':False}
        finally: probe.close()
    client=ftplib.FTP()
    try:
        client.connect(values[names[0]],21,timeout=20)
        client.login(values[names[1]],values[names[2]])
        out={'status':'authenticated','pwd':client.pwd(),'system':client.sendcmd('SYST')}
        # Selective metadata only; never list private directory contents or RETR.
        for path in ['.','..','public_html','.election-publisher','.election-publisher/hmac.key',
                     '.election-publisher/ftp-config.json','public_html/api/election-publish.php',
                     'public_html/api/election-ftp-control.php','includes','ftp-inbox',
                     'ftp-inbox/elections','ftp-inbox/code']:
            try:
                out[path]={'mlst':client.sendcmd('MLST '+path)}
            except ftplib.all_errors:
                out[path]={'status':'listing_unavailable'}
        return out
    finally:
        client.close()


def validate_php_readonly():
    source=(Path(__file__).resolve().parents[1]/'locaweb/ftp-publication.php').read_text(encoding='utf-8')
    source += r'''
try {
 $site='/home/storage/4/b7/e0/afgnet1/public_html/data';
 $marker=fp_json($site.'/version.json');
 $water=fp_validate_release($site.'/releases/'.$marker['snapshot_id'],['environment'=>'oficial','round'=>1]);
 echo json_encode(['status'=>'validated_readonly','targets'=>count($water),'php_version'=>PHP_VERSION,'flock_available'=>function_exists('flock'),'fsync_available'=>function_exists('fsync'),'rename_available'=>function_exists('rename')]);
} catch (Throwable $error) { echo json_encode(['status'=>'validation_failed','error_type'=>get_class($error),'error_code'=>$error instanceof RuntimeException ? $error->getMessage() : 'validation_error']); }
'''
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','afg-locaweb','/usr/bin/php8.4 -n'],
        input=source,capture_output=True,text=True,timeout=90)
    if result.returncode: raise RuntimeError('php_readonly_audit_failed')
    return json.loads(result.stdout)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--ftp',action='store_true')
    parser.add_argument('--ftp-credentials-file',type=Path)
    parser.add_argument('--public-hashes',action='store_true')
    parser.add_argument('--validate-php',action='store_true')
    args=parser.parse_args()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        remote=pool.submit(ssh,'afg-locaweb',LOCAWEB)
        app=pool.submit(ssh,'app01',APP01,True)
        report={'locaweb':remote.result(),'app01':app.result()}
    selected=report['locaweb']['marker']['snapshot_id']
    with urllib.request.urlopen('https://afgnet.com.br/data/version.json',timeout=30) as response:
        raw=response.read(); public=json.loads(raw)
        report['public']={'marker':public,'sha256':hashlib.sha256(raw).hexdigest(),'headers':{k:response.headers.get(k) for k in ['Server','X-Powered-By','Cache-Control','Last-Modified']}}
    results=report['locaweb']['results']
    if args.public_hashes:
        def public_hash(path):
            with urllib.request.urlopen('https://afgnet.com.br/data/releases/'+selected+'/'+path,timeout=30) as response:
                return path,hashlib.sha256(response.read()).hexdigest()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            hashes=dict(pool.map(public_hash,list(results)+['manifest.json','version.json','alerts.json']))
        expected={p:v['sha256'] for p,v in results.items()}
        expected.update({p:v['sha256'] for p,v in report['locaweb']['metadata'].items()})
        report['public_hash_verification']={'checked':len(hashes),'mismatches':[p for p,h in hashes.items() if h!=expected[p]]}
    for name in ['state','pending']:
        live=report['app01'][name]
        entries={e['path']:e for e in live.get('manifest',{}).get('results',[])}
        report[name+'_comparison']={
            'manifest_differences':[p for p,v in results.items() if entries.get(p)!=v['manifest']],
            'target_idg_differences':[p for p,v in results.items() if live.get('targets',{}).get(p,{}).get('tse_idg')!=v['snapshot']['tse_idg']],
            'target_count':len(live.get('targets',{}))}
        report[name+'_comparison']['alerts_equal']=live.get('alerts_sha256')==report['locaweb']['metadata']['alerts.json'].get('alerts_sha256')
    report['public_matches_ssh']=public.get('snapshot_id')==selected and report['public']['sha256']==report['locaweb']['marker_sha256']
    report['stage_source_comparison']={}
    for path,value in report['app01']['stage'].get('sources',{}).items():
        old=results.get(path,{})
        report['stage_source_comparison'][path]={'same_source_hash':old.get('source_hash')==value['source_hash'],
            'same_idg':str(old.get('snapshot',{}).get('tse_idg'))==value['snapshot']['tse_idg'],
            'same_source_time':old.get('snapshot',{}).get('generated_at')==value['snapshot'].get('generated_at'),
            'snapshot_fields_changed':[k for k,v in value['snapshot'].items() if k!='tse_idg' and v!=old.get('snapshot',{}).get(k)]}
    if args.ftp: report['ftp']=ftp_readonly(args.ftp_credentials_file)
    if args.validate_php: report['php_readonly_validation']=validate_php_readonly()
    args.report.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'report':str(args.report),'snapshot_id':selected,'results':len(results),
        'public_matches_ssh':report['public_matches_ssh'],'state_differences':len(report['state_comparison']['manifest_differences']),
        'pending_differences':len(report['pending_comparison']['manifest_differences']),'ftp':report.get('ftp',{}).get('status')}))


if __name__=='__main__':
    try: main()
    except Exception as error:
        print(json.dumps({'status':'failed','error_type':type(error).__name__}))
        raise SystemExit(1)
