"""Build a NEW local synthetic test namespace. No network or activation.

Uses the same 137-target fixtures as the publication tests (dev dependencies).
Future remote installation/writes require separate authorization.
"""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import socket
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tests'))
from test_ftp_publication import dataset

REMOTE_HOME = '/home/storage/4/b7/e0/afgnet1'
REMOTE_PRIVATE = REMOTE_HOME + '/ftp-staging-pr75'
REMOTE_PUBLIC = REMOTE_HOME + '/public_html/eleicoes/__staging_pr75'
ROUTE_URL = 'https://afgnet.com.br/eleicoes/__staging_pr75/probe.php'
ROUTE_HTACCESS = b'Options -Indexes\nDirectoryIndex probe.php\n'


def prepare_route(source, output):
    """Reuse a verified fixture package; prepare a read-only split route locally.

    The fresh route credential is separate from both source/production keys.
    It is NOT part of a generic artifact; its private installation must be
    explicitly approved along with the exact installation plan.
    """
    source, output = Path(source), Path(output)
    if not output.name.startswith('ftp-staging-') or output.exists() or output.is_symlink():
        raise ValueError('new_fixture_namespace_required')
    manifest = json.loads((source/'transfer-manifest.json').read_text())
    files = manifest.get('files', {})
    if manifest.get('fixture_only') is not True or len(files) != 147:
        raise ValueError('invalid_fixture_inventory')
    for name, digest in files.items():
        relative = Path(name)
        path = source/relative
        if relative.is_absolute() or '..' in relative.parts or not path.resolve().is_relative_to(source.resolve()):
            raise ValueError('invalid_fixture_inventory')
        if any((source/parent).is_symlink() for parent in [relative, *relative.parents]) or not path.is_file():
            raise ValueError('invalid_fixture_inventory')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('fixture_checksum_mismatch')
    required = ['private/ftp-publication.php', 'public/probe.php', 'public/probe-marker.json']
    original_bytes = sum((source/name).stat().st_size for name in required)
    if (source/'public/probe-marker.json').read_bytes() != b'{"fixture":"replace_a"}':
        raise ValueError('unexpected_initial_fixture')
    output.mkdir(parents=True, mode=0o700)
    (output/'private').mkdir(mode=0o700)
    (output/'public').mkdir(mode=0o755)
    shutil.copyfile(source/'private/ftp-publication.php', output/'private/ftp-publication.php')
    shutil.copyfile(ROOT/'deploy/locaweb/ftp-staging-probe.php', output/'public/probe.php')
    shutil.copyfile(source/'public/probe-marker.json', output/'public/probe-marker.json')
    (output/'public/.htaccess').write_bytes(ROUTE_HTACCESS)
    config = {'fixture_only': True, 'environment': 'fixture', 'root': REMOTE_PRIVATE,
              'public_root': REMOTE_PUBLIC, 'allowed_actions': ['runtime', 'read'],
              'activation_host': '', 'fixture_key': secrets.token_hex(32)}
    config_path = output/'private/staging-config.json'
    config_path.write_text(json.dumps(config, sort_keys=True, separators=(',', ':')), encoding='utf-8')
    config_path.chmod(0o600)
    destinations = {
        'private/ftp-publication.php': '/ftp-staging-pr75/private/ftp-publication.php',
        'private/staging-config.json': '/ftp-staging-pr75/private/staging-config.json',
        'public/probe.php': '/public_html/eleicoes/__staging_pr75/probe.php',
        'public/probe-marker.json': '/public_html/eleicoes/__staging_pr75/probe-marker.json',
        'public/.htaccess': '/public_html/eleicoes/__staging_pr75/.htaccess',
    }
    inventory = {name: {'ftp_destination': destination, 'bytes': (output/name).stat().st_size,
                        'sha256': hashlib.sha256((output/name).read_bytes()).hexdigest(),
                        'confidential': name == 'private/staging-config.json'}
                 for name, destination in destinations.items()}
    plan = {'fixture_only': True, 'remote_writes_authorized': False, 'url': ROUTE_URL,
            'private_root': REMOTE_PRIVATE, 'public_root': REMOTE_PUBLIC,
            'source_fixture_files_verified': len(files), 'original_initial_bytes': original_bytes,
            'files': inventory, 'allowed_actions': ['runtime', 'read'],
            'new_directories': ['/ftp-staging-pr75', '/ftp-staging-pr75/private',
                                '/public_html/eleicoes/__staging_pr75']}
    (output/'install-plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    (output/'transfer-manifest.json').write_text(json.dumps({
        'fixture_only': True, 'remote_installation_authorized': False,
        'files': {name: details['sha256'] for name, details in inventory.items() if not details['confidential']},
        'excluded': ['private/staging-config.json'],
    }, sort_keys=True), encoding='utf-8')
    return {'status': 'fixture_route_prepared', 'source_files_verified': len(files),
            'original_initial_bytes': original_bytes, 'url': ROUTE_URL}


def prepare(output):
    output=Path(output)
    if not output.name.startswith('ftp-staging-') or output.exists() or output.is_symlink():
        raise ValueError('new_fixture_namespace_required')
    output.mkdir(parents=True)
    for name in ['private','public','inbox','spool']:
        (output/name).mkdir(mode=0o700 if name!='public' else 0o755)
    dataset(output/'fixtures/full')
    dataset(output/'fixtures/delta',2,True)
    shutil.copyfile(ROOT/'deploy/locaweb/ftp-publication.php',output/'private/ftp-publication.php')
    shutil.copyfile(ROOT/'deploy/locaweb/ftp-staging-probe.php',output/'public/probe.php')
    # This is a disposable fixture key, never a copy of the production key.
    config={'fixture_only':True,'environment':'fixture','root':str(output.resolve()),
            'activation_host':socket.gethostname(),'fixture_key':secrets.token_hex(32)}
    path=output/'private/staging-config.json';path.write_text(json.dumps(config),encoding='utf-8');path.chmod(0o600)
    (output/'public/probe-marker.json').write_text('{"fixture":"replace_a"}',encoding='utf-8')
    # Transfer allowlist: deliberately excludes the local fixture key/config.
    # The remote probe needs a NEW server-side key and a remote-root binding.
    files = {}
    for path in sorted(output.rglob('*')):
        if path.is_file() and path != output/'private/staging-config.json':
            files[path.relative_to(output).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    (output/'transfer-manifest.json').write_text(json.dumps({
        'fixture_only': True, 'files': files,
        'excluded': ['private/staging-config.json'],
        'remote_installation_authorized': False,
    }, sort_keys=True), encoding='utf-8')
    return {'status':'fixture_prepared','targets':137}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--reuse-fixtures', type=Path)
    try:
        args = parser.parse_args()
        print(json.dumps(prepare_route(args.reuse_fixtures, args.output) if args.reuse_fixtures else prepare(args.output)))
    except Exception as error: print(json.dumps({'status':'failed','error_type':type(error).__name__}));raise SystemExit(1)
