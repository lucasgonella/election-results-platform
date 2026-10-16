"""Fixed SSH filesystem protocol. No network listener, shell paths or credentials.

Executed with Python's unbuffered stdio through authenticated SSH. Both sides
validate scope; this is application confinement, not a restricted hosting account.
"""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

HOME = '/home/storage/4/b7/e0/afgnet1'
MAX_BYTES = 16 * 1024 * 1024
SCOPES = {
    'first-production': ['/public_html/data', '/election-static-deploy/production'],
    'first-staging': ['/public_html/__election_static_staging/data', '/election-static-deploy/staging'],
    'second': ['/public_html/data/turnos/2', '/election-round2-deploy'],
    'municipal-1': ['/public_html/municipal-2026/turnos/1', '/public_html/municipal-2026/geography', '/election-municipal-deploy/1'],
    'municipal-2': ['/public_html/municipal-2026/turnos/2', '/public_html/municipal-2026/geography', '/election-municipal-deploy/2'],
    'portal': ['/public_html/eleicoes', '/frontend-deploy'],
    'raio-x': ['/public_html/eleicoes/goias/raio-x', '/frontend-deploy'],
    'finance': ['/public_html/eleicoes/goias/raio-x/data', '/goias-finance-deploy'],
    'benchmark': ['/election-ssh-benchmark'],
    'archive-first': ['/backup/election-results-platform/ftp-cycles'],
    'archive-second': ['/backup/election-results-platform/round2-cycles'],
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def path_for(name, scope, root=HOME, *, ancestor=False):
    if (scope not in SCOPES or not isinstance(name, str) or not name.startswith('/')
            or str(PurePosixPath(name)) != name or any(
                not re.fullmatch('[A-Za-z0-9_.-]+', part) or part in {'.', '..'}
                for part in PurePosixPath(name).parts[1:])):
        raise ValueError('ssh_unsafe_path')
    roots = SCOPES[scope] + ['/election-ssh-staging/' + scope]
    if scope == 'first-production' and (name == '/public_html/data/turnos' or name.startswith('/public_html/data/turnos/')):
        raise ValueError('ssh_other_round_protected')
    if scope in {'portal','raio-x'}:
        public = SCOPES[scope][0]
        relative = name[len(public)+1:] if name.startswith(public+'/') else name
        if name.startswith(public+'/') and ('data' in PurePosixPath(relative).parts
                or scope == 'portal' and relative.split('/')[0] == 'goias'):
            raise ValueError('ssh_frontend_data_protected')
    allowed = any(name == p or name.startswith(p + '/') for p in roots)
    parents = {str(parent) for p in roots for parent in PurePosixPath(p).parents}
    if not allowed and not (ancestor and name in parents):
        raise ValueError('ssh_outside_scope')
    # Reject every existing symlink component, including ancestors of the
    # hosting home. No traversal through public symlinks is permitted.
    path = Path(root + name)
    for part in reversed([path, *path.parents]):
        try: mode = part.lstat().st_mode
        except FileNotFoundError: continue
        if stat.S_ISLNK(mode): raise ValueError('ssh_symlink_rejected')
        if part != path and not stat.S_ISDIR(mode): raise ValueError('ssh_parent_not_directory')
    return path


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def metadata(path):
    try: value = path.lstat()
    except FileNotFoundError: return None
    if stat.S_ISREG(value.st_mode): return {'type': 'file', 'size': str(value.st_size)}
    if stat.S_ISDIR(value.st_mode): return {'type': 'dir'}
    raise ValueError('ssh_nonregular_file')


def read(path, limit=MAX_BYTES):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode): raise ValueError('ssh_nonregular_file')
        raw = stream.read(limit + 1)
    if len(raw) > limit: raise ValueError('ssh_oversized_file')
    return raw


def rename_exclusive(source, destination):
    # NFS on this hosting rejects RENAME_NOREPLACE (EINVAL). Link creation is
    # exclusive for regular files and never replaces an existing destination.
    # Directory promotion has its own resumable, inventory-verified protocol.
    if not stat.S_ISREG(source.lstat().st_mode): raise ValueError('ssh_exclusive_regular_file_required')
    os.link(source, destination, follow_symlinks=False)
    sync_dir(destination.parent)
    source.unlink()
    if source.parent != destination.parent: sync_dir(source.parent)


def promote(request, root):
    scope, source, destination = request['scope'], request['path'], request['destination']
    if scope not in {'first-production', 'first-staging'}: raise ValueError('ssh_invalid_promotion_scope')
    match = re.fullmatch(re.escape(SCOPES[scope][1]) + r'/staging/([a-f0-9]{64})/files', source)
    if not match or destination != SCOPES[scope][0] + '/releases/' + match[1]:
        raise ValueError('ssh_invalid_directory_promotion')
    src, dst = path_for(source, scope, root), path_for(destination, scope, root)
    files = request['files']
    if not isinstance(files, dict) or len(files) != 140: raise ValueError('ssh_invalid_promotion_inventory')
    for name, entry in files.items():
        path_for(source + '/' + name, scope, root)
        if (type(entry.get('size')) is not int or not 0 < entry['size'] <= MAX_BYTES
                or not re.fullmatch('[a-f0-9]{64}', entry.get('sha256', ''))):
            raise ValueError('ssh_invalid_promotion_inventory')
    # The application's prepared journal already owns this immutable inventory.
    # A transport receipt additionally proves ownership of an unselected partial
    # destination. Unknown existing directories are never adopted or overwritten.
    receipt_name = '/election-ssh-staging/' + scope + '/promotions/' + match[1] + '.json'
    receipt = path_for(receipt_name, scope, root)
    intent = {'source':source, 'destination':destination, 'files':files}
    if receipt.exists():
        old = json.loads(read(receipt))
        if old != intent or not dst.is_dir(): raise ValueError('ssh_promotion_receipt_mismatch')
    else:
        if dst.exists(): raise ValueError('ssh_immutable_collision')
        receipt.parent.mkdir(mode=0o700, exist_ok=True)
        dst.mkdir(mode=0o755)  # Exclusive: never rename over another directory.
        dst.chmod(0o755)
        sync_dir(dst.parent)
        fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(intent, stream, separators=(',', ':')); stream.flush(); os.fsync(stream.fileno())
        sync_dir(receipt.parent)
    for base, names in [(src, files), (dst, files)]:
        for item in base.rglob('*'):
            path_for('/' + str(item.relative_to(root)), scope, root)
            if item.is_file() and item.relative_to(base).as_posix() not in names:
                raise ValueError('ssh_unexpected_promotion_file')
    for name, entry in files.items():
        origin = path_for(source+'/'+name, scope, root)
        final = path_for(destination+'/'+name, scope, root)
        if not final.exists():
            raw = read(origin)
            if sha(raw) != entry['sha256'] or len(raw) != entry['size']: raise ValueError('ssh_hash_mismatch')
            if not final.parent.exists():
                final.parent.mkdir(parents=True)
                final.parent.chmod(0o755)
            os.link(origin, final, follow_symlinks=False)
            sync_dir(final.parent)
        final.chmod(0o644)  # Private staged files started 0600; web must read them.
        raw = read(final)
        if sha(raw) != entry['sha256'] or len(raw) != entry['size']: raise ValueError('ssh_hash_mismatch')
    # Source cleanup removes only this verified, private staging inventory. A
    # partial response leaves the receipt and can resume without reuploading.
    for item in sorted(src.rglob('*'), key=lambda p:len(p.parts), reverse=True):
        if item.is_dir(): item.rmdir()
        else: item.unlink()
    src.rmdir(); sync_dir(src.parent)
    return None


def handle(request, root=HOME):
    scope, op = request['scope'], request['op']
    file_limit = 64*1024*1024 if scope.startswith('archive-') else MAX_BYTES
    read_file = lambda path: read(path, file_limit)
    name = request.get('path')
    if (scope in {'portal','raio-x'} and op not in {'metadata','read','hash','hello'} and name
            and name.startswith('/frontend-deploy/') and not name.startswith('/frontend-deploy/'+scope+'/')
            and name != '/frontend-deploy/'+scope):
        raise ValueError('ssh_other_frontend_protected')
    p = path_for(name, scope, root, ancestor=op in {'metadata', 'mkdir'}) if name else None
    if op == 'hello':
        if str(Path(root).resolve()) != root: raise ValueError('ssh_home_mismatch')
        return {'protocol': 1, 'home': root}
    if op == 'promote': return promote(request, root)
    if op == 'metadata': return metadata(p)
    if op == 'chunk':
        if not scope.startswith('archive-'): raise ValueError('ssh_chunk_scope_required')
        offset = request['offset']
        if type(offset) is not int or not 0 <= offset <= file_limit: raise ValueError('ssh_invalid_offset')
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > file_limit: raise ValueError('ssh_invalid_archive')
            stream.seek(offset)
            raw = stream.read(65536)
        return base64.b64encode(raw).decode('ascii')
    if op == 'read':
        if not p.exists() and request.get('optional'): return None
        return base64.b64encode(read_file(p)).decode('ascii')
    if op == 'mkdir':
        # Ancestors may only be created as ordinary directories, never locks.
        mode = 0o755 if name.startswith('/public_html') else 0o700
        try: p.mkdir(mode=mode)
        except FileExistsError:
            if request.get('exclusive', False): raise
        else: p.chmod(mode)
        if metadata(p)['type'] != 'dir': raise ValueError('ssh_not_directory')
        sync_dir(p.parent)
        return None
    if op == 'reserve':
        nonce = request['nonce']
        if not re.fullmatch('[a-f0-9]{32}', nonce): raise ValueError('ssh_invalid_nonce')
        base = '/election-ssh-staging/' + scope
        for n in ['/election-ssh-staging', base]:
            q = path_for(n, scope, root, ancestor=True)
            q.mkdir(mode=0o700, exist_ok=True)
        q = path_for(base + '/' + nonce, scope, root)
        q.mkdir(mode=0o700)  # Exclusive ownership, never adopt someone else's temp.
        sync_dir(q.parent)
        return base + '/' + nonce + '/payload'
    if op == 'hash': return sha(read_file(p))
    if op in {'reserve_batch', 'cache_batch'}:
        entries, nonce = request['entries'], request['nonce']
        if (not isinstance(entries, dict) or not 1 <= len(entries) <= 150
                or not re.fullmatch('[a-f0-9]{32}', nonce)
                or sum(entries.values()) > 64*1024*1024): raise ValueError('ssh_invalid_batch')
        for key, size in entries.items():
            if not re.fullmatch('[a-f0-9]{64}', key) or type(size) is not int or not 0 < size <= MAX_BYTES:
                raise ValueError('ssh_invalid_batch')
        prefix = '/election-ssh-staging/' + scope
        for name in ['/election-ssh-staging', prefix, prefix+'/objects']:
            path_for(name, scope, root, ancestor=True).mkdir(mode=0o700, exist_ok=True)
        batch = prefix+'/'+nonce
        if op == 'reserve_batch':
            path_for(batch, scope, root).mkdir(mode=0o700)
            path_for(batch+'/files', scope, root).mkdir(mode=0o700)
            missing = []
            for key in entries:
                obj = path_for(prefix+'/objects/'+key, scope, root)
                if obj.exists():
                    if sha(read_file(obj)) != key: raise ValueError('ssh_hash_mismatch')
                else: missing.append(key)
            return {'missing':missing, 'directory':batch+'/files'}
        directory = path_for(batch+'/files', scope, root)
        for item in directory.iterdir():
            path_for(batch+'/files/'+item.name, scope, root)
            if item.name not in entries or not item.is_file(): raise ValueError('ssh_unexpected_batch_file')
        for key, size in entries.items():
            obj = path_for(prefix+'/objects/'+key, scope, root)
            if not obj.exists():
                staged = path_for(batch+'/files/'+key, scope, root)
                raw = read_file(staged)
                if len(raw) != size or sha(raw) != key: raise ValueError('ssh_hash_mismatch')
                rename_exclusive(staged, obj)
            raw = read_file(obj)
            if len(raw) != size or sha(raw) != key: raise ValueError('ssh_hash_mismatch')
        return {key:prefix+'/objects/'+key for key in entries}
    if op == 'cached':
        key = request['sha256']
        if not re.fullmatch('[a-f0-9]{64}', key): raise ValueError('ssh_invalid_hash')
        name = '/election-ssh-staging/' + scope + '/objects/' + key
        obj = path_for(name, scope, root)
        if not obj.exists(): return None
        if sha(read_file(obj)) != key: raise ValueError('ssh_hash_mismatch')
        return name
    if op == 'cache':
        key = request['sha256']
        if not re.fullmatch('[a-f0-9]{64}', key): raise ValueError('ssh_invalid_hash')
        if not re.fullmatch('/election-ssh-staging/' + scope + '/[a-f0-9]{32}/payload', name):
            raise ValueError('ssh_not_owned_stage')
        if sha(read_file(p)) != key: raise ValueError('ssh_hash_mismatch')
        directory = path_for('/election-ssh-staging/' + scope + '/objects', scope, root)
        directory.mkdir(mode=0o700, exist_ok=True)
        obj = path_for('/election-ssh-staging/' + scope + '/objects/' + key, scope, root)
        if obj.exists():
            if sha(read_file(obj)) != key: raise ValueError('ssh_hash_mismatch')
        else: rename_exclusive(p, obj)
        return '/election-ssh-staging/' + scope + '/objects/' + key
    if op == 'commit':
        stage = path_for(request['stage'], scope, root)
        if not request['stage'].startswith('/election-ssh-staging/' + scope + '/'):
            raise ValueError('ssh_not_private_stage')
        raw = read_file(stage)
        if sha(raw) != request['sha256'] or len(raw) != request['size']:
            raise ValueError('ssh_hash_mismatch')
        previous = sha(read_file(p)) if p.exists() else None
        if previous != request['before']: raise ValueError('ssh_external_writer')
        if previous is not None and not request['replace']: raise ValueError('ssh_immutable_collision')
        temporary = path_for(request['temporary'], scope, root)
        if temporary.parent != p.parent or not temporary.name.endswith('.upload'):
            raise ValueError('ssh_invalid_temporary')
        mode = 0o644 if name.startswith('/public_html/') else 0o600
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        if sha(read_file(temporary)) != request['sha256']: raise ValueError('ssh_copy_hash_mismatch')
        if (sha(read_file(p)) if p.exists() else None) != previous: raise ValueError('ssh_external_writer')
        if request['replace']:
            os.replace(temporary, p)
            sync_dir(p.parent)
        else:
            rename_exclusive(temporary, p)
        if sha(read_file(p)) != request['sha256']: raise ValueError('ssh_final_hash_mismatch')
        # Retain immutable private hash objects for verified reuse. Application
        # journals remain authoritative; transport caching never selects data.
        return None
    if op == 'rename':
        dest = path_for(request['destination'], scope, root)
        if metadata(p)['type'] == 'dir':
            rename_exclusive(p, dest)
        else:
            if not name.endswith('.upload'): raise ValueError('ssh_not_owned_temporary')
            if p.parent != dest.parent: raise ValueError('ssh_cross_directory_temporary')
            if request.get('replace'): os.replace(p, dest); sync_dir(dest.parent)
            else: rename_exclusive(p, dest)
        return None
    if op == 'unlink':
        if not (name.endswith('.upload') or name.endswith('/lock/owner.json')):
            raise ValueError('ssh_delete_protected')
        p.unlink(); sync_dir(p.parent)
        return None
    if op == 'rmdir':
        if not name.endswith('/lock'): raise ValueError('ssh_rmdir_protected')
        p.rmdir(); sync_dir(p.parent)
        return None
    raise ValueError('ssh_unknown_operation')


def serve():
    for line in sys.stdin.buffer:
        try:
            if len(line) > MAX_BYTES * 2: raise ValueError('ssh_oversized_request')
            result = {'ok': True, 'value': handle(json.loads(line))}
        except Exception as error:
            # Only fixed codes/types/errno; never server replies, file bytes,
            # user names, environment or document identifiers.
            code = str(error) if type(error) in {ValueError, RuntimeError} and re.fullmatch('[a-z_]{1,80}', str(error)) else 'ssh_remote_operation_failed'
            result = {'ok': False, 'code': code, 'type': type(error).__name__, 'errno': getattr(error, 'errno', None)}
        sys.stdout.write(json.dumps(result, separators=(',', ':')) + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    serve()
