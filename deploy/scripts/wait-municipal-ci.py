"""Exact SHA checks and municipal source freshness. No tokens in output/argv."""
import argparse,json,os,subprocess,time

def main():
    p=argparse.ArgumentParser();p.add_argument('--commit',required=True);a=p.parse_args()
    required={'Python Tests','Frontend FTP validation','Municipal pipeline and browser'}
    prefix='repos/'+os.environ['GITHUB_REPOSITORY']
    for _ in range(90):
        runs=json.loads(subprocess.check_output(['gh','api',prefix+'/commits/'+a.commit+'/check-runs?per_page=100']))['check_runs']
        latest={}
        for run in runs:
            if run['name'] not in latest or run['id']>latest[run['name']]['id']:latest[run['name']]=run
        if all(name in latest and latest[name]['status']=='completed' for name in required):
            if any(latest[name]['conclusion']!='success' for name in required):raise RuntimeError('municipal_required_ci_failed')
            head=json.loads(subprocess.check_output(['gh','api',prefix+'/git/ref/heads/main']))['object']['sha']
            if head!=a.commit:
                comparison=json.loads(subprocess.check_output(['gh','api',prefix+'/compare/'+a.commit+'...main']))
                paths=[entry['filename'] for entry in comparison['files']]
                if comparison['status'] not in ('ahead','identical') or len(paths)>=300 or any((path in {'collector/src/parser.py','collector/src/tse_client.py','collector/src/election_release.py','collector/src/second_round_publish.py','deploy/frontend.py'} or path.startswith(('collector/src/municipal','tools/municipal','.github/workflows/municipal','deploy/scripts/wait-municipal'))) for path in paths):
                    raise RuntimeError('municipal_obsolete_source_commit')
            print('Municipal CI approved for exact commit '+a.commit);return
        time.sleep(10)
    raise RuntimeError('municipal_ci_timeout')
if __name__=='__main__':main()
