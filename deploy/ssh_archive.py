"""Private archive adapter retaining full download verification before deletion."""
import base64
import hashlib
from pathlib import PurePosixPath
import re
import secrets

from . import frontend as wire
from .ssh_transport import transport


class Policy(wire.Transport):
    def __init__(self, client, destination, **kwargs):
        super().__init__(client, **kwargs)
        if destination not in {'/backup/election-results-platform/ftp-cycles','/backup/election-results-platform/round2-cycles'}:
            raise ValueError('unsafe_private_backup_destination')
        self.destination = destination

    def allowed(self, path):
        base = path.rstrip('/')
        if '..' in PurePosixPath(path).parts or any(c in path for c in ('\\','\n','\r')):
            raise ValueError('unsafe_archive_path')
        if base == self.destination or path.startswith(self.destination+'/') or base in {str(p) for p in PurePosixPath(self.destination).parents if str(p) != '/'}:
            return path
        raise ValueError('outside_archive_namespace')

    def writable(self, path):
        self.allowed(path)
        name = path.removeprefix(self.destination+'/')
        if not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*\.(tar\.gz|json)', name):
            raise ValueError('unsafe_archive_name')
        return path


class ArchiveSSH:
    def __init__(self, *, destination):
        scope = 'archive-first' if destination.endswith('/ftp-cycles') else 'archive-second'
        self.t = transport(Policy, scope, destination)
        self.destination = destination
        self.t.directory(destination)

    def verified(self, name, size, sha256):
        path = self.destination+'/'+name
        self.t.writable(path)
        self.phase = 'size'
        meta = self.t.metadata(path)
        if meta is None: return False
        if meta['type'] != 'file' or int(meta['size']) != size: raise ValueError('backup_size_mismatch')
        self.phase = 'download_verification'
        digest, offset = hashlib.sha256(), 0
        while offset < size:
            raw = base64.b64decode(self.t.ftp.rpc('chunk', path=path, offset=offset), validate=True)
            if not raw or offset+len(raw) > size: raise ValueError('backup_size_mismatch')
            digest.update(raw); offset += len(raw)
        if digest.hexdigest() != sha256: raise ValueError('backup_hash_mismatch')
        return True

    def upload(self, name, stream, size, sha256):
        if not 0 < size <= 64*1024*1024: raise ValueError('backup_file_too_large')
        if self.verified(name,size,sha256): return
        raw = stream.read(size+1)
        if len(raw) != size or wire.digest(raw) != sha256: raise ValueError('backup_source_mismatch')
        self.phase = 'upload'
        stage = self.t.ftp.upload(raw)
        path = self.destination+'/'+name
        self.t.ftp.rpc('commit', path=path, stage=stage, temporary=path+'.'+secrets.token_hex(16)+'.upload',
                       sha256=sha256, size=size, before=None, replace=False)
        if not self.verified(name,size,sha256): raise ValueError('backup_missing_after_rename')

    def close(self): self.t.ftp.close()
