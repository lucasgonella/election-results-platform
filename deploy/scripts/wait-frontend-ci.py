"""Wait for successful checks at exact deployment SHA; no deploy on CI failure."""
import argparse
import json
import os
import subprocess
import time


def relevant(path, component):
    shared = {'deploy/frontend.py', 'deploy/scripts/recover-frontend-owned-actions.py', 'deploy/frontend-targets.json', 'deploy/frontend-requirements.txt',
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


FINANCE_EXPORT = 'web/public/eleicoes/goias/raio-x/data/go-2026.json'


def approved_finance_ancestor(commit):
    """Accept only an already-CI-approved ancestor behind finance-data-only bot commits.

    GITHUB_TOKEN pushes do not trigger push workflows. Never treat an untested
    code, workflow or frontend change as approved merely because a prior SHA passed.
    """
    repository = os.environ['GITHUB_REPOSITORY']
    cursor = commit
    for _ in range(20):
        record = json.loads(subprocess.check_output(
            ['gh', 'api', 'repos/' + repository + '/commits/' + cursor]))
        parents = record.get('parents', [])
        files = record.get('files', [])
        if (len(parents) != 1 or len(files) != 1
                or files[0].get('filename') != FINANCE_EXPORT
                or files[0].get('status') not in {'modified', 'added'}
                or (record.get('author') or {}).get('login') != 'github-actions[bot]'):
            return None
        cursor = parents[0]['sha']
        response = subprocess.check_output(
            ['gh', 'api', 'repos/' + repository + '/commits/' + cursor + '/check-runs?per_page=100'])
        if ready(json.loads(response)['check_runs']):
            return cursor
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--commit', required=True)
    parser.add_argument('--component', choices=['portal', 'raio-x'], required=True)
    args = parser.parse_args()
    for attempt in range(48):
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
        # A finance export published with GITHUB_TOKEN does not start push CI.
        # Verify the exact main tip before considering its trusted ancestry.
        # Missing checks are never automatically considered successful.
        if attempt == 0:
            head = json.loads(subprocess.check_output(
                ['gh', 'api', 'repos/'+os.environ['GITHUB_REPOSITORY']+'/git/ref/heads/main']))
            if head['object']['sha'] == args.commit:
                ancestor = approved_finance_ancestor(args.commit)
                if ancestor:
                    confirmation = json.loads(subprocess.check_output(
                        ['gh', 'api', 'repos/'+os.environ['GITHUB_REPOSITORY']+'/git/ref/heads/main']))
                    if confirmation['object']['sha'] != args.commit:
                        raise RuntimeError('obsolete_component_commit')
                    print('CI approved for ancestor '+ancestor+'; intervening changes are finance-only bot exports')
                    return
        time.sleep(10)
    raise RuntimeError('required_ci_timeout')


if __name__ == '__main__':
    main()
