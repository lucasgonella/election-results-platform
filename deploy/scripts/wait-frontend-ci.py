"""Wait for successful checks at exact deployment SHA; no deploy on CI failure."""
import argparse
import json
import os
import subprocess
import time


def relevant(path, component):
    shared = {'deploy/frontend.py', 'deploy/frontend-targets.json', 'deploy/frontend-requirements.txt',
              'deploy/scripts/wait-frontend-ci.py', '.github/workflows/deploy-frontend-ftp.yml'}
    caller = '.github/workflows/deploy-'+('portal' if component == 'portal' else 'goias')+'-ftp.yml'
    if path in shared or path == caller:
        return True
    root = 'web/public/eleicoes/' + ('goias/raio-x/' if component == 'raio-x' else '')
    if not path.startswith(root):
        return False
    relative = path.removeprefix(root)
    return not (relative.startswith(('data/', 'goias/')) or relative.endswith('.md'))


def ready(runs):
    required = {'Python Tests', 'Frontend FTP validation'}
    latest = {}
    for run in runs:
        name = run['name']
        if name not in latest or run['id'] > latest[name]['id']:
            latest[name] = run
    for name in required:
        run = latest.get(name)
        if not run or run['status'] != 'completed':
            return False
        if run['conclusion'] != 'success':
            raise RuntimeError('required_ci_failed: '+name)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--commit', required=True)
    parser.add_argument('--component', choices=['portal', 'raio-x'], required=True)
    args = parser.parse_args()
    for _ in range(48):
        raw = subprocess.check_output(['gh', 'api', 'repos/'+os.environ['GITHUB_REPOSITORY']+'/commits/'+args.commit+'/check-runs?per_page=100'])
        if ready(json.loads(raw)['check_runs']):
            head = subprocess.check_output(['gh', 'api', 'repos/'+os.environ['GITHUB_REPOSITORY']+'/git/ref/heads/main'])
            if json.loads(head)['object']['sha'] != args.commit:
                comparison = subprocess.check_output(['gh', 'api', 'repos/'+os.environ['GITHUB_REPOSITORY']+'/compare/'+args.commit+'...main'])
                data = json.loads(comparison)
                # A finance-only bot push must not cancel the latest visual deploy.
                # Refuse stale visual code, divergent history and truncated inventories.
                files = data['files']
                if data['status'] not in {'ahead', 'identical'} or len(files) >= 300 or any(
                    relevant(entry['filename'], args.component) or relevant(entry.get('previous_filename', ''), args.component)
                    for entry in files
                ):
                    raise RuntimeError('obsolete_component_commit')
            print('CI approved for exact commit '+args.commit)
            return
        time.sleep(10)
    raise RuntimeError('required_ci_timeout')


if __name__ == '__main__':
    main()
