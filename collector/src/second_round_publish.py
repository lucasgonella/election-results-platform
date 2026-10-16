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
import time
import threading
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, build_opener

from deploy import frontend as wire
from .election_release import META, UFS, canonical, digest, parse, tree, transition
from .second_round_integrity import verify_values
from .second_round_metrics import measure

SITE = '/public_html/data/turnos/2'
PRIVATE = '/election-round2-deploy'
STATE = '/var/lib/election-round2'


def now():
    return datetime.now(timezone.utc).isoformat()


def identity(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('invalid_second_round_release_id')
    return value


def save(path, value, *, mode=0o600):
    """Durable replace on the local filesystem; no shared first-round files."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(value)
    fd, temporary = tempfile.mkstemp(prefix='.round2-', dir=path.parent)
    try:
        os.fchmod(fd, mode)
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


def transaction_path(sid, name):
    # Full identity stays in the verified descriptor; prefix collisions fail closed.
    return PRIVATE + '/transactions/' + identity(sid)[:24] + '/' + name


def result_name(name):
    return name in META | {'portal.json'} or bool(re.fullmatch(r'(' + '|'.join(UFS + ['br', 'zz']) +
        r')/(president|governor)\.json', name))


class Transport(wire.Transport):
    def fork(self):
        if self.reconnect is None: return None
        child = Transport(self.reconnect(), reconnect=self.reconnect)
        child.metrics, child.metrics_lock = getattr(self, 'metrics', {}), getattr(self, 'metrics_lock', threading.Lock())
        return child

    def _readonly_retry(self, operation):
        # Replace the control socket before repeating any interrupted read.
        # Partial RETR bytes and unread responses must never be reused.
        import time
        for attempt in range(3):
            try: return operation()
            except (OSError, EOFError, ftplib.Error) as error:
                with getattr(self, 'metrics_lock', threading.Lock()):
                    metrics = getattr(self, 'metrics', {})
                    metrics['ftp_failures'] = metrics.get('ftp_failures', 0) + 1
                if not isinstance(error, (OSError, EOFError)) and not (isinstance(error, ftplib.error_temp) and str(error).startswith('421')):
                    raise
                if attempt == 2 or self.reconnect is None: raise
                self.ftp.close()
                time.sleep(attempt + 1)
                self.ftp = self.reconnect()

    def metadata(self, path):
        if getattr(self, '_reading', False):
            return super().metadata(path)
        return self._readonly_retry(lambda: super(Transport, self).metadata(path))

    def read(self, path, *, optional=False):
        self.allowed(path)
        # One three-attempt budget for MLST + RETR, not nested 3 x 3 retries.
        # This synchronous transport is used by one writer under local flock.
        self._reading = True
        try:
            return self._readonly_retry(
                lambda: super(Transport, self).read(path, optional=optional))
        finally:
            self._reading = False

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
        if path in {SITE + '/version.json', SITE + '/status.json'}: return path
        relative = path.removeprefix(SITE + '/releases/')
        sid, _, name = relative.partition('/')
        if re.fullmatch('[a-f0-9]{64}', sid) and result_name(name): return path
        if path == PRIVATE + '/lock/owner.json': return path
        match = re.fullmatch(re.escape(PRIVATE) + r'/transactions/([a-f0-9]{24})/(descriptor|before-marker)\.json', path)
        if match: return path
        raise ValueError('protected_second_round_destination')

    def put(self, path, raw, *, replace=False):
        if replace and path.startswith(SITE + '/releases/'):
            raise ValueError('immutable_second_round_release')
        return super().put(path, raw, replace=replace)

    def directory(self, path):
        self.allowed(path + '/')
        actual = self.metadata(path + '/')
        if actual is not None:
            if actual['type'] != 'dir': raise RuntimeError('not_directory')
            return
        if path.rstrip('/') == '/public_html/data':
            raise RuntimeError('missing_shared_data_parent')
        parent = str(PurePosixPath(path).parent)
        if parent not in {'/', '/public_html'}: self.directory(parent)
        try:
            # Locaweb drops long absolute MKD commands. CWD components followed
            # by a basename MKD keeps the same guarded absolute destination.
            self.ftp.cwd('/')
            for component in PurePosixPath(parent).parts[1:]: self.ftp.cwd(component)
            self.ftp.mkd(PurePosixPath(path).name)
            self.ftp.cwd('/')
            actual = self.metadata(path + '/')
            if actual is None or actual['type'] != 'dir':
                raise RuntimeError('second_round_directory_creation_unconfirmed')
        except (OSError, EOFError, ftplib.Error):
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
            '--ftp-method', 'multicwd', '--max-time', '45', '--connect-timeout', '15', '--max-filesize', str(wire.MAX_BYTES),
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
            if os.environ.get('LOCAWEB_FTP_PORT', '21') != '21':
                raise ValueError('plain_ftp_port_21_required')
            ftp = wire.PassiveFTP()
            if isinstance(ftp, ftplib.FTP):
                original_transfer = ftp.ntransfercmd
                def transfer(cmd, rest=None):
                    connection, size = original_transfer(cmd, rest)
                    connection.settimeout(45)  # Separate data/control budgets.
                    return connection, size
                ftp.ntransfercmd = transfer
            try:
                ftp.connect(os.environ['LOCAWEB_FTP_HOST'], 21, timeout=15)
                ftp.login(os.environ['LOCAWEB_FTP_USER'], os.environ['LOCAWEB_FTP_PASSWORD'])
                ftp.set_pasv(True)
                if ftp.pwd() != '/': raise RuntimeError('ftp_home_mismatch')
                return ftp
            except BaseException:
                ftp.close()
                raise
        except (OSError, EOFError):
            if attempt == 2: raise
            time.sleep(attempt + 1)


def connect():
    # Small electoral JSONs share one passive control session, as round one does.
    return Transport(ftp_connect(), reconnect=ftp_connect)


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
    return verify_values(values, strict=True)


def marker_for(verified):
    desc = verified['descriptor']
    marker = {'schema_version': 1, 'environment': 'oficial', 'round': 2,
        'generated_at': desc['generated_at'], 'snapshot_id': verified['snapshot_id']}
    if 'portal.json' in desc['files']:
        marker['portal'] = desc['files']['portal.json']
    return canonical(marker)


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
    def __init__(self, transport, state, *, http=http_read, fault=lambda _: None, metrics=None):
        self.t = transport
        self.state = Path(state)
        self.fault = fault
        self.job_path = self.state / 'pending.json'
        self.checkpoint_path = self.state / 'checkpoint.json'
        self.metrics = metrics if metrics is not None else {}
        self.t.metrics, self.t.metrics_lock = self.metrics, threading.Lock()
        self._baseline_cache = None
        self._http_lock, self._http_next = threading.Lock(), 0
        def read_public(relative):
            if http is http_read:
                rate = float(os.environ.get('ELECTION_ROUND2_HTTPS_RPS', '4'))
                if not 0 < rate <= 5: raise ValueError('invalid_round2_https_rate')
                with self._http_lock:
                    delay = self._http_next - time.monotonic()
                    if delay > 0: time.sleep(delay)
                    self._http_next = time.monotonic() + 1 / rate
            try:
                return http(relative)
            except HTTPError as error:
                if error.code == 429:
                    with self._http_lock:
                        self.metrics['public_http_429'] = self.metrics.get('public_http_429', 0) + 1
                raise
        self.http = read_public

    def read_files(self, sid, files):
        def read(transport, pair):
            name, entry = pair
            raw = transport.read(SITE + '/releases/' + sid + '/' + name)
            wire.verify_bytes(raw, entry)
            if self.http('releases/' + sid + '/' + name) != raw:
                raise RuntimeError('second_round_https_hash_mismatch')
            return name, raw
        workers = int(os.environ.get('ELECTION_ROUND2_FTP_WORKERS', '2'))
        if workers not in (1, 2): raise ValueError('invalid_round2_ftp_workers')
        if workers == 1 or not getattr(self.t, 'reconnect', None):
            return dict(read(self.t, pair) for pair in sorted(files.items()))
        from concurrent.futures import ThreadPoolExecutor
        local, sessions = threading.local(), []
        def run(pair):
            if not hasattr(local, 'transport'):
                local.transport = self.t.fork(); sessions.append(local.transport)
            return read(local.transport, pair)
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                return dict(pool.map(run, sorted(files.items())))
        finally:
            for transport in sessions: transport.ftp.close()

    def baseline(self, marker, *, reuse=False):
        # Scoped to one trusted writer operation. Never cache candidate validation
        # across activation or skip the final FTP/HTTPS integrity verification.
        if reuse and self._baseline_cache and self._baseline_cache[0] == marker:
            return self._baseline_cache[1]
        with measure(self.metrics, 'baseline_verification'):
            result = self.release(marker)
        self._baseline_cache = (marker, result)
        return result

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
        desc = parse(self.t.read(transaction_path(sid, 'descriptor.json')))
        validate_descriptor(desc, sid)
        if expected is not None and expected != desc: raise ValueError('remote_descriptor_conflict')
        values = self.read_files(sid, desc['files'])
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
                'publication_phase': verified['publication_phase'] if verified else None,
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
        with measure(self.metrics, 'https_post_activation_verification'):
            self.release(bytes.fromhex(job['marker']), expected=job['descriptor'])
        if self.marker() != bytes.fromhex(job['marker']):
            raise RuntimeError('second_round_selection_changed')
        receipt = {'status': 'published', 'round': 2, 'snapshot_id': job['snapshot_id'],
                   'verified_at': now(), 'activation': 'ftp_marker_rename', 'multinode_guarantee': False,
                   'transaction_owner': job['owner']}
        receipt_path = self.state / 'receipts' / (job['snapshot_id'] + '.json')
        previous_receipt = load(receipt_path)
        if previous_receipt:
            if previous_receipt.get('transaction_owner') == job['owner']:
                receipt = previous_receipt  # Crash recovery never fabricates a newer publication time.
            else:
                save(self.state / 'receipt-history' / (digest(canonical(previous_receipt)) + '.json'), previous_receipt)
        save(receipt_path, receipt)
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
        journal_path = self.state / 'journals' / (job['snapshot_id'] + '.json')
        previous_job = load(journal_path)
        if previous_job and previous_job.get('owner') != job['owner']:
            journal_path = journal_path.with_name(job['snapshot_id'] + '.' + job['owner'][:24] + '.json')
        save(journal_path, job)
        save(self.job_path, None)
        return {key: value for key, value in receipt.items() if key != 'transaction_owner'}

    def recover(self, *, reuse_baseline=False):
        job = load(self.job_path)
        if not job:
            if self.t.metadata(PRIVATE + '/lock/') is not None:
                raise RuntimeError('orphan_lock_without_trusted_journal')
            return self.reconcile(reuse_baseline=reuse_baseline)
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
        if old:
            self.baseline(old, reuse=reuse_baseline)
            self.t.put(job.get('before_backup', transaction_path(job['snapshot_id'], 'before-marker.json')), old)
        package = Path(job['package'])
        values = tree(package)
        verified = describe(values)
        if verified['descriptor'] != job['descriptor']: raise ValueError('local_pending_package_changed')
        # Only temporary names belonging to this persisted transaction are known.
        with measure(self.metrics, 'ftp_upload_and_verification'):
            self.prepare_files(job, values)
        self.t.put(transaction_path(job['snapshot_id'], 'descriptor.json'), canonical(job['descriptor']))
        with measure(self.metrics, 'https_pre_activation_verification'):
            self.release(new, expected=job['descriptor'])
        job['phase'] = 'verified'
        save(self.job_path, job)
        self.fault('before_activation')
        if self.marker() != old: raise RuntimeError('external_second_round_marker')
        # A marker temporary left by a crash is reconciled, never blindly replayed.
        with measure(self.metrics, 'activation'):
            temporary = self.t.read(SITE + '/version.json.upload', optional=True)
            if temporary is not None:
                if temporary != new: raise RuntimeError('unknown_marker_temporary')
                self.t.ftp.rename(SITE + '/version.json.upload', SITE + '/version.json')
            else:
                self.t.put(SITE + '/version.json', new, replace=True)
        self.fault('after_activation')
        return self.finish(job)

    def prepare_files(self, job, values):
        """Disjoint immutable files only; activation remains serialized."""
        def upload(transport, name, raw):
            path = SITE + '/releases/' + job['snapshot_id'] + '/' + name
            existing = transport.read(path, optional=True)
            if existing is not None:
                if existing != raw: raise ValueError('immutable_second_round_collision')
                return
            temporary = transport.read(path + '.upload', optional=True)
            if temporary is not None:
                if temporary == raw:
                    transport.ftp.rename(path + '.upload', path)
                else:
                    transport.ftp.delete(path + '.upload')
            if transport.read(path, optional=True) is None: transport.put(path, raw)
        workers = int(os.environ.get('ELECTION_ROUND2_FTP_WORKERS', '2'))
        if workers not in (1, 2): raise ValueError('invalid_round2_ftp_workers')
        if workers == 1 or not getattr(self.t, 'reconnect', None):
            for name, raw in sorted(values.items()):
                upload(self.t, name, raw)
                self.fault('after_file')
            return
        from concurrent.futures import ThreadPoolExecutor
        import threading
        sessions, local = [], threading.local()
        def run(pair):
            if not hasattr(local, 'transport'):
                local.transport = self.t.fork()
                sessions.append(local.transport)
            upload(local.transport, *pair)
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                # Context manager waits for all workers even after a failure.
                # No marker/receipt/checkpoint is touched by a worker.
                for _ in pool.map(run, sorted(values.items())): self.fault('after_file')
        finally:
            for transport in sessions: transport.ftp.close()

    def reconcile(self, *, reuse_baseline=False):
        if load(self.job_path): return self.recover()
        if self.t.metadata(PRIVATE + '/lock/') is not None:
            raise RuntimeError('orphan_lock_without_trusted_journal')
        marker = self.marker()
        checkpoint = load(self.checkpoint_path)
        if not marker:
            if checkpoint: raise RuntimeError('remote_second_round_marker_missing')
            return {'status': 'awaiting_official_round_two_data'}
        verified = self.baseline(marker, reuse=reuse_baseline)[1]
        if checkpoint and checkpoint['snapshot_id'] != verified['snapshot_id']:
            # Adopt only a transaction previously verified by this trusted host.
            receipt = load(self.state / 'receipts' / (verified['snapshot_id'] + '.json'))
            if not receipt: raise RuntimeError('unrecognized_second_round_marker')
            save(self.checkpoint_path, receipt)
        elif not checkpoint:
            raise RuntimeError('remote_release_without_local_receipt')
        return {'status': 'verified', 'snapshot_id': verified['snapshot_id']}

    def publish(self, directory=None, *, values=None, baseline_checked=False):
        self.reconcile(reuse_baseline=baseline_checked)
        values = tree(Path(directory)) if values is None else values
        verified = describe(values)
        before = self.marker()
        if before:
            prior, _ = self.baseline(before, reuse=True)
            # Different fetch times alone never create a new public release.
            if verified['snapshot_id'] == parse(before)['snapshot_id']:
                return {'status': 'unchanged', 'snapshot_id': verified['snapshot_id']}
            before_names, after_names = set(prior) - META - {'portal.json'}, set(values) - META - {'portal.json'}
            if not before_names <= after_names: raise ValueError('second_round_inventory_regression')
            for name in before_names:
                old, new = parse(prior[name]), parse(values[name])
                if old['snapshot']['sections']['totalized'] > 0 and new['snapshot']['sections']['totalized'] == 0:
                    raise ValueError('second_round_counting_regression')
                if {str(c['tse_candidate_seq']) for c in old['candidates']} != {str(c['tse_candidate_seq']) for c in new['candidates']}:
                    raise ValueError('second_round_roster_change_requires_review')
                transition(name, old, new)
        checkpoint = load(self.checkpoint_path)
        if checkpoint and (not before or checkpoint['snapshot_id'] != parse(before)['snapshot_id']):
            raise RuntimeError('second_round_checkpoint_mismatch')
        import secrets
        if directory is None: raise ValueError('changed_round2_package_required')
        job = {'schema': 1, 'snapshot_id': verified['snapshot_id'], 'owner': secrets.token_hex(32),
            'phase': 'prepared', 'package': str(Path(directory).resolve()), 'descriptor': verified['descriptor'],
            'before': before.hex() if before else None, 'marker': marker_for(verified).hex(), 'created_at': now()}
        # A release may be safely selected again without overwriting the first
        # activation's backup. Descriptors remain addressed by the full release ID.
        job['before_backup'] = transaction_path(job['owner'], 'before-marker.json')
        # Persist intended work before acquiring the remote lock.
        save(self.job_path, job)
        self.fault('after_journal')
        self.remote_lock(job)
        self.fault('after_lock')
        return self.recover(reuse_baseline=True)
