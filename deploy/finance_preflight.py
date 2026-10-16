"""Read-only proof that the active Raio-X can consume this checkout's export.

The financial Actions job holds locaweb-frontend-production through its final
upload verification. Never wait for, dispatch, recover or publish a frontend here.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile

from . import frontend as f


def require_idle(transport):
    for component in ('portal', 'raio-x'):
        base = f.PRIVATE + '/' + component
        if transport.metadata(base + '/lock/') is not None:
            raise RuntimeError('frontend_requires_recovery')
        raw = transport.read(base + '/pending.json', optional=True)
        if raw is not None and f.decode(raw).get('status') not in {'complete', 'restored'}:
            raise RuntimeError('frontend_requires_recovery')


def verify_reader(transport, *, root=f.ROOT, http=f.http_read):
    require_idle(transport)
    path = f.state_path('raio-x')
    before = transport.read(path)
    manifest = f.decode(before).get('manifest')
    if not isinstance(manifest, dict):
        raise RuntimeError('no_published_finance_reader')
    f.validate_manifest(manifest, 'raio-x')
    # Commit-independent source identity accepts a previously published commit
    # with identical content, including runs triggered by data-only bot commits.
    with tempfile.TemporaryDirectory() as folder:
        expected = f.build('raio-x', manifest['commit'], Path(folder) / 'expected',
                           root=root, validate=False)
    if (manifest.get('source_sha256') != expected['source_sha256']
            or manifest['files'] != expected['files']):
        raise RuntimeError('compatible_finance_reader_not_published')
    verified = f.status(transport, 'raio-x', http=http)
    require_idle(transport)
    if (verified['lock_present'] or verified['pending'] not in {None, 'complete', 'restored'}
            or verified['commit'] != manifest['commit'] or transport.read(path) != before):
        raise RuntimeError('finance_reader_changed_during_preflight')
    return {'status': 'compatible', 'component': 'raio-x', 'commit': manifest['commit'],
            'source_sha256': expected['source_sha256'], 'ftp_https_verified': True}


def verify_live_reader():
    # Reuse the existing passive FTP21 reader and credentials. This gate
    # never calls STOR, MKD, rename, recovery or the financial writer.
    transport = f.Transport(f.connect(), reconnect=f.connect, transfer=f.curl_transfer)
    try:
        return verify_reader(transport)
    finally:
        transport.ftp.close()


def main():
    try:
        result = verify_live_reader()
    except Exception as error:
        print(json.dumps({'status': 'blocked', **f.error_report(error)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
