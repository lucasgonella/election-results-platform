"""CI approval cannot cross municipal changes or hide failed/pending checks."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('municipal_gate', Path(__file__).resolve().parents[1]/'deploy/scripts/wait-municipal-ci.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
HEAD, BASE = 'a'*40, 'b'*40


def checks(status='completed', conclusion='success'):
    return {'check_runs': [{'id': i, 'name': name, 'status': status, 'conclusion': conclusion}
                           for i, name in enumerate(sorted(gate.REQUIRED), 1)]}


class MunicipalCIGateTests(unittest.TestCase):
    def setUp(self):
        self.responses = {
            '/commits/'+HEAD+'/check-runs?per_page=100': {'check_runs': []},
            '/commits/'+HEAD: {'parents': [{'sha': BASE}]},
            '/commits/'+BASE+'/check-runs?per_page=100': checks(),
            '/compare/'+BASE+'...'+HEAD: {'status': 'ahead', 'files': [{'filename': gate.FINANCE_EXPORT}]},
            '/git/ref/heads/main': {'object': {'sha': HEAD}},
        }
        self.api = self.responses.__getitem__

    def test_finance_only_bot_commit_reuses_exact_tested_code(self):
        self.responses['/commits/'+HEAD+'/check-runs?per_page=100'] = {
            'check_runs': [{'id': 10, 'name': 'collect', 'status': 'completed', 'conclusion': 'failure'}]}
        self.assertEqual(gate.approved_commit(HEAD, self.api), BASE)
        gate.assert_fresh(HEAD, self.api)

    def test_exact_commit_approval_does_not_need_an_ancestor(self):
        self.responses['/commits/'+HEAD+'/check-runs?per_page=100'] = checks()
        self.assertEqual(gate.approved_commit(HEAD, self.api), HEAD)

    def test_pending_or_failed_head_checks_cannot_inherit_success(self):
        path = '/commits/'+HEAD+'/check-runs?per_page=100'
        self.responses[path] = checks('in_progress', None)
        self.assertIsNone(gate.approved_commit(HEAD, self.api))
        self.responses[path] = checks(conclusion='failure')
        with self.assertRaisesRegex(RuntimeError, 'municipal_required_ci_failed'):
            gate.approved_commit(HEAD, self.api)

    def test_source_tests_dependencies_and_renames_cannot_inherit_approval(self):
        for entry in [{'filename': 'collector/src/municipal_publish.py'},
                      {'filename': 'tests/test_municipal_pipeline.py'},
                      {'filename': 'collector/requirements.txt'},
                      {'filename': gate.FINANCE_EXPORT, 'previous_filename': 'deploy/frontend.py'}]:
            with self.subTest(entry=entry):
                self.responses['/compare/'+BASE+'...'+HEAD]['files'] = [entry]
                self.assertIsNone(gate.approved_commit(HEAD, self.api))

    def test_failed_ancestor_and_truncated_checks_fail_closed(self):
        self.responses['/commits/'+BASE+'/check-runs?per_page=100'] = checks(conclusion='failure')
        with self.assertRaisesRegex(RuntimeError, 'municipal_required_ci_failed'):
            gate.approved_commit(HEAD, self.api)
        with self.assertRaisesRegex(RuntimeError, 'municipal_ci_inventory_truncated'):
            gate.latest_checks({'check_runs': [], 'total_count': 101})

    def test_divergent_or_truncated_comparison_cannot_inherit_approval(self):
        comparison = self.responses['/compare/'+BASE+'...'+HEAD]
        comparison['status'] = 'diverged'
        self.assertIsNone(gate.approved_commit(HEAD, self.api))
        comparison.update(status='ahead', files=[{'filename': gate.FINANCE_EXPORT}]*300)
        self.assertIsNone(gate.approved_commit(HEAD, self.api))

    def test_new_municipal_commit_blocks_old_publication_including_renames(self):
        self.responses['/git/ref/heads/main']['object']['sha'] = BASE
        self.responses['/compare/'+HEAD+'...'+BASE] = {
            'status': 'ahead', 'files': [{'filename': gate.FINANCE_EXPORT, 'previous_filename': 'collector/src/municipal_runner.py'}]}
        with self.assertRaisesRegex(RuntimeError, 'municipal_obsolete_source_commit'):
            gate.assert_fresh(HEAD, self.api)

    def test_scheduled_job_checks_do_not_hide_required_ci_on_next_page(self):
        path = '/commits/'+HEAD+'/check-runs?per_page=100'
        required = checks()['check_runs']
        self.responses[path] = {'total_count': 103, 'check_runs': [
            {'id': 100+i, 'name': 'collect', 'status': 'completed', 'conclusion': 'success'} for i in range(100)]}
        self.responses[path+'&page=2'] = {'total_count': 103, 'check_runs': required}
        self.assertEqual(gate.approved_commit(HEAD, self.api), HEAD)
        required[-1]['conclusion'] = 'failure'
        with self.assertRaisesRegex(RuntimeError, 'municipal_required_ci_failed'):
            gate.approved_commit(HEAD, self.api)


if __name__ == '__main__':
    unittest.main()
