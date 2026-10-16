"""Remote helper contract, runnable with stdlib only on hosting Python 3.6."""
import base64
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import ssh_remote as remote


class HostingPythonContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def call(self, scope, op, **args):
        return remote.handle(dict(scope=scope, op=op, **args), str(self.root))

    def test_metadata_and_reads_in_every_publisher_scope(self):
        for scope, roots in remote.SCOPES.items():
            name = roots[0] + '/compat.json'
            path = self.root / name.lstrip('/')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'{}')
            self.assertEqual(self.call(scope, 'metadata', path=name), {'type':'file','size':'2'})
            self.assertEqual(base64.b64decode(self.call(scope, 'read', path=name)), b'{}')

    def test_frontend_private_metadata_commit(self):
        name = '/frontend-deploy/portal/current.json'
        path = self.root / name.lstrip('/')
        path.parent.mkdir(parents=True)
        old, new = b'{"version":1}', b'{"version":2}'
        path.write_bytes(old)
        stage = self.call('portal', 'reserve', nonce='a'*32)
        (self.root / stage.lstrip('/')).write_bytes(new)
        cached = self.call('portal', 'cache', path=stage, sha256=remote.sha(new))
        self.call('portal', 'commit', path=name, stage=cached, temporary=name+'.fixture.upload',
                  before=remote.sha(old), sha256=remote.sha(new), size=len(new), replace=True)
        self.assertEqual(path.read_bytes(), new)

    def test_scopes_cannot_read_other_components(self):
        for scope, name in [('portal','/public_html/eleicoes/goias/raio-x/index.html'),
                            ('raio-x','/public_html/eleicoes/goias/raio-x/data/go-2026.json'),
                            ('first-production','/public_html/data/turnos/2/version.json')]:
            with self.assertRaises(ValueError): self.call(scope, 'metadata', path=name)

    def test_symlink_is_not_followed(self):
        directory = self.root/'frontend-deploy/portal'
        directory.mkdir(parents=True)
        (directory/'current.json').symlink_to(self.root/'unknown')
        with self.assertRaises(ValueError):
            self.call('portal', 'read', path='/frontend-deploy/portal/current.json')


if __name__ == '__main__':
    unittest.main()
