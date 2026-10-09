"""Bounded synthetic FTP diagnostic. Not an election/code delivery mechanism.

The default prints a plan without reading credentials or accessing the network.
Remote writes require separate human approval AND the exact namespace argument.
Existing publisher isolation/authentication/integrity gates are unchanged.
"""
import argparse
import ftplib
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from collector.src.ftp_safety import SENSITIVE_PATHS, validate_credentials_file

PARENT = '/ftp-inbox/elections/staging'
NAMESPACE = PARENT + '/ftp-staging-pr75-etapa11'
PART = NAMESPACE + '/probe.json.part'
FINAL = NAMESPACE + '/probe.json'
PAYLOAD = b'{"fixture_only":true,"probe":"pr75-etapa11","payload":"synthetic"}\n'
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


def plan():
    return {'fixture_only': True, 'namespace': NAMESPACE,
            'files': [PART, FINAL], 'sha256': DIGEST, 'bytes': len(PAYLOAD),
            'production_isolation': 'not_guaranteed',
            'remote_writes_authorized': False,
            'effects': ['MKD namespace', 'STOR .part', 'RETR checksum',
                        'RNFR/RNTO .part to final', 'RETR final checksum'],
            'cleanup': 'Separate approval: verify exact files/bytes, DELE, RMD leaf only'}


def approved(namespace):
    if namespace != NAMESPACE:
        raise ValueError('exact_namespace_approval_required')


def inspect(ftp):
    """PWD/MLST only. Never reads protected content or performs writes."""
    result = {'pwd': ftp.pwd(), 'control_accessible': [],
              'metadata_inconclusive': [], 'paths': {},
              'production_isolation': 'not_guaranteed'}
    paths = [NAMESPACE, PARENT, '/public_html',
             '/ftp-inbox/code/staging', '/ftp-inbox/code/production',
             '/ftp-inbox/elections/production']
    sensitive = ['/' + path for path in SENSITIVE_PATHS]
    for path in paths + sensitive:
        try:
            response = ftp.sendcmd('MLST ' + path)
        except ftplib.error_perm as error:
            denied = str(error).startswith('550')
            result['paths'][path] = {'status': 'denied_550' if denied else 'inconclusive'}
            if not denied:
                result['metadata_inconclusive'].append(path)
        else:
            facts = {}
            for line in response.splitlines():
                for field in line.strip().split(' ', 1)[0].split(';'):
                    if '=' in field:
                        name, value = field.split('=', 1)
                        if name.lower() in {'type', 'perm', 'unix.uid', 'unix.gid',
                                            'unix.mode', 'unique', 'size'}:
                            facts[name.lower()] = value
            result['paths'][path] = {'status': 'visible', 'facts': facts}
            if path in sensitive:
                result['control_accessible'].append(path)
    return result


def retrieve(ftp, path):
    """Read only our bounded synthetic file; reject oversized responses."""
    raw = bytearray()
    def receive(block):
        if len(raw) + len(block) > len(PAYLOAD):
            raise ValueError('unexpected_probe_bytes')
        raw.extend(block)
    ftp.retrbinary('RETR ' + path, receive, blocksize=1024)
    if bytes(raw) != PAYLOAD or hashlib.sha256(raw).hexdigest() != DIGEST:
        raise ValueError('probe_checksum_mismatch')


def transfer(ftp, namespace=None):
    approved(namespace)  # Must precede even metadata/network operations.
    ftp.cwd(PARENT)  # Parents must be provisioned under separate approval.
    try:
        ftp.sendcmd('MLST ' + NAMESPACE)
    except ftplib.error_perm as error:
        if not str(error).startswith('550'):
            raise ValueError('probe_namespace_unverifiable') from None
    else:
        raise ValueError('probe_namespace_already_visible')
    # MKD is the exclusive claim. Never adopt/overwrite an existing namespace.
    ftp.mkd(NAMESPACE)
    ftp.storbinary('STOR ' + PART, io.BytesIO(PAYLOAD))
    retrieve(ftp, PART)
    ftp.rename(PART, FINAL)
    retrieve(ftp, FINAL)
    return {'status': 'synthetic_transport_verified', 'namespace': NAMESPACE,
            'sha256': DIGEST, 'cleanup_pending': True,
            'production_isolation': 'not_guaranteed'}


def cleanup(ftp, namespace=None):
    approved(namespace)
    entries = list(ftp.mlsd(NAMESPACE))
    if not entries:
        raise ValueError('empty_or_hidden_probe_namespace')
    # No recursion, symlinks, extra/hidden objects, or permission changes.
    for name, facts in entries:
        if name not in {'probe.json.part', 'probe.json'} or facts.get('type') != 'file':
            raise ValueError('unexpected_probe_inventory')
    for name, _ in entries:
        retrieve(ftp, NAMESPACE + '/' + name)
    for name, _ in entries:
        ftp.delete(NAMESPACE + '/' + name)
    ftp.rmd(NAMESPACE)  # Fails safely if anything else remains.
    return {'status': 'synthetic_probe_removed', 'namespace': NAMESPACE}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', nargs='?', default='plan',
                        choices=['plan', 'inspect', 'transfer', 'cleanup'])
    parser.add_argument('--credentials-file', type=Path,
                        default=ROOT / '.secrets/ftp.env')
    parser.add_argument('--approved-namespace')
    args = parser.parse_args(argv)
    if args.operation == 'plan':
        print(json.dumps(plan()))
        return
    if args.operation in {'transfer', 'cleanup'}:
        approved(args.approved_namespace)
    # Reuse the existing file; never export, print, copy or change its modes.
    validate_credentials_file(args.credentials_file)
    from dotenv import dotenv_values
    credentials = dotenv_values(args.credentials_file, interpolate=False)
    if str(credentials.get('LOCAWEB_FTP_PORT', '21')) != '21':
        raise ValueError('ftp_port_must_be_21')
    if not all(credentials.get(name) for name in
               ['LOCAWEB_FTP_HOST', 'LOCAWEB_FTP_USER', 'LOCAWEB_FTP_PASSWORD']):
        raise ValueError('missing_ftp_credentials')
    ftp = ftplib.FTP()
    try:
        ftp.connect(credentials['LOCAWEB_FTP_HOST'], 21, timeout=5)
        ftp.login(credentials['LOCAWEB_FTP_USER'], credentials['LOCAWEB_FTP_PASSWORD'])
        ftp.set_pasv(True)
        result = inspect(ftp) if args.operation == 'inspect' else (
            transfer(ftp, args.approved_namespace) if args.operation == 'transfer'
            else cleanup(ftp, args.approved_namespace))
        print(json.dumps(result))
    finally:
        ftp.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Exception messages can carry server/credential data; never emit them.
        print(json.dumps({'status': 'failed', 'error_type': type(error).__name__}))
        raise SystemExit(1)
