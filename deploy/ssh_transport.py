"""Explicit SSH/rsync transport beneath existing publication state machines.

Policy classes retain their namespaces, financial validation and recovery.
SSH's stdio RPC handles metadata/activation; rsync uploads only fresh private
staging objects. There is no automatic FTP fallback or write replay.
"""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import select
import shlex
import stat
import subprocess
import tempfile
import threading
import time

from . import ssh_remote

HOST_FINGERPRINT = 'SHA256:bahZf80pWXz9IHeBZcj5bspwnZnLfDFAaKJR7Vd+qM8'


def verify_known_hosts(path):
    result = subprocess.run(['ssh-keygen', '-F', 'ftp.afgnet.com.br', '-f', str(path)],
                            capture_output=True, timeout=10)
    matching = []
    for line in result.stdout.decode('ascii').splitlines():
        if line.startswith('#'): continue
        fields = line.split()
        if len(fields) == 3 and fields[1] == 'ssh-ed25519':
            raw = base64.b64decode(fields[2], validate=True)
            matching.append('SHA256:' + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('='))
    if result.returncode or not matching or any(k != HOST_FINGERPRINT for k in matching):
        raise ValueError('ssh_host_fingerprint_mismatch')


def selection():
    value = os.environ.get('PUBLICATION_TRANSPORT', 'ftp')
    if value not in {'ftp', 'ssh'}: raise ValueError('invalid_publication_transport')
    return value


class SSHError(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.transport_error_code = code


class SSHSession:
    """One authenticated control connection and serialized filesystem RPCs."""
    def __init__(self, scope, *, environment=None):
        env = os.environ if environment is None else environment
        if scope not in ssh_remote.SCOPES: raise ValueError('invalid_ssh_scope')
        self.scope, self.checker = scope, None
        self.metrics = {'transport': 'ssh_rsync', 'connections': 0, 'ssh_failures': 0,
                        'rsync_failures': 0, 'hash_failures': 0, 'files_sent': 0,
                        'files_reused': 0, 'bytes_payload': 0, 'rsync_seconds': 0.0}
        self.guard, self.buffer = threading.RLock(), bytearray()
        credentials = env.get('CREDENTIALS_DIRECTORY')
        self.identity = self._file(env.get('LOCAWEB_SSH_IDENTITY_FILE') or
            (credentials+'/locaweb_ssh_key' if credentials else None), private=True,
            credentials_directory=credentials if not env.get('LOCAWEB_SSH_IDENTITY_FILE') else None)
        self.known_hosts = self._file(env.get('LOCAWEB_SSH_KNOWN_HOSTS_FILE') or
            (credentials+'/locaweb_known_hosts' if credentials else None))
        verify_known_hosts(self.known_hosts)
        self.directory = tempfile.TemporaryDirectory(prefix='election-ssh-')
        self.process = None
        self.options = ['ssh', '-F', '/dev/null', '-p', '22', '-i', str(self.identity),
                        '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
                        '-o', 'StrictHostKeyChecking=yes', '-o', 'HostKeyAlgorithms=ssh-ed25519',
                        '-o', 'UserKnownHostsFile=' + str(self.known_hosts),
                        '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'ConnectTimeout=10',
                        '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
                        '-o', 'ControlMaster=auto', '-o', 'ControlPersist=30',
                        '-o', 'ControlPath=' + self.directory.name + '/control', '-o', 'LogLevel=ERROR']
        self.destination = 'afgnet1@ftp.afgnet.com.br'

    @staticmethod
    def _file(value, private=False, credentials_directory=None):
        if not value or not Path(value).is_absolute() or re.search(r'[\s,:;\x00-\x1f]', value):
            raise ValueError('ssh_configuration_required')
        p = Path(value)
        info = p.lstat()
        # systemd uses a named-user ACL on root-owned read-only credentials.
        # Its ACL mask appears as group-read (0440), despite ordinary service
        # group membership not granting access. Accept only that managed case:
        # exact credential parent, /run/credentials, root ownership, read-only
        # file, protected root-owned directory, and no symlink indirection.
        managed = False
        if (private and credentials_directory and p.parent == Path(credentials_directory)
                and str(p).startswith('/run/credentials/') and p.resolve() == p
                and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o440):
            parent = p.parent.lstat()
            managed = stat.S_ISDIR(parent.st_mode) and parent.st_uid == 0 and not parent.st_mode & 0o027
        if not stat.S_ISREG(info.st_mode) or (info.st_mode & (0o077 if private else 0o022) and not managed):
            raise ValueError('ssh_unsafe_key_permissions' if private else 'ssh_unsafe_known_hosts_permissions')
        return p

    def connect(self):
        if self.process is not None: return
        started = time.monotonic()
        code = Path(ssh_remote.__file__).read_text()
        # Fixed code and validated constants only; all filesystem arguments go
        # through a JSON stdin protocol, never into a remote shell command.
        command = self.options + [self.destination, '/usr/bin/python3 -u -c ' + shlex.quote(code)]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=0)
        self.metrics['connections'] += 1
        try:
            value = self.rpc('hello')
            if value != {'protocol': 1, 'home': ssh_remote.HOME}: raise SSHError('ssh_home_mismatch')
            self.metrics['connect_seconds'] = self.metrics.get('connect_seconds',0) + time.monotonic()-started
        except BaseException:
            self.close()
            raise

    def rpc(self, op, **args):
        with self.guard:
            if self.process is None: self.connect()
            started = time.monotonic()
            request = json.dumps({'scope': self.scope, 'op': op, **args}, separators=(',', ':')).encode() + b'\n'
            try:
                # Requests contain metadata only, never large uploaded files.
                deadline = time.monotonic() + 45
                os.set_blocking(self.process.stdin.fileno(), False)
                offset = 0
                while offset < len(request):
                    remaining = deadline-time.monotonic()
                    if remaining <= 0 or not select.select([], [self.process.stdin], [], max(0,remaining))[1]:
                        raise TimeoutError('ssh_operation_timeout')
                    try: offset += os.write(self.process.stdin.fileno(), request[offset:])
                    except BlockingIOError: continue
                while b'\n' not in self.buffer:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not select.select([self.process.stdout], [], [], max(0, remaining))[0]:
                        raise TimeoutError('ssh_operation_timeout')
                    chunk = os.read(self.process.stdout.fileno(), 65536)
                    if not chunk: raise EOFError('ssh_connection_closed')
                    self.buffer.extend(chunk)
                    if len(self.buffer) > ssh_remote.MAX_BYTES * 2: raise SSHError('ssh_response_too_large')
                line, _, remainder = self.buffer.partition(b'\n')
                self.buffer = bytearray(remainder)
                response = json.loads(line)
                if not response['ok']:
                    if response['code'] in {'ssh_hash_mismatch', 'ssh_final_hash_mismatch'}:
                        self.metrics['hash_failures'] += 1
                    failure = SSHError(response['code'])
                    failure.transport_operation = op
                    failure.remote_errno = response.get('errno')
                    raise failure
                return response['value']
            except (OSError, EOFError, ValueError) as error:
                self.metrics['ssh_failures'] += 1
                self.close()
                # Do not reconnect/replay a mutation with an unknown outcome.
                raise SSHError('ssh_operation_outcome_unknown') from None
            finally:
                self.metrics['rpc_seconds'] = self.metrics.get('rpc_seconds',0) + time.monotonic()-started
                operations = self.metrics.setdefault('operations',{})
                operations[op] = operations.get(op,0)+1

    def checked(self, path):
        name = str(PurePosixPath(path))
        if name != path.rstrip('/') or not path.startswith('/'):
            raise ValueError('ssh_unsafe_path')
        if self.checker: self.checker.allowed(path.rstrip('/') + '/')
        # Apply identical lexical/scope checks locally, without probing local
        # hosting paths. The server repeats them and rejects actual symlinks.
        if '..' in PurePosixPath(path).parts or any(not re.fullmatch('[A-Za-z0-9_.-]+', p) for p in PurePosixPath(path).parts[1:]):
            raise ValueError('ssh_unsafe_path')
        return name

    def metadata(self, path): return self.rpc('metadata', path=self.checked(path))

    def read(self, path, optional=False):
        value = self.rpc('read', path=self.checked(path), optional=optional)
        return base64.b64decode(value, validate=True) if value is not None else None

    def mkd(self, path): return self.rpc('mkdir', path=self.checked(path), exclusive=True)

    def rmd(self, path): return self.rpc('rmdir', path=self.checked(path))

    def delete(self, path): return self.rpc('unlink', path=self.checked(path))

    def rename(self, source, destination):
        source, destination = self.checked(source), self.checked(destination)
        kind = self.metadata(source)
        if kind and kind['type'] == 'dir':
            if (self.scope not in {'first-production', 'first-staging'}
                    or not re.fullmatch(re.escape(self.checker.private) + r'/staging/[a-f0-9]{64}/files', source)
                    or destination != self.checker.site + '/releases/' + source.split('/')[-2]):
                raise ValueError('ssh_invalid_directory_promotion')
        elif self.checker: self.checker.writable(destination)
        immutable = any(p in destination for p in ['/releases/', '/frontend-releases/', '/geography/'])
        return self.rpc('rename', path=source, destination=destination, replace=not immutable)

    def close(self):
        if self.process is not None:
            self.process.stdin.close()
            try: self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try: self.process.wait(timeout=2)
                except subprocess.TimeoutExpired: self.process.kill(); self.process.wait()
            self.process.stdout.close()
            self.process = None
        self.buffer.clear()
        if Path(self.directory.name, 'control').exists():
            try:
                subprocess.run(self.options + ['-O', 'exit', self.destination], capture_output=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired): pass

    def shutdown(self):
        self.close()
        self.directory.cleanup()

    def upload(self, raw):
        limit = 64*1024*1024 if self.scope.startswith('archive-') else ssh_remote.MAX_BYTES
        if not 0 < len(raw) <= limit: raise ValueError('ssh_invalid_upload_size')
        cached = self.rpc('cached', sha256=ssh_remote.sha(raw))
        if cached:
            self.metrics['files_reused'] += 1
            return cached
        stage = self.rpc('reserve', nonce=secrets.token_hex(16))
        with tempfile.NamedTemporaryFile(dir=self.directory.name) as stream:
            stream.write(raw); stream.flush()
            command = ['rsync', '--protect-args', '--checksum', '--itemize-changes',
                       '--stats', '--timeout=30', '--chmod=F600', '-e', shlex.join(self.options),
                       stream.name, self.destination + ':' + ssh_remote.HOME + stage]
            start = time.monotonic()
            try: result = subprocess.run(command, capture_output=True, timeout=60)
            except subprocess.TimeoutExpired:
                self.metrics['rsync_failures'] += 1
                raise SSHError('rsync_transfer_timeout') from None
            self.metrics['rsync_seconds'] += time.monotonic() - start
            if result.returncode:
                self.metrics['rsync_failures'] += 1
                raise SSHError('rsync_transfer_failed')
            stats = result.stdout.decode('ascii', errors='ignore')
            for label, key in [('Total bytes sent', 'bytes_sent'), ('Total bytes received', 'bytes_received')]:
                match = re.search(re.escape(label) + r': ([0-9,]+)', stats)
                if match: self.metrics[key] = self.metrics.get(key, 0) + int(match[1].replace(',', ''))
        self.metrics['files_sent'] += 1
        self.metrics['bytes_payload'] += len(raw)
        if self.rpc('hash', path=stage) != ssh_remote.sha(raw):
            self.metrics['hash_failures'] += 1
            raise SSHError('ssh_hash_mismatch')
        return self.rpc('cache', path=stage, sha256=ssh_remote.sha(raw))

    def upload_many(self, values):
        unique = {ssh_remote.sha(raw):raw for raw in values}
        nonce = secrets.token_hex(16)
        entries = {key:len(raw) for key,raw in unique.items()}
        prepared = self.rpc('reserve_batch', entries=entries, nonce=nonce)
        missing = prepared['missing']
        self.metrics['files_reused'] += len(unique) - len(missing)
        if missing:
            with tempfile.TemporaryDirectory(dir=self.directory.name) as folder:
                for key in missing: Path(folder, key).write_bytes(unique[key])
                command = ['rsync', '--recursive', '--protect-args', '--checksum', '--itemize-changes',
                           '--stats', '--timeout=30', '--chmod=D700,F600', '-e', shlex.join(self.options),
                           folder+'/', self.destination+':'+ssh_remote.HOME+prepared['directory']+'/']
                start = time.monotonic()
                try: result = subprocess.run(command, capture_output=True, timeout=90)
                except subprocess.TimeoutExpired:
                    self.metrics['rsync_failures'] += 1
                    raise SSHError('rsync_transfer_timeout') from None
                self.metrics['rsync_seconds'] += time.monotonic()-start
                if result.returncode:
                    self.metrics['rsync_failures'] += 1
                    raise SSHError('rsync_transfer_failed')
                for label,key in [('Total bytes sent','bytes_sent'),('Total bytes received','bytes_received')]:
                    match = re.search(re.escape(label)+r': ([0-9,]+)',result.stdout.decode('ascii',errors='ignore'))
                    if match:self.metrics[key]=self.metrics.get(key,0)+int(match[1].replace(',',''))
                self.metrics['files_sent'] += len(missing)
                self.metrics['bytes_payload'] += sum(entries[key] for key in missing)
        return self.rpc('cache_batch', entries=entries, nonce=nonce)


class SSHOperations:
    """Mix in I/O only; keep the caller's namespace and transaction policy."""
    def metadata(self, path):
        self.allowed(path.rstrip('/') + '/')
        return self.ftp.metadata(path)

    def writable(self, path):
        result = super().writable(path)
        scope = self.ftp.scope
        if scope in {'portal','raio-x'}:
            public = ssh_remote.SCOPES[scope][0]
            if not (path.startswith(public+'/') or path.startswith('/frontend-deploy/'+scope+'/')):
                raise ValueError('ssh_other_frontend_protected')
            # The portal root contains Goiás; the ordinary frontend policy also
            # understands Goiás. Pin this particular SSH writer to its component.
            if scope == 'portal' and path.startswith(public+'/goias/'):
                raise ValueError('ssh_other_frontend_protected')
        return result

    def read(self, path, *, optional=False): return self.ftp.read(self.allowed(path), optional)

    def directory(self, path):
        self.allowed(path + '/')
        known = getattr(self, '_ssh_directories', set())
        if path in known: return
        meta = self.metadata(path)
        if meta:
            if meta['type'] != 'dir': raise ValueError('ssh_not_directory')
            known.add(path); self._ssh_directories = known
            return
        parent = str(PurePosixPath(path).parent)
        if parent not in {'/', '/public_html', '/public_html/eleicoes', '/public_html/eleicoes/goias', '/public_html/eleicoes/goias/raio-x'}:
            self.directory(parent)
        self.ftp.rpc('mkdir', path=path)
        known.add(path); self._ssh_directories = known

    def put(self, path, raw, *, replace=False):
        self.writable(path)
        if replace and ('/releases/' in path or '/frontend-releases/' in path or '/geography/' in path):
            raise ValueError('ssh_immutable_release')
        old = self.read(path, optional=True)
        if old is not None and not replace:
            if old != raw: raise ValueError('ssh_immutable_collision')
            self.ftp.metrics['files_reused'] += 1
            return
        if old == raw:
            self.ftp.metrics['files_reused'] += 1
            return
        self.directory(str(PurePosixPath(path).parent))
        stage = getattr(self, '_ssh_ready', {}).get(ssh_remote.sha(raw)) or self.ftp.upload(raw)
        self.ftp.rpc('commit', path=path, stage=stage, temporary=path + '.' + secrets.token_hex(16) + '.upload',
                     sha256=ssh_remote.sha(raw), size=len(raw), before=ssh_remote.sha(old) if old is not None else None,
                     replace=replace)
        if self.read(path) != raw: raise SSHError('ssh_final_hash_mismatch')

    def put_many(self, entries):
        pending = {}
        for path,raw in entries.items():
            self.writable(path)
            old = self.read(path, optional=True)
            if old is not None:
                if old != raw: raise ValueError('ssh_immutable_collision')
                self.ftp.metrics['files_reused'] += 1
            else: pending[path] = raw
        if not pending: return
        self._ssh_ready = self.ftp.upload_many(pending.values())
        try:
            for path,raw in pending.items(): self.put(path, raw)
        finally: self._ssh_ready = {}

    def _rename(self, source, destination): return self.ftp.rename(source, destination)

    def promote_release(self, source, destination, files):
        self.allowed(source); self.allowed(destination)
        return self.ftp.rpc('promote', path=source, destination=destination, files=files)

    def fork(self):
        # Serialize one authenticated control connection; application workers
        # remain bounded. Bulk preparation can be added without new writers.
        return None


def transport(policy, scope, *args, environment=None, **kwargs):
    session = SSHSession(scope, environment=environment)
    cls = type('SSH' + policy.__name__, (SSHOperations, policy), {})
    instance = cls(session, *args, reconnect=None, **kwargs)
    session.checker = instance
    session.connect()
    return instance
