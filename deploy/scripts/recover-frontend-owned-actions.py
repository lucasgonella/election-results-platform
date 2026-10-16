"""Recover only a verified, finished Actions owner inside the serialized deploy.

Never steal an unknown/live lock. Never infer abandonment from elapsed time.
All public writes use the existing journal/backup/checksum recovery mechanism.
"""
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from deploy import frontend as f

REPO = 'lucasgonella/election-results-platform'
WORKFLOWS = {'.github/workflows/deploy-portal-ftp.yml', '.github/workflows/deploy-goias-ftp.yml',
             '.github/workflows/frontend-ftp-manual.yml'}


def owner_proof(journal, repo, fetch_attempt):
    if repo != REPO: raise ValueError('unexpected_recovery_repository')
    match = re.fullmatch(r'actions-([0-9]{1,20})-([0-9]{1,5})', journal.get('transaction', ''))
    if not match or journal.get('status') != 'prepared': raise RuntimeError('unproven_frontend_lock_owner')
    run_id, attempt = map(int, match.groups())
    manifest = journal.get('manifest') or {}
    f.validate_manifest(manifest, journal['component'])
    run = fetch_attempt(run_id, attempt)
    if (run.get('status') != 'completed' or run.get('conclusion') not in {'failure', 'cancelled', 'timed_out'}
            or run.get('head_sha') != manifest['commit'] or run.get('head_branch') != 'main'
            or run.get('run_attempt') != attempt or run.get('id') != run_id
            or run.get('repository', {}).get('full_name') != repo
            or run.get('path') not in WORKFLOWS):
        raise RuntimeError('frontend_owner_not_verified_abandoned')
    return {'run_id': run_id, 'attempt': attempt, 'commit': manifest['commit']}


def recover_owned(transport, repo, fetch_attempt, *, http=f.http_read):
    recovered = []
    for component in ['portal', 'raio-x']:
        private = f.PRIVATE + '/' + component
        if transport.metadata(private + '/lock/') is None: continue
        journal = f.decode(transport.read(private + '/pending.json'))
        if journal.get('component') != component: raise RuntimeError('foreign_frontend_recovery_journal')
        proof = owner_proof(journal, repo, fetch_attempt)
        cfg, manifest = f.target(component), journal['manifest']
        if set(journal.get('before', {})) != set(cfg['entrypoints']): raise RuntimeError('invalid_backup_inventory')
        current = f.decode(transport.read(f.state_path(component)))
        if current != journal['previous_state'] and not (
                current.get('commit') == manifest['commit'] and current.get('manifest') == manifest
                and current.get('transaction') == journal['transaction']):
            raise RuntimeError('external_frontend_state_detected')
        # Verify every backup and both possible public states before the first
        # restore write; an unrelated writer's HTML is never overwritten.
        for name, entry in journal['before'].items():
            path = private + '/transactions/' + journal['transaction'] + '/before/' + name
            f.verify_bytes(transport.read(path), entry)
            allowed = {entry['sha256'], manifest['files'][name]['sha256']}
            if (f.digest(transport.read(cfg['ftp_root'] + '/' + name)) not in allowed
                    or f.digest(http(cfg['url'] + name)) not in allowed):
                raise RuntimeError('external_frontend_entrypoint_detected')
        result = f.recover(transport, component, http=http)
        recovered.append({**result, 'transaction': journal['transaction'], 'verified_owner': proof})
    return recovered


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REF') != 'refs/heads/main':
        raise RuntimeError('recovery_requires_serialized_main_workflow')
    repo = os.environ['GITHUB_REPOSITORY']
    token = os.environ['GH_TOKEN']
    def fetch_attempt(run, attempt):
        url = 'https://api.github.com/repos/' + REPO + '/actions/runs/' + str(run) + '/attempts/' + str(attempt)
        request = Request(url, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28'})
        with build_opener(f.NoRedirect).open(request, timeout=20) as response:
            return json.loads(response.read(2 * 1024 * 1024))
    transport = f.Transport(f.connect(), reconnect=f.connect, transfer=f.curl_transfer)
    try: recovered = recover_owned(transport, repo, fetch_attempt)
    finally: transport.ftp.close()
    print(json.dumps({'status': 'recovered_known_owner' if recovered else 'no_recovery_needed', 'recoveries': recovered}))


if __name__ == '__main__':
    try: main()
    except Exception as error:
        print(json.dumps({'status': 'recovery_blocked', **f.error_report(error)}))
        raise SystemExit(1)
