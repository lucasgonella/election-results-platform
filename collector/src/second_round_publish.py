"""Isolated round-two FTP transactions with durable local journal and reconciliation.

Single trusted app01 writer, fenced by local flock and a remote owner-bound MKD.
FTP rename is a controlled marker replacement, not a distributed transaction.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import ftplib
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, build_opener

from deploy import frontend as wire
from .election_release import META, UFS, canonical, digest, parse, tree, transition
from .second_round_integrity import verify_values

SITE = '/public_html/data/turnos/2'
PRIVATE = '/election-round2-deploy'
STATE = '/var/lib/election-round2'


def now():
    return datetime.now(timezone.utc).isoformat()


def identity(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('invalid_second_round_release_id')
    return value


def save(path, value):
    """Durable replace on the local filesystem; no shared first-round files."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(value)
    fd, temporary = tempfile.mkstemp(prefix='.round2-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def load(path):
    return parse(path.read_bytes()) if path.exists() else None


@contextmanager
def local_lock(state):
    state.mkdir(parents=True, exist_ok=True)
    path = state / 'writer.lock'
    with path.open('a+b') as stream:
        os.chmod(path, 0o600)
        try: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('second_round_writer_busy') from None
        yield


def result_name(name):
    return name in META or bool(re.fullmatch(r'(' + '|'.join(UFS + ['br', 'zz']) +
        r')/(president|governor)\.json', name))


class Transport(wire.Transport):
    def metadata(self, path):
        # Safe read-only retry. Long HTTPS checks may expire an FTP control socket.
        import time
        for attempt in range(3):
            try: return super().metadata(path)
            except (OSError, EOFError, ftplib.error_temp) as error:
                if isinstance(error, ftplib.error_temp) and not str(error).startswith('421'):
                    raise
                if attempt == 2 or self.reconnect is None: raise
                self.ftp.close()
                time.sleep(attempt + 1)
                self.ftp = self.reconnect()

    def allowed(self, path):
        if (not isinstance(path, str) or not path.startswith('/')
                or any(c in path for c in ('\r', '\n', '\\'))
                or '..' in PurePosixPath(path).parts or '//' in path):
            raise ValueError('unsafe_second_round_path')
        if path.rstrip('/') in {str(p) for p in PurePosixPath(SITE).parents if str(p) not in {'/', '/public_html'}}:
            return path  # read/MKD ancestors only, never writable
        if not any(path.rstrip('/') == root or path.startswith(root + '/') for root in (SITE, PRIVATE)):
            raise ValueError('outside_second_round_namespace')
        return path

    def writable(self, path):
        self.allowed(path)
        if path == SITE + '/version.json': return path
        relative = path.removeprefix(SITE + '/releases/')
        sid, _, name = relative.partition('/')
        if re.fullmatch('[a-f0-9]{64}', sid) and result_name(name): return path
        if path == PRIVATE + '/lock/owner.json': return path
        match = re.fullmatch(re.escape(PRIVATE) + r'/transactions/([a-f0-9]{64})/(descriptor|before-marker)\.json', path)
        if match: return path
        raise ValueError('protected_second_round_destination')

    def put(self, path, raw, *, replace=False):
        if replace and path.startswith(SITE + '/releases/'):
            raise ValueError('immutable_second_round_release')
        return super().put(path, raw, replace=replace)

    def directory(self, path):
        # Do not create or modify the shared /data parent.
        if path.rstrip('/') == '/public_html/data':
            if not self.metadata(path + '/'):
                raise RuntimeError('missing_shared_data_parent')
            return
        try:
            return super().directory(path)
        except (OSError, EOFError, ftplib.error_temp):
            if self.reconnect is None: raise
            self.ftp.close()
            self.ftp = self.reconnect()
            actual = self.metadata(path + '/')
            if actual is None or actual['type'] != 'dir':
                raise RuntimeError('second_round_directory_creation_unconfirmed') from None
            # Lost MKD response: adopt only the directory actually inspected.
            return


def native_transfer(path, raw=None):
    checker = Transport(None)
    checker.allowed(path)
    if raw is not None:
        if not path.endswith('.upload'): raise ValueError('temporary_upload_required')
        checker.writable(path.removesuffix('.upload'))
    host = os.environ['LOCAWEB_FTP_HOST']
    if not re.fullmatch('[A-Za-z0-9.-]+', host): raise ValueError('invalid_ftp_host')
    def token(value):
        if '\n' in value or '\r' in value: raise ValueError('invalid_ftp_credential_format')
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    with tempfile.TemporaryDirectory() as folder:
        path_netrc = Path(folder) / 'ftp.netrc'
        path_netrc.touch(mode=0o600)
        path_netrc.write_text('machine ' + host + ' login ' + token(os.environ['LOCAWEB_FTP_USER']) +
            ' password ' + token(os.environ['LOCAWEB_FTP_PASSWORD']) + '\n')
        command = ['curl', '--disable', '--silent', '--fail', '--proto', '=ftp', '--ftp-pasv',
            '--max-time', '45', '--connect-timeout', '15', '--max-filesize', str(wire.MAX_BYTES),
            '--netrc-file', str(path_netrc), '--noproxy', '*']
        if raw is not None: command += ['--upload-file', '-']
        command += ['ftp://' + host + ':21/' + quote(path.lstrip('/'), safe='/')]
        result = subprocess.run(command, input=raw, capture_output=True, timeout=50)
        if result.returncode: raise RuntimeError('native_ftp_error_' + str(result.returncode))
        if len(result.stdout) > wire.MAX_BYTES: raise ValueError('oversized_ftp_file')
        return result.stdout


def ftp_connect():
    import time
    for attempt in range(3):
        try:
            ftp = wire.connect()
            ftp.timeout = 15
            ftp.sock.settimeout(15)
            return ftp
        except (OSError, EOFError):
            if attempt == 2: raise
            time.sleep(attempt + 1)


def connect():
    return Transport(ftp_connect(), reconnect=ftp_connect, transfer=native_transfer)


def http_read(relative):
    url = 'https://afgnet.com.br/data/turnos/2/' + relative
    try:
        with build_opener(wire.NoRedirect).open(Request(url, headers={
                'Cache-Control': 'no-cache', 'Accept-Encoding': 'identity'}), timeout=20) as response:
            if response.status != 200 or response.geturl() != url:
                raise RuntimeError('invalid_second_round_https_response')
            raw = response.read(wire.MAX_BYTES + 1)
            if len(raw) > wire.MAX_BYTES: raise ValueError('oversized_public_file')
            return raw
    except HTTPError as error:
        if error.code == 404: return None
        raise


def describe(values):
    verified = verify_values(values, strict=True)
    if not any(parse(raw)['snapshot']['sections']['totalized'] > 0 for name, raw in values.items() if name not in META):
        raise ValueError('second_round_apuration_not_started')
    return verified


def marker_for(verified):
    desc = verified['descriptor']
    return canonical({'schema_version': 1, 'environment': 'oficial', 'round': 2,
        'generated_at': desc['generated_at'], 'snapshot_id': verified['snapshot_id']})


def validate_descriptor(desc, sid):
    if digest(canonical(desc)) != identity(sid) or desc.get('round') != 2 or desc.get('environment') != 'oficial':
        raise ValueError('invalid_second_round_descriptor')
    names = desc.get('files', {})
    if not META <= set(names) or not 4 <= len(names) <= 59 or any(not result_name(n) for n in names):
        raise ValueError('invalid_second_round_inventory')
    for entry in names.values():
        identity(entry.get('sha256'))
        if type(entry.get('size')) is not int or not 0 < entry['size'] <= wire.MAX_BYTES:
            raise ValueError('invalid_second_round_file_size')


class Publisher:
    """Caller holds local_lock for every mutation, including orphan recovery."""
    def __init__(self, transport, state, *, http=http_read, fault=lambda _: None):
        self.t = transport
        self.state = Path(state)
        self.http = http
        self.fault = fault
        self.job_path = self.state / 'pending.json'
        self.checkpoint_path = self.state / 'checkpoint.json'

    def marker(self):
        ftp = self.t.read(SITE + '/version.json', optional=True)
        https = self.http('version.json')
        if ftp != https: raise RuntimeError('second_round_marker_visibility_unknown')
        if ftp:
            item = parse(ftp)
            identity(item.get('snapshot_id'))
            if item.get('environment') != 'oficial' or item.get('round') != 2:
                raise ValueError('invalid_remote_second_round_marker')
        return ftp

    def release(self, marker, *, expected=None):
        item = parse(marker)
        sid = identity(item['snapshot_id'])
        desc = parse(self.t.read(PRIVATE + '/transactions/' + sid + '/descriptor.json'))
        validate_descriptor(desc, sid)
        if expected is not None and expected != desc: raise ValueError('remote_descriptor_conflict')
        values = {}
        for name, entry in sorted(desc['files'].items()):
            raw = self.t.read(SITE + '/releases/' + sid + '/' + name)
            wire.verify_bytes(raw, entry)
            if self.http('releases/' + sid + '/' + name) != raw:
                raise RuntimeError('second_round_https_hash_mismatch')
            values[name] = raw
        verified = describe(values)
        if verified['descriptor'] != desc or marker_for(verified) != marker:
            raise ValueError('second_round_release_identity_mismatch')
        return values, verified

    def status(self):
        marker = self.marker()
        verified = self.release(marker)[1] if marker else None
        checkpoint = load(self.checkpoint_path)
        return {'status': 'verified' if marker else 'awaiting_official_round_two_data',
                'snapshot_id': verified['snapshot_id'] if verified else None,
                'checkpoint_matches': (checkpoint or {}).get('snapshot_id') == (verified or {}).get('snapshot_id'),
                'pending': bool(load(self.job_path)), 'remote_lock': self.t.metadata(PRIVATE + '/lock/') is not None,
                'checked_at': now()}

    def remote_lock(self, job):
        self.t.directory(PRIVATE)
        lock = PRIVATE + '/lock'
        owner = canonical({'transaction': job['snapshot_id'], 'owner': job['owner']})
        if self.t.metadata(lock + '/') is None:
            self.t.ftp.mkd(lock)  # Never steal by age.
            self.t.put(lock + '/owner.json', owner)
        elif self.t.read(lock + '/owner.json', optional=True) != owner:
            raise RuntimeError('unknown_second_round_lock_owner')

    def finish(self, job):
        # Proof before adopting checkpoint; a checkpoint failure leaves the journal.
        self.release(bytes.fromhex(job['marker']), expected=job['descriptor'])
        if self.marker() != bytes.fromhex(job['marker']):
            raise RuntimeError('second_round_selection_changed')
        receipt = {'status': 'published', 'round': 2, 'snapshot_id': job['snapshot_id'],
                   'verified_at': now(), 'activation': 'ftp_marker_rename', 'multinode_guarantee': False}
        save(self.state / 'receipts' / (job['snapshot_id'] + '.json'), receipt)
        self.fault('before_checkpoint')
        save(self.checkpoint_path, receipt)
        self.fault('after_checkpoint')
        job['phase'] = 'committed'
        save(self.job_path, job)
        owner = self.t.read(PRIVATE + '/lock/owner.json', optional=True)
        expected = canonical({'transaction': job['snapshot_id'], 'owner': job['owner']})
        if self.t.metadata(PRIVATE + '/lock/') is not None:
            if owner != expected: raise RuntimeError('unknown_second_round_lock_owner')
            self.t.ftp.delete(PRIVATE + '/lock/owner.json')
            self.fault('after_owner_cleanup')
            self.t.ftp.rmd(PRIVATE + '/lock')
        # Keep an immutable local journal; no releases/backups are deleted.
        save(self.state / 'journals' / (job['snapshot_id'] + '.json'), job)
        save(self.job_path, None)
        return receipt

    def recover(self):
        job = load(self.job_path)
        if not job:
            if self.t.metadata(PRIVATE + '/lock/') is not None:
                raise RuntimeError('orphan_lock_without_trusted_journal')
            return self.reconcile()
        identity(job['snapshot_id'])
        validate_descriptor(job['descriptor'], job['snapshot_id'])
        selected = self.marker()  # Resolve activation outcome before any write.
        old = bytes.fromhex(job['before']) if job['before'] else None
        new = bytes.fromhex(job['marker'])
        if selected not in (old, new): raise RuntimeError('external_second_round_marker')
        if job['phase'] == 'committed':
            # Crash during lock cleanup: only a locally committed, verified job
            # can release an empty ownerless lock after local flock acquisition.
            self.release(new, expected=job['descriptor'])
            lock = PRIVATE + '/lock'
            if self.t.metadata(lock + '/') and self.t.read(lock + '/owner.json', optional=True) is None:
                self.t.ftp.rmd(lock)
            return self.finish(job)
        self.remote_lock(job)
        if selected == new: return self.finish(job)
        if old: self.release(old)
        package = Path(job['package'])
        values = tree(package)
        verified = describe(values)
        if verified['descriptor'] != job['descriptor']: raise ValueError('local_pending_package_changed')
        # Only temporary names belonging to this persisted transaction are known.
        for name, raw in sorted(values.items()):
            path = SITE + '/releases/' + job['snapshot_id'] + '/' + name
            existing = self.t.read(path, optional=True)
            if existing is not None:
                if existing != raw: raise ValueError('immutable_second_round_collision')
                continue
            temporary = self.t.read(path + '.upload', optional=True)
            if temporary is not None:
                if temporary == raw:
                    self.t.ftp.rename(path + '.upload', path)
                else:
                    self.t.ftp.delete(path + '.upload')
            if self.t.read(path, optional=True) is None: self.t.put(path, raw)
            self.fault('after_file')
        self.t.put(PRIVATE + '/transactions/' + job['snapshot_id'] + '/descriptor.json', canonical(job['descriptor']))
        self.release(new, expected=job['descriptor'])
        job['phase'] = 'verified'
        save(self.job_path, job)
        self.fault('before_activation')
        if self.marker() != old: raise RuntimeError('external_second_round_marker')
        # A marker temporary left by a crash is reconciled, never blindly replayed.
        temporary = self.t.read(SITE + '/version.json.upload', optional=True)
        if temporary is not None:
            if temporary != new: raise RuntimeError('unknown_marker_temporary')
            self.t.ftp.rename(SITE + '/version.json.upload', SITE + '/version.json')
        else:
            self.t.put(SITE + '/version.json', new, replace=True)
        self.fault('after_activation')
        return self.finish(job)

    def reconcile(self):
        if load(self.job_path): return self.recover()
        if self.t.metadata(PRIVATE + '/lock/') is not None:
            raise RuntimeError('orphan_lock_without_trusted_journal')
        marker = self.marker()
        checkpoint = load(self.checkpoint_path)
        if not marker:
            if checkpoint: raise RuntimeError('remote_second_round_marker_missing')
            return {'status': 'awaiting_official_round_two_data'}
        verified = self.release(marker)[1]
        if checkpoint and checkpoint['snapshot_id'] != verified['snapshot_id']:
            # Adopt only a transaction previously verified by this trusted host.
            receipt = load(self.state / 'receipts' / (verified['snapshot_id'] + '.json'))
            if not receipt: raise RuntimeError('unrecognized_second_round_marker')
            save(self.checkpoint_path, receipt)
        elif not checkpoint:
            raise RuntimeError('remote_release_without_local_receipt')
        return {'status': 'verified', 'snapshot_id': verified['snapshot_id']}

    def publish(self, directory):
        self.reconcile()  # Finish earlier transaction before considering newer data.
        values = tree(Path(directory))
        verified = describe(values)
        before = self.marker()
        if before:
            prior, _ = self.release(before)
            # Different fetch times alone never create a new public release.
            if verified['snapshot_id'] == parse(before)['snapshot_id']:
                return {'status': 'unchanged', 'snapshot_id': verified['snapshot_id']}
            before_names, after_names = set(prior) - META, set(values) - META
            if not before_names <= after_names: raise ValueError('second_round_inventory_regression')
            for name in before_names:
                old, new = parse(prior[name]), parse(values[name])
                if {str(c['tse_candidate_seq']) for c in old['candidates']} != {str(c['tse_candidate_seq']) for c in new['candidates']}:
                    raise ValueError('second_round_roster_change_requires_review')
                transition(name, old, new)
        checkpoint = load(self.checkpoint_path)
        if checkpoint and (not before or checkpoint['snapshot_id'] != parse(before)['snapshot_id']):
            raise RuntimeError('second_round_checkpoint_mismatch')
        import secrets
        job = {'schema': 1, 'snapshot_id': verified['snapshot_id'], 'owner': secrets.token_hex(32),
            'phase': 'prepared', 'package': str(Path(directory).resolve()), 'descriptor': verified['descriptor'],
            'before': before.hex() if before else None, 'marker': marker_for(verified).hex(), 'created_at': now()}
        # Persist intended work before acquiring the remote lock.
        save(self.job_path, job)
        self.fault('after_journal')
        self.remote_lock(job)
        self.fault('after_lock')
        if before:
            self.t.put(PRIVATE + '/transactions/' + job['snapshot_id'] + '/before-marker.json', before)
        return self.recover()
