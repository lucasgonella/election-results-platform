"""Offline protocol tests. No hosting, database, TSE or production access."""
import ftplib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

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

    def test_second_client_cannot_acquire_lock(self):
        with self.transport.lock('portal'):
            with self.assertRaises(ftplib.error_perm):
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


if __name__ == '__main__':
    unittest.main()
