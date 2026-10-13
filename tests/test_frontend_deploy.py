"""Offline protocol tests. No hosting, database, TSE or production access."""
import ftplib
import importlib.util
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch

from deploy import frontend as f


class FakeFTP:
    def __init__(self):
        self.files = {}
        self.dirs = {'/', '/public_html', '/public_html/eleicoes', '/public_html/eleicoes/goias', '/public_html/eleicoes/goias/raio-x'}
        self.events = []
        self.fail_rename = None
        self.corrupt_upload = False

    def sendcmd(self, command):
        verb, path = command.split(' ', 1)
        assert verb == 'MLST'
        path = path.rstrip('/') or '/'
        if path in self.files:
            return '250-Listing\n type=file;size='+str(len(self.files[path]))+'; '+path+'\n250 End'
        if path in self.dirs:
            return '250-Listing\n type=dir; '+path+'\n250 End'
        raise ftplib.error_perm('550 Not found')

    def mkd(self, path):
        if path in self.dirs or path in self.files:
            raise ftplib.error_perm('550 Exists')
        assert str(Path(path).parent).replace('\\', '/') in self.dirs
        self.dirs.add(path)
        self.events.append(('mkdir', path))

    def rmd(self, path):
        assert not any(p.startswith(path+'/') for p in self.files)
        self.dirs.remove(path)

    def retrbinary(self, command, callback):
        callback(self.files[command.removeprefix('RETR ')])

    def storbinary(self, command, stream):
        path = command.removeprefix('STOR ')
        self.events.append(('upload', path))
        self.files[path] = stream.read() + (b'bad' if self.corrupt_upload else b'')
        self.corrupt_upload = False

    def rename(self, old, new):
        self.events.append(('rename', new))
        if self.fail_rename == new:
            self.fail_rename = None
            raise ftplib.error_temp('450 simulated failure')
        self.files[new] = self.files.pop(old)

    def delete(self, path):
        self.events.append(('delete', path))
        del self.files[path]


class FrontendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ftp = FakeFTP()
        self.transport = f.Transport(self.ftp)
        self.original = {}
        for component in ['portal', 'raio-x']:
            cfg = f.target(component)
            for name in cfg['entrypoints']:
                raw = ('old '+component+' '+name).encode()
                self.ftp.files[cfg['ftp_root']+'/'+name] = raw
                self.original[cfg['ftp_root']+'/'+name] = raw
        self.ftp.files['/public_html/data/version.json'] = b'protected election marker'
        self.ftp.files['/public_html/eleicoes/goias/raio-x/data/go-2026.json'] = b'protected finance'

    def http(self, url):
        relative = url.removeprefix('https://afgnet.com.br')
        if relative.endswith('/'):
            relative += 'index.html'
        return self.ftp.files['/public_html'+relative]

    def package(self, component='portal', commit='a'*40):
        source = self.root/f.target(component)['source']
        source.mkdir(parents=True, exist_ok=True)
        for name in f.target(component)['entrypoints']:
            (source/name).write_text('<!doctype html><html><head><link href="styles.css?v=1"></head><body><script src="app.js"></script></body></html>')
        (source/'app.js').write_text('console.log("ok")')
        (source/'styles.css').write_text('body { color: red; }')
        (source/'data').mkdir(exist_ok=True)
        (source/'data/private.json').write_text('{"secret":"never ship"}')
        out = self.root/(component+commit[:4])
        manifest = f.build(component, commit, out, root=self.root, validate=False)
        return out, manifest, {n: (out/'files'/n).read_bytes() for n in manifest['files']}

    def publish(self, component='portal', commit='a'*40, transaction='first'):
        package, manifest, contents = self.package(component, commit)
        with self.transport.lock(component):
            result = f.activate(self.transport, manifest, contents, transaction, http=self.http)
        return package, manifest, result

    def test_allowlist_and_immutable_references(self):
        path, manifest, contents = self.package()
        self.assertEqual(f.validate_package(path, 'portal'), manifest)
        self.assertNotIn('data/private.json', manifest['files'])
        self.assertIn(('/eleicoes/frontend-releases/'+'a'*40+'/app.js').encode(), contents['index.html'])

    def test_success_effectively_publishes_and_preserves_data_goias(self):
        _, manifest, result = self.publish()
        self.assertEqual(result['status'], 'published')
        self.assertFalse(result['multinode_guarantee'])
        f.verify_public(manifest, http=self.http, live=True)
        self.assertEqual(self.ftp.files['/public_html/data/version.json'], b'protected election marker')
        self.assertEqual(self.ftp.files['/public_html/eleicoes/goias/raio-x/data/go-2026.json'], b'protected finance')
        self.assertEqual(self.ftp.files['/public_html/eleicoes/goias/raio-x/index.html'], self.original['/public_html/eleicoes/goias/raio-x/index.html'])
        changes = [p for operation, p in self.ftp.events if operation == 'rename']
        asset_last = max(i for i, p in enumerate(changes) if '/frontend-releases/' in p)
        first_root = min(i for i, p in enumerate(changes) if p in self.original)
        self.assertLess(asset_last, first_root)

    def test_checksum_corruption_stops_before_activation(self):
        self.transport.directory('/frontend-deploy/portal')
        self.ftp.corrupt_upload = True
        with self.assertRaises(RuntimeError):
            self.transport.put('/frontend-deploy/portal/current.json', b'test')
        self.assertNotIn('/frontend-deploy/portal/current.json', self.ftp.files)
        self.assertNotIn('/frontend-deploy/portal/current.json.upload', self.ftp.files)
        for path, raw in self.original.items():
            self.assertEqual(self.ftp.files[path], raw)

    def test_partial_activation_failure_restores_all_entrypoints(self):
        _, manifest, contents = self.package()
        self.ftp.fail_rename = '/public_html/eleicoes/index.html'
        with self.assertRaises(ftplib.error_temp):
            with self.transport.lock('portal'):
                f.activate(self.transport, manifest, contents, 'failed', http=self.http)
        for path, raw in self.original.items():
            self.assertEqual(self.ftp.files[path], raw)
        self.assertIn('/frontend-deploy/portal/lock', self.ftp.dirs)
        self.assertEqual(f.recover(self.transport, 'portal', http=self.http)['status'], 'recovered')

    def test_http_failure_after_activation_restores(self):
        _, manifest, contents = self.package()
        def bad_http(url):
            if url.endswith('/index.html') and '/frontend-releases/' not in url and self.ftp.files['/public_html/eleicoes/index.html'] != self.original['/public_html/eleicoes/index.html']:
                return b'stale cached page'
            return self.http(url)
        with self.assertRaises(RuntimeError):
            f.activate(self.transport, manifest, contents, 'cache-failure', http=bad_http)
        self.assertEqual(self.ftp.files['/public_html/eleicoes/index.html'], self.original['/public_html/eleicoes/index.html'])

    def test_rollback_first_deployment_restores_bootstrap(self):
        self.publish()
        with self.transport.lock('portal'):
            result = f.rollback(self.transport, 'portal', 'previous', 'rollback-first', http=self.http)
        self.assertEqual(result['status'], 'restored_bootstrap')
        for path, raw in self.original.items():
            self.assertEqual(self.ftp.files[path], raw)

    def test_rollback_version_and_previous(self):
        self.publish()
        _, old_manifest, _ = self.package('portal', 'b'*40)
        # package already prepared above; use it directly instead of rebuilding.
        contents = {n: (self.root/('portal'+'bbbb')/'files'/n).read_bytes() for n in old_manifest['files']}
        with self.transport.lock('portal'):
            f.activate(self.transport, old_manifest, contents, 'second', http=self.http, skip_unchanged=False)
        with self.transport.lock('portal'):
            result = f.rollback(self.transport, 'portal', 'previous', 'back', http=self.http)
        self.assertEqual(result['commit'], 'a'*40)

    def test_immutable_conflict_rejected(self):
        self.transport.put('/public_html/eleicoes/frontend-releases/'+'a'*40+'/app.js', b'old')
        with self.assertRaisesRegex(RuntimeError, 'immutable_collision'):
            self.transport.put('/public_html/eleicoes/frontend-releases/'+'a'*40+'/app.js', b'new')

    def test_abandoned_asset_temporary_is_preserved_during_new_attempt(self):
        _, manifest, contents = self.package()
        orphan = '/public_html/eleicoes/frontend-releases/'+'a'*40+'/app.js.upload'
        self.ftp.files[orphan] = b'unknown partial upload'
        with self.transport.lock('portal'):
            result = f.activate(self.transport, manifest, contents, 'retry', http=self.http)
        self.assertEqual(result['status'], 'published')
        self.assertEqual(self.ftp.files[orphan], b'unknown partial upload')
        self.assertFalse(any(path == orphan for operation, path in self.ftp.events))
        f.verify_public(manifest, http=self.http, live=True)

    def test_process_interruption_can_recover_then_publish_same_asset_version(self):
        _, manifest, contents = self.package()
        original_store = self.ftp.storbinary
        interrupted = []
        def terminate(command, stream):
            original_store(command, stream)
            if '/frontend-releases/' in command and not interrupted:
                interrupted.append(command.removeprefix('STOR '))
                raise SystemExit('simulated process termination')
        self.ftp.storbinary = terminate
        with self.assertRaises(SystemExit):
            with self.transport.lock('portal'):
                f.activate(self.transport, manifest, contents, 'interrupted', http=self.http)
        for path, raw in self.original.items():
            self.assertEqual(self.ftp.files[path], raw)
        self.ftp.storbinary = original_store
        new_transport = f.Transport(self.ftp)
        f.recover(new_transport, 'portal', http=self.http)
        orphan_bytes = self.ftp.files[interrupted[0]]
        with new_transport.lock('portal'):
            result = f.activate(new_transport, manifest, contents, 'retry', http=self.http)
        self.assertEqual(result['status'], 'published')
        self.assertEqual(self.ftp.files[interrupted[0]], orphan_bytes)
        self.assertEqual(sum(operation == 'upload' and path == interrupted[0]
                             for operation, path in self.ftp.events), 1)
        f.verify_public(manifest, http=self.http, live=True)
        self.assertEqual(self.ftp.files['/public_html/data/version.json'], b'protected election marker')
        self.assertEqual(self.ftp.files['/public_html/eleicoes/goias/raio-x/data/go-2026.json'], b'protected finance')

    def test_fresh_asset_temporary_collision_still_fails_closed(self):
        path = '/public_html/eleicoes/frontend-releases/'+'a'*40+'/app.js'
        temporary = path.removesuffix('.js')+'.'+'b'*32+'.js.upload'
        self.ftp.files[temporary] = b'foreign bytes'
        with patch.object(f.secrets, 'token_hex', return_value='b'*32), \
             self.assertRaisesRegex(RuntimeError, 'temporary_collision'):
            self.transport.put(path, b'new bytes')
        self.assertNotIn(path, self.ftp.files)
        self.assertEqual(self.ftp.files[temporary], b'foreign bytes')
        self.assertFalse(self.ftp.events)

    def test_stable_entrypoint_temporary_collision_still_requires_recovery(self):
        path = '/public_html/eleicoes/index.html'
        self.ftp.files[path+'.upload'] = b'foreign entrypoint'
        with self.assertRaisesRegex(RuntimeError, 'temporary_collision'):
            self.transport.put(path, b'new html', replace=True)
        self.assertEqual(self.ftp.files[path], self.original[path])
        self.assertEqual(self.ftp.files[path+'.upload'], b'foreign entrypoint')

    def test_second_client_cannot_acquire_lock(self):
        with self.transport.lock('portal'):
            with self.assertRaisesRegex(RuntimeError, 'frontend_requires_recovery'):
                with self.transport.lock('portal'):
                    self.fail('second client acquired lock')

    def test_raio_x_only_changes_its_entrypoint(self):
        self.publish('raio-x')
        self.assertEqual(self.ftp.files['/public_html/eleicoes/index.html'], self.original['/public_html/eleicoes/index.html'])
        self.assertEqual(self.ftp.files['/public_html/eleicoes/goias/raio-x/data/go-2026.json'], b'protected finance')

    def test_tampered_package_refused_before_network(self):
        directory, _, _ = self.package()
        (directory/'files/app.js').write_bytes(b'evil')
        with self.assertRaises(RuntimeError):
            f.validate_package(directory, 'portal')

    def test_extra_package_file_rejected(self):
        directory, _, _ = self.package()
        (directory/'files/payload.php').write_bytes(b'<?php')
        with self.assertRaises(ValueError):
            f.validate_package(directory, 'portal')

    def test_static_paths_cannot_escape_or_ship_election_data(self):
        for name in ['../index.html', '/index.html', 'data/version.json', '.env', 'goias/index.html', 'probe.php', 'a\\index.html', 'a//index.html', 'frontend-releases/index.html']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                f.static_path(name)

    def test_redirects_refused(self):
        with self.assertRaises(RuntimeError):
            f.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com')

    def test_bad_revision_and_component(self):
        with self.assertRaises(ValueError):
            f.revision('main; dangerous')
        with self.assertRaises(ValueError):
            f.target('election-data')

    def test_backup_paths_not_taken_from_remote_journal(self):
        with self.assertRaises(RuntimeError):
            f.restore(self.transport, {'component':'portal', 'transaction':'../../keys', 'before':{}}, http=self.http)

    def test_ci_failure_never_authorizes_deploy(self):
        spec = importlib.util.spec_from_file_location('wait', f.ROOT/'deploy/scripts/wait-frontend-ci.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        checks = [{'id':i, 'name':name, 'status':'completed', 'conclusion':'success'} for i, name in enumerate(['Python Tests', 'Frontend FTP validation'])]
        self.assertTrue(module.ready(checks))
        checks[-1]['conclusion'] = 'failure'
        with self.assertRaises(RuntimeError):
            module.ready(checks)
        self.assertFalse(module.ready(checks[:1]))

    def test_same_commit_is_idempotent(self):
        package, manifest, _ = self.publish()
        contents = {name: (package/'files'/name).read_bytes() for name in manifest['files']}
        with self.transport.lock('portal'):
            result = f.activate(self.transport, manifest, contents, 'retry', http=self.http)
        self.assertEqual(result['status'], 'unchanged')
        self.assertFalse(any('/retry/' in path for _, path in self.ftp.events))

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(ValueError):
            f.decode(b'{"component":"portal","component":"raio-x"}')

    def test_abort_before_activation_keeps_recovery_journal(self):
        _, manifest, contents = self.package()
        def unavailable(url):
            if '/frontend-releases/' in url:
                raise RuntimeError('staging_not_visible')
            return self.http(url)
        with self.assertRaises(RuntimeError):
            with self.transport.lock('portal'):
                f.activate(self.transport, manifest, contents, 'stage-failed', http=unavailable)
        for path, raw in self.original.items():
            self.assertEqual(self.ftp.files[path], raw)
        f.recover(self.transport, 'portal', http=self.http)

    def test_transport_refuses_protected_and_unmanaged_writes(self):
        for path in ['/public_html/data/version.json', '/public_html/eleicoes/data/version.json',
                     '/public_html/eleicoes/goias/raio-x/data/go-2026.json',
                     '/public_html/eleicoes/api/probe.php', '/frontend-deploy/staging-config.json',
                     '/public_html/eleicoes/app.js']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.transport.put(path, b'overwrite')

    def test_bootstrap_rollback_failure_restores_active_version(self):
        _, manifest, _ = self.publish()
        self.ftp.fail_rename = '/public_html/eleicoes/index.html'
        with self.assertRaises(ftplib.error_temp):
            with self.transport.lock('portal'):
                f.rollback(self.transport, 'portal', 'previous', 'rollback-failed', http=self.http)
        f.verify_public(manifest, http=self.http, live=True)
        f.recover(self.transport, 'portal', http=self.http)

    def test_goias_workflow_has_one_visual_writer_and_preserves_financial_pipeline(self):
        text = (f.ROOT/'.github/workflows/deploy-goias-ftp.yml').read_text(encoding='utf-8-sig')
        self.assertEqual(text.count('uses: ./.github/workflows/deploy-frontend-ftp.yml'), 1)
        self.assertNotIn('curl', text)
        self.assertIn("'!web/public/eleicoes/goias/raio-x/data/**'", text)
        financial = (f.ROOT/'.github/workflows/goias-finance-data.yml').read_text(encoding='utf-8-sig')
        self.assertIn('data/go-2026.json', financial)
        self.assertIn('--upload-file', financial)
        self.assertNotIn('--upload-file "web/public/eleicoes/goias/raio-x/index.html"', financial)

    def test_identical_component_content_is_not_uploaded_again(self):
        _, original, _ = self.publish()
        _, manifest, contents = self.package('portal', 'b'*40)
        self.assertEqual(original['source_sha256'], manifest['source_sha256'])
        before = list(self.ftp.events)
        result = f.activate(self.transport, manifest, contents, 'skip', http=self.http)
        self.assertEqual(result['status'], 'unchanged')
        self.assertEqual(result['commit'], original['commit'])
        self.assertEqual(result['requested_commit'], manifest['commit'])
        self.assertEqual(self.ftp.events, before)

    def test_content_change_requires_new_publication(self):
        _, original, _ = self.publish()
        source = self.root/f.target('portal')['source']
        (source/'styles.css').write_text('body { color: blue; }')
        directory = self.root/'changed'
        manifest = f.build('portal', 'b'*40, directory, root=self.root, validate=False)
        self.assertNotEqual(manifest['source_sha256'], original['source_sha256'])
        contents = {name: (directory/'files'/name).read_bytes() for name in manifest['files']}
        with self.transport.lock('portal'):
            result = f.activate(self.transport, manifest, contents, 'changed', http=self.http)
        self.assertEqual(result['status'], 'published')
        self.assertEqual(result['commit'], 'b'*40)

    def test_status_is_read_only_and_checks_public_hashes(self):
        _, manifest, _ = self.publish()
        before = list(self.ftp.events)
        result = f.status(self.transport, 'portal', http=self.http)
        self.assertEqual(result['commit'], manifest['commit'])
        self.assertFalse(result['lock_present'])
        self.assertEqual(self.ftp.events, before)
        self.ftp.files['/public_html/eleicoes/index.html'] = b'unexpected html'
        with self.assertRaises(RuntimeError):
            f.status(self.transport, 'portal', http=self.http)

    def test_legacy_installed_manifest_is_compatible(self):
        _, manifest, contents = self.package()
        manifest.pop('source_sha256')
        with self.transport.lock('portal'):
            f.activate(self.transport, manifest, contents, 'legacy', http=self.http)
        self.assertEqual(f.status(self.transport, 'portal', http=self.http)['commit'], 'a'*40)

    def test_content_skip_still_detects_public_corruption(self):
        self.publish()
        _, manifest, contents = self.package('portal', 'b'*40)
        self.ftp.files['/public_html/eleicoes/index.html'] = b'corrupt'
        with self.assertRaises(RuntimeError):
            f.activate(self.transport, manifest, contents, 'skip', http=self.http)

    def test_recovery_after_process_interruption_uses_verified_backups(self):
        self.publish()
        private = '/frontend-deploy/portal'
        journal = f.decode(self.ftp.files[private+'/transactions/first/journal.json'])
        journal['status'] = 'prepared'
        self.ftp.files[private+'/pending.json'] = f.encode(journal)
        self.ftp.dirs.add(private+'/lock')
        self.ftp.files['/public_html/eleicoes/index.html'] = b'interrupted publication'
        result = f.recover(self.transport, 'portal', http=self.http)
        self.assertEqual(result['status'], 'recovered')
        for path, raw in self.original.items():
            self.assertEqual(self.ftp.files[path], raw)

    def test_invalid_source_fingerprint_is_rejected(self):
        _, manifest, _ = self.package()
        manifest['source_sha256'] = 'not a hash'
        with self.assertRaises(ValueError):
            f.validate_manifest(manifest, 'portal')

    def test_finance_bot_push_does_not_cancel_visual_deploy(self):
        spec = importlib.util.spec_from_file_location('wait', f.ROOT/'deploy/scripts/wait-frontend-ci.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        path = 'web/public/eleicoes/goias/raio-x/data/go-2026.json'
        self.assertFalse(module.relevant(path, 'portal'))
        self.assertFalse(module.relevant(path, 'raio-x'))
        self.assertFalse(module.relevant('web/public/eleicoes/goias/raio-x/README.md', 'raio-x'))
        self.assertTrue(module.relevant('web/public/eleicoes/styles.css', 'portal'))
        self.assertFalse(module.relevant('web/public/eleicoes/styles.css', 'raio-x'))
        self.assertTrue(module.relevant('web/public/eleicoes/goias/raio-x/index.html', 'raio-x'))
        self.assertFalse(module.relevant('web/public/eleicoes/goias/raio-x/index.html', 'portal'))

    def test_latest_ci_attempt_is_authoritative(self):
        spec = importlib.util.spec_from_file_location('wait', f.ROOT/'deploy/scripts/wait-frontend-ci.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        checks = [{'id': 1, 'name': 'Python Tests', 'status': 'completed', 'conclusion': 'success'},
                  {'id': 2, 'name': 'Frontend FTP validation', 'status': 'completed', 'conclusion': 'success'},
                  {'id': 3, 'name': 'Frontend FTP validation', 'status': 'completed', 'conclusion': 'failure'}]
        with self.assertRaises(RuntimeError):
            module.ready(checks)

    def test_epsv_is_preferred_without_an_active_connection(self):
        client = f.PassiveFTP()
        client.af = socket.AF_INET
        client.sock = Mock()
        client.sock.getpeername.return_value = ('127.0.0.1', 21)
        client.sendcmd = Mock(return_value='229 Entering Extended Passive Mode (|||12345|)')
        self.assertEqual(client.makepasv(), ('127.0.0.1', 12345))
        client.sendcmd.assert_called_once_with('EPSV')

    def test_pasv_fallback_only_when_epsv_is_unsupported(self):
        client = f.PassiveFTP()
        client.af = socket.AF_INET
        client.sock = Mock()
        client.sock.getpeername.return_value = ('127.0.0.1', 21)
        client.sendcmd = Mock(side_effect=[ftplib.error_perm('502 Not implemented'),
                                          '227 Entering Passive Mode (10,0,0,1,48,57)'])
        self.assertEqual(client.makepasv(), ('127.0.0.1', 12345))
        self.assertEqual([call.args[0] for call in client.sendcmd.call_args_list], ['EPSV', 'PASV'])
        client.sendcmd = Mock(side_effect=ftplib.error_perm('530 Not authenticated'))
        with self.assertRaises(ftplib.error_perm):
            client.makepasv()
        client.sendcmd.assert_called_once_with('EPSV')

    def test_transfer_failure_is_preserved_when_cleanup_connection_is_broken(self):
        class InterruptedFTP(FakeFTP):
            broken = False
            def sendcmd(self, command):
                if self.broken:
                    raise OSError('cannot read from timed out object; fixture-secret')
                return super().sendcmd(command)
            def storbinary(self, command, stream):
                self.broken = True
                raise TimeoutError('fixture-secret')
        transport = f.Transport(InterruptedFTP())
        with self.assertRaises(ExceptionGroup) as error:
            transport.put('/frontend-deploy/portal/current.json', b'test')
        report = f.error_report(error.exception)
        self.assertEqual(report['causes'][0]['error_type'], 'TimeoutError')
        self.assertEqual(report['causes'][1]['error_type'], 'OSError')
        self.assertNotIn('fixture-secret', json.dumps(report))

    def test_cli_failure_writes_a_sanitized_failure_receipt(self):
        report = self.root/'failure.json'
        failure = ExceptionGroup('fixture-secret', [ConnectionResetError(104, 'fixture-secret'),
                                                    ftplib.error_perm('550 fixture-secret')])
        with patch('sys.argv', ['frontend', 'status', '--component', 'portal', '--report', str(report)]), \
             patch.object(f, 'execute', side_effect=failure), patch('sys.stdout', new=io.StringIO()), \
             self.assertRaises(SystemExit) as error:
            f.main()
        self.assertEqual(error.exception.code, 1)
        receipt = json.loads(report.read_text())
        self.assertEqual(receipt['status'], 'failed')
        self.assertEqual(receipt['causes'][0]['errno'], 104)
        self.assertEqual(receipt['causes'][1]['ftp_code'], '550')
        self.assertNotIn('fixture-secret', json.dumps(receipt))

    def interrupted_transport(self, *, corrupt=False, lose_rename=False):
        class LostResponse(FakeFTP):
            broken = False
            def close(self):
                pass
            def sendcmd(self, command):
                if self.broken:
                    raise OSError('cannot read from timed out object')
                return super().sendcmd(command)
            def storbinary(self, command, stream):
                super().storbinary(command, stream)
                if not lose_rename:
                    self.broken = True
                    raise TimeoutError('lost completion response')
            def rename(self, old, new):
                super().rename(old, new)
                self.broken = True
                raise ConnectionResetError('lost rename response')
        first = LostResponse()
        first.corrupt_upload = corrupt
        next_connection = FakeFTP()
        next_connection.files = first.files
        next_connection.dirs = first.dirs
        next_connection.events = first.events
        return first, f.Transport(first, reconnect=lambda: next_connection)

    def test_lost_upload_response_is_reconciled_without_replaying_stor(self):
        first, transport = self.interrupted_transport()
        path = '/frontend-deploy/portal/current.json'
        transport.put(path, b'verified bytes')
        self.assertEqual(first.files[path], b'verified bytes')
        self.assertEqual(sum(event == 'upload' for event, _ in first.events), 1)
        self.assertNotIn(path+'.upload', first.files)
        self.assertEqual(transport.reconciled_transfers, 1)

    def test_lost_asset_upload_response_reconciles_only_its_fresh_temporary(self):
        first, transport = self.interrupted_transport()
        path = '/public_html/eleicoes/frontend-releases/'+'a'*40+'/app.js'
        foreign = path+'.upload'
        first.files[foreign] = b'unknown prior upload'
        transport.put(path, b'verified asset')
        self.assertEqual(first.files[path], b'verified asset')
        self.assertEqual(first.files[foreign], b'unknown prior upload')
        self.assertEqual(sum(event == 'upload' for event, _ in first.events), 1)
        self.assertEqual(transport.reconciled_transfers, 1)
        self.assertEqual([p for p in first.files if p.endswith('.upload')], [foreign])

    def test_lost_rename_response_is_reconciled_by_destination_hash(self):
        first, transport = self.interrupted_transport(lose_rename=True)
        path = '/frontend-deploy/portal/current.json'
        transport.put(path, b'verified bytes')
        self.assertEqual(first.files[path], b'verified bytes')
        self.assertEqual(sum(event == 'rename' for event, _ in first.events), 1)
        self.assertEqual(transport.reconciled_transfers, 1)

    def test_interrupted_corrupt_upload_is_never_renamed(self):
        first, transport = self.interrupted_transport(corrupt=True)
        path = '/frontend-deploy/portal/current.json'
        with self.assertRaises(ExceptionGroup):
            transport.put(path, b'verified bytes')
        self.assertNotIn(path, first.files)
        self.assertNotIn(path+'.upload', first.files)
        self.assertFalse(any(event == 'rename' for event, _ in first.events))

    def test_unrecovered_other_component_blocks_new_mutations(self):
        self.ftp.dirs.add('/frontend-deploy/raio-x/lock')
        with self.assertRaisesRegex(RuntimeError, 'frontend_requires_recovery'):
            with self.transport.lock('portal'):
                self.fail('mutation started while another component needs recovery')

    def test_native_data_channel_preserves_control_checks_and_final_hash(self):
        self.ftp.close = lambda: None
        def transfer(path, raw=None):
            if raw is not None:
                self.ftp.files[path] = raw
                return b''
            return self.ftp.files[path]
        transport = f.Transport(self.ftp, reconnect=lambda: self.ftp, transfer=transfer)
        path = '/frontend-deploy/portal/current.json'
        transport.put(path, b'verified native transfer')
        self.assertEqual(transport.read(path), b'verified native transfer')
        self.assertNotIn(path+'.upload', self.ftp.files)

    def test_native_curl_is_plain_passive_and_keeps_credentials_out_of_argv(self):
        credentials = {'LOCAWEB_FTP_HOST': 'ftp.example.test', 'LOCAWEB_FTP_USER': 'fixture-user',
                       'LOCAWEB_FTP_PASSWORD': 'fixture-password'}
        captured = {}
        def command(args, **kwargs):
            captured['args'] = args
            captured['netrc'] = Path(args[args.index('--netrc-file')+1])
            self.assertIn('fixture-password', captured['netrc'].read_text())
            self.assertEqual(kwargs['input'], b'fixture body')
            return Mock(returncode=0, stdout=b'', stderr=b'')
        with patch.dict(f.os.environ, credentials), patch.object(f.shutil, 'which', return_value='curl'), \
             patch.object(f.subprocess, 'run', side_effect=command):
            f.curl_transfer('/frontend-deploy/portal/current.json.upload', b'fixture body')
        args = captured['args']
        self.assertEqual(args[1], '--disable')
        self.assertIn('--ftp-pasv', args)
        self.assertEqual(args[args.index('--proto')+1], '=ftp')
        self.assertTrue(args[-1].startswith('ftp://ftp.example.test:21/'))
        self.assertNotIn('fixture-password', ' '.join(args))
        self.assertNotIn('fixture-user', ' '.join(args))
        self.assertNotIn('--ssl', args)
        self.assertNotIn('--retry', args)
        self.assertFalse(captured['netrc'].exists())

    def test_native_curl_errors_do_not_log_server_output(self):
        with patch.dict(f.os.environ, {'LOCAWEB_FTP_HOST': 'ftp.example.test',
                                       'LOCAWEB_FTP_USER': 'fixture-user', 'LOCAWEB_FTP_PASSWORD': 'fixture-secret'}), \
             patch.object(f.shutil, 'which', return_value='curl'), \
             patch.object(f.subprocess, 'run', return_value=Mock(returncode=28, stdout=b'', stderr=b'fixture-secret')):
            with self.assertRaisesRegex(RuntimeError, 'native_ftp_error_28') as error:
                f.curl_transfer('/frontend-deploy/portal/current.json.upload', b'fixture body')
        self.assertNotIn('fixture-secret', json.dumps(f.error_report(error.exception)))


class FrontendControlReconnectTests(unittest.TestCase):
    credentials = {'LOCAWEB_FTP_HOST': 'ftp.example.test', 'LOCAWEB_FTP_USER': 'fixture-user',
                   'LOCAWEB_FTP_PASSWORD': 'fixture-secret', 'LOCAWEB_FTP_PORT': '21'}

    def client(self, *, connect_error=None, login_error=None, home='/'):
        client = Mock()
        client.connect.side_effect = connect_error
        client.login.side_effect = login_error
        client.pwd.return_value = home
        return client

    def test_fresh_connections_retry_reset_and_timeout_with_bounded_backoff(self):
        first = self.client(connect_error=TimeoutError('fixture-secret'))
        second = self.client(login_error=ConnectionResetError(104, 'fixture-secret'))
        final = self.client()
        with patch.dict(f.os.environ, self.credentials), patch.object(f, 'CONTROL_RETRIES', 0), \
             patch.object(f, 'PassiveFTP', side_effect=[first, second, final]), \
             patch.object(f.time, 'sleep') as sleep, patch.object(f, 'curl_transfer') as transfer:
            self.assertIs(f.connect(), final)
            self.assertEqual(f.CONTROL_RETRIES, 2)
            self.assertEqual([call.args for call in sleep.call_args_list], [(5,), (15,)])
            transfer.assert_not_called()
        for client in [first, second, final]:
            client.connect.assert_called_once_with('ftp.example.test', 21, timeout=20)
        first.close.assert_called_once()
        second.close.assert_called_once()
        final.set_pasv.assert_called_once_with(True)
        final.close.assert_not_called()

    def test_exhausted_control_connections_fail_closed_and_do_not_expose_replies(self):
        clients = [self.client(connect_error=TimeoutError('fixture-secret')) for _ in range(3)]
        with patch.dict(f.os.environ, self.credentials), patch.object(f, 'CONTROL_RETRIES', 0), \
             patch.object(f, 'PassiveFTP', side_effect=clients) as factory, patch.object(f.time, 'sleep') as sleep:
            with self.assertRaises(TimeoutError) as error:
                f.connect()
            self.assertEqual(factory.call_count, 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(f.error_report(error.exception), {'error_type': 'TimeoutError', 'ftp_operation': 'connect'})
        for client in clients:
            client.close.assert_called_once()

    def test_authentication_and_wrong_home_are_never_retried(self):
        for client, exception in [(self.client(login_error=ftplib.error_perm('530 fixture-secret')), ftplib.error_perm),
                                  (self.client(home='/another-home'), RuntimeError)]:
            with self.subTest(exception=exception), patch.dict(f.os.environ, self.credentials), \
                 patch.object(f, 'PassiveFTP', return_value=client) as factory, patch.object(f.time, 'sleep') as sleep:
                with self.assertRaises(exception) as error:
                    f.connect()
                factory.assert_called_once()
                sleep.assert_not_called()
                client.close.assert_called_once()
                self.assertNotIn('fixture-secret', json.dumps(f.error_report(error.exception)))

    def test_port_policy_precedes_any_connection(self):
        with patch.dict(f.os.environ, {**self.credentials, 'LOCAWEB_FTP_PORT': '990'}), \
             patch.object(f, 'PassiveFTP') as factory:
            with self.assertRaisesRegex(ValueError, 'ftp_port_must_be_21'):
                f.connect()
            factory.assert_not_called()

    def test_successful_native_upload_is_not_repeated_after_control_handshake_reset(self):
        ftp = FakeFTP()
        ftp.close = Mock()
        ftp.connect = Mock()
        ftp.login = Mock()
        ftp.set_pasv = Mock()
        ftp.pwd = Mock(return_value='/')
        failed = self.client(connect_error=ConnectionResetError(104, 'fixture-secret'))
        native = []
        def transfer(path, raw=None):
            native.append(('stor' if raw is not None else 'retr', path))
            if raw is not None:
                ftp.files[path] = raw
                return b''
            return ftp.files[path]
        path = '/public_html/eleicoes/frontend-releases/'+'a'*40+'/composition.css'
        with patch.dict(f.os.environ, self.credentials), patch.object(f, 'CONTROL_RETRIES', 0), \
             patch.object(f, 'PassiveFTP', side_effect=[failed, ftp, ftp, ftp]), patch.object(f.time, 'sleep'):
            transport = f.Transport(ftp, reconnect=f.connect, transfer=transfer)
            transport.put(path, b'fixture stylesheet')
            self.assertEqual(ftp.files[path], b'fixture stylesheet')
            self.assertEqual(sum(operation == 'stor' for operation, _ in native), 1)
            self.assertEqual(sum(operation == 'rename' for operation, _ in ftp.events), 1)
            self.assertEqual(f.CONTROL_RETRIES, 1)
            self.assertEqual(transport.reconciled_transfers, 0)

    def test_operation_diagnostics_keep_destination_guards_and_omit_secrets(self):
        ftp = Mock()
        ftp.sendcmd.side_effect = TimeoutError('fixture-secret')
        transport = f.Transport(ftp)
        with self.assertRaises(TimeoutError) as error:
            transport.metadata('/frontend-deploy/portal/current.json')
        self.assertEqual(f.error_report(error.exception)['ftp_operation'], 'metadata')
        with self.assertRaises(ValueError):
            transport._rename('/public_html/eleicoes/a.upload', '/public_html/eleicoes/unsafe.php')
        ftp.rename.assert_not_called()
        ftp.rename.side_effect = TimeoutError('fixture-secret')
        with self.assertRaises(TimeoutError) as error:
            transport._rename('/public_html/eleicoes/index.html.upload', '/public_html/eleicoes/index.html')
        result = f.error_report(error.exception)
        self.assertEqual(result['ftp_operation'], 'rename')
        self.assertNotIn('fixture-secret', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
