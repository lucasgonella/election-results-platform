"""Watch-loop progress and durable retry timing with no external requests."""
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from collector.src import biometry as b, biometry_publish as p, biometry_runner as r
from collector.src.second_round_publish import load
from tests.biometry_fixtures import dataset
from tests.test_frontend_deploy import FakeFTP


class WatchCadenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)

    def run_loop(self, times, publish, *, seed=None, operation='watch', collection=None):
        clock = [times[0]]
        waits = []

        class Stop:
            index = 0

            def is_set(self):
                if self.index == len(times):
                    return True
                clock[0] = times[self.index]
                self.index += 1
                return False

            def wait(self, seconds):
                waits.append(seconds)

        db = b.database(self.state)
        if not b.meta(db, 'inventory'):
            b.set_meta(db, 'inventory', {'synthetic': True})
            b.set_meta(db, 'inventory_checked_at', times[0])
        for name, value in (seed or {}).items():
            b.set_meta(db, name, value)
        db.commit()
        output = io.StringIO()
        try:
            with ExitStack() as stack:
                stack.enter_context(patch.object(r, 'database', return_value=db))
                stack.enter_context(patch.object(r, 'guard_storage'))
                stack.enter_context(patch.object(r, 'OfficialHTTP'))
                stack.enter_context(patch.object(r.signal, 'signal'))
                stack.enter_context(patch.object(r.threading, 'Event', return_value=Stop()))
                stack.enter_context(patch.object(r.time, 'time', side_effect=lambda: clock[0]))
                stack.enter_context(patch.object(r, 'initialize', side_effect=AssertionError('unexpected inventory refresh')))
                collector = stack.enter_context(patch.object(r, 'collect',
                    **({'side_effect': collection} if collection else {'return_value': 128})))
                aggregate = stack.enter_context(patch.object(r, 'aggregate', return_value=dataset()))
                publisher = stack.enter_context(patch.object(p, 'publish', side_effect=publish))
                stack.enter_context(patch('sys.argv', ['biometry_runner', operation,
                    '--state', str(self.state), '--publish']))
                with redirect_stdout(output):
                    r.main()
                return {'collector': collector, 'aggregate': aggregate, 'publisher': publisher,
                        'waits': waits, 'events': [json.loads(line) for line in output.getvalue().splitlines()]}
        finally:
            db.close()

    def metadata(self, name, default=0):
        db = b.database(self.state)
        try:
            return b.meta(db, name, default)
        finally:
            db.close()

    def test_publication_failure_keeps_collecting_until_scheduled_retry(self):
        result = self.run_loop([2000, 2065, 2600],
            [RuntimeError('synthetic_ssh_failure'), {'status': 'published'}])
        self.assertEqual(result['collector'].call_count, 3)
        self.assertEqual(result['publisher'].call_count, 2)
        self.assertEqual(result['aggregate'].call_count, 2)
        self.assertEqual(result['waits'], [])
        self.assertEqual([event.get('event') for event in result['events']].count('biometry_publish_failed'), 1)
        self.assertNotIn('biometry_cycle_failed', [event.get('event') for event in result['events']])
        self.assertEqual(self.metadata('last_publish_attempt'), 2600)
        self.assertEqual(self.metadata('last_published'), 2600)

    def test_crash_after_attempt_does_not_retry_immediately_on_restart(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_loop([2000], KeyboardInterrupt())
        self.assertEqual(self.metadata('last_publish_attempt'), 2000)
        self.assertEqual(self.metadata('last_published'), 0)
        result = self.run_loop([2065, 2120], AssertionError('publication retried too soon'))
        self.assertEqual(result['collector'].call_count, 2)
        result['publisher'].assert_not_called()
        result['aggregate'].assert_not_called()
        self.assertEqual(result['waits'], [])

    def test_pending_transaction_survives_collection_and_recovers_same_owner(self):
        ftp = FakeFTP()
        publisher = p.Publisher(p.Transport(ftp), self.state,
            http_read=lambda name: ftp.files.get(p.SITE + '/' + name))
        owners = []

        def fail_once(state, value):
            def fault(phase):
                if phase == 'before_activation':
                    owners.append(load(self.state / 'pending-publish.json')['owner'])
                    raise RuntimeError('synthetic_lost_connection')
            publisher.fault = fault
            return publisher.publish(value)

        first = self.run_loop([2000, 2065], fail_once)
        self.assertEqual(first['publisher'].call_count, 1)
        self.assertEqual(first['collector'].call_count, 2)
        self.assertEqual(load(self.state / 'pending-publish.json')['owner'], owners[0])
        publisher.fault = lambda _: None
        second = self.run_loop([2600], lambda state, value: publisher.publish(value))
        self.assertEqual(second['publisher'].call_count, 1)
        self.assertIsNone(load(self.state / 'pending-publish.json'))
        self.assertNotIn(p.PRIVATE + '/lock', ftp.dirs)
        publisher.verify(publisher.marker())

    def test_official_source_cooldown_still_pauses_collection(self):
        result = self.run_loop([2000, 2060, 2120], [{'status': 'published'}], seed={'retry_after': 2120})
        self.assertEqual(result['waits'], [60, 60])
        self.assertEqual(result['collector'].call_count, 1)
        self.assertEqual(result['publisher'].call_count, 1)

    def test_collection_failure_retains_its_own_pause(self):
        result = self.run_loop([2000, 2060], [{'status': 'published'}],
            collection=[RuntimeError('synthetic_source_failure'), 128])
        self.assertEqual(result['waits'], [60])
        self.assertEqual(result['collector'].call_count, 2)
        self.assertEqual(result['publisher'].call_count, 1)
        self.assertIn('biometry_cycle_failed', [event.get('event') for event in result['events']])

    def test_supervised_export_reports_failure_even_inside_watch_cadence(self):
        with self.assertRaisesRegex(RuntimeError, 'synthetic_publication_failure'):
            self.run_loop([2065], RuntimeError('synthetic_publication_failure'),
                seed={'last_publish_attempt': 2000}, operation='export')
        self.assertEqual(self.metadata('last_publish_attempt'), 2065)
        self.assertEqual(self.metadata('last_published'), 0)
