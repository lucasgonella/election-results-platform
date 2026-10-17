"""Regression tests for the finance-data-only CI ancestry exception."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / 'deploy/scripts/wait-frontend-ci.py'
spec = importlib.util.spec_from_file_location('frontend_ci_gate', MODULE_PATH)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def runner(commits, checks):
    def query(argv):
        path = argv[-1]
        if path.endswith('/check-runs?per_page=100'):
            sha = path.split('/commits/')[1].split('/')[0]
            return json.dumps({'check_runs': [
                {'name': name, 'status': 'completed', 'conclusion': 'success', 'id': i}
                for i, name in enumerate(checks.get(sha, []), 1)
            ]}).encode()
        sha = path.split('/commits/')[1]
        return json.dumps(commits[sha]).encode()
    return query


def revision(parent='approved', path=gate.FINANCE_EXPORT, user='github-actions[bot]'):
    return {'parents': [{'sha': parent}], 'files': [{'filename': path, 'status': 'modified'}],
            'author': {'login': user}}


def test_approved_finance_data_only_ancestor():
    commits = {'bot2': revision('bot1'), 'bot1': revision()}
    checks = {'approved': ['Python Tests', 'Frontend FTP validation']}
    with patch.dict(gate.os.environ, {'GITHUB_REPOSITORY': 'owner/repo'}), patch.object(
            gate.subprocess, 'check_output', side_effect=runner(commits, checks)):
        assert gate.approved_finance_ancestor('bot2') == 'approved'


def test_code_change_never_inherits_prior_ci():
    commits = {'bot2': revision('approved', 'deploy/frontend.py')}
    checks = {'approved': ['Python Tests', 'Frontend FTP validation']}
    with patch.dict(gate.os.environ, {'GITHUB_REPOSITORY': 'owner/repo'}), patch.object(
            gate.subprocess, 'check_output', side_effect=runner(commits, checks)):
        assert gate.approved_finance_ancestor('bot2') is None


def test_human_commit_never_inherits_prior_ci():
    commits = {'user_commit': revision('approved', user='somebody')}
    checks = {'approved': ['Python Tests', 'Frontend FTP validation']}
    with patch.dict(gate.os.environ, {'GITHUB_REPOSITORY': 'owner/repo'}), patch.object(
            gate.subprocess, 'check_output', side_effect=runner(commits, checks)):
        assert gate.approved_finance_ancestor('user_commit') is None


def test_partial_ci_is_not_accepted():
    commits = {'bot1': revision('approved'), 'approved': revision('older', user='somebody')}
    checks = {'approved': ['Python Tests']}
    with patch.dict(gate.os.environ, {'GITHUB_REPOSITORY': 'owner/repo'}), patch.object(
            gate.subprocess, 'check_output', side_effect=runner(commits, checks)):
        assert gate.approved_finance_ancestor('bot1') is None
