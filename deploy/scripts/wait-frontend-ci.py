"""Wait for successful checks at exact deployment SHA; no deploy on CI failure."""
import argparse
import json
import os
import subprocess
import time


def ready(runs):
    required = {'Python Tests', 'validate (3.13)', 'validate (3.14)', 'Frontend FTP validation'}
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
    args = parser.parse_args()
    for _ in range(48):
        raw = subprocess.check_output(['gh', 'api', 'repos/'+os.environ['GITHUB_REPOSITORY']+'/commits/'+args.commit+'/check-runs?per_page=100'])
        if ready(json.loads(raw)['check_runs']):
            print('CI approved for exact commit '+args.commit)
            return
        time.sleep(10)
    raise RuntimeError('required_ci_timeout')


if __name__ == '__main__':
    main()
