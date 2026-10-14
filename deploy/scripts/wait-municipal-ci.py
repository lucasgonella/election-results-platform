"""Require tested municipal code, including after an unrelated finance bot push."""
import argparse
import json
import os
import re
import subprocess
import time

REQUIRED = {'Python Tests', 'Frontend FTP validation', 'Municipal pipeline and browser'}
FINANCE_EXPORT = 'web/public/eleicoes/goias/raio-x/data/go-2026.json'


def latest_checks(data):
    runs = data['check_runs']
    if data.get('total_count', len(runs)) > len(runs):
        raise RuntimeError('municipal_ci_inventory_truncated')
    latest = {}
    for run in runs:
        if run['name'] in REQUIRED and (run['name'] not in latest or run['id'] > latest[run['name']]['id']):
            latest[run['name']] = run
    return latest


def successful(checks):
    if any(run['status'] == 'completed' and run['conclusion'] != 'success' for run in checks.values()):
        raise RuntimeError('municipal_required_ci_failed')
    return all(name in checks and checks[name]['status'] == 'completed' for name in REQUIRED)


def finance_only(comparison):
    files = comparison['files']
    return (comparison['status'] == 'ahead' and 0 < len(files) < 300
            and all(entry['filename'] == FINANCE_EXPORT
                    and entry.get('previous_filename', FINANCE_EXPORT) == FINANCE_EXPORT for entry in files))


def commit_checks(commit, api):
    path = '/commits/'+commit+'/check-runs?per_page=100'
    data = api(path)
    runs = {run['id']: run for run in data['check_runs']}
    total = data.get('total_count', len(runs))
    for page in range(2, 11):
        if len(runs) >= total:
            break
        more = api(path+'&page='+str(page))
        total = max(total, more.get('total_count', total))
        runs.update((run['id'], run) for run in more['check_runs'])
        if not more['check_runs']:
            break
    return latest_checks({'check_runs': list(runs.values()), 'total_count': total})


def approved_commit(commit, api):
    checks = commit_checks(commit, api)
    if checks:
        return commit if successful(checks) else None
    # GITHUB_TOKEN exports do not trigger new CI. Reuse an approved ancestor
    # only when the complete tree diff contains this one financial JSON.
    # Never inherit approval across changed code, tests, requirements or renames.
    ancestor = commit
    for _ in range(20):
        parents = api('/commits/'+ancestor)['parents']
        if not parents:
            return None
        ancestor = parents[0]['sha']
        checks = commit_checks(ancestor, api)
        if checks:
            if not finance_only(api('/compare/'+ancestor+'...'+commit)):
                return None
            return ancestor if successful(checks) else None
    return None


def relevant(path):
    return (path in {'collector/src/parser.py', 'collector/src/tse_client.py',
                     'collector/src/election_release.py', 'collector/src/second_round_publish.py',
                     'collector/requirements.txt', 'deploy/frontend.py'}
            or path.startswith(('collector/src/municipal', 'tools/municipal',
                                '.github/workflows/municipal', 'deploy/scripts/wait-municipal',
                                'tests/test_municipal', 'tests/municipal_fixtures')))


def assert_fresh(commit, api):
    head = api('/git/ref/heads/main')['object']['sha']
    if head == commit:
        return
    comparison = api('/compare/'+commit+'...'+head)
    files = comparison['files']
    if (comparison['status'] not in {'ahead', 'identical'} or len(files) >= 300
            or any(relevant(entry['filename']) or relevant(entry.get('previous_filename', '')) for entry in files)):
        raise RuntimeError('municipal_obsolete_source_commit')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    if not re.fullmatch('[a-f0-9]{40}', args.commit):
        raise ValueError('municipal_invalid_source_commit')
    prefix = 'repos/'+os.environ['GITHUB_REPOSITORY']

    def api(path):
        return json.loads(subprocess.check_output(['gh', 'api', prefix+path]))

    for _ in range(90):
        approved = approved_commit(args.commit, api)
        if approved:
            assert_fresh(args.commit, api)
            print('Municipal source '+args.commit+' approved by CI at '+approved)
            return
        time.sleep(10)
    raise RuntimeError('municipal_ci_timeout')


if __name__ == '__main__':
    main()
