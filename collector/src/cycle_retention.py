"""Conservative, backup-first retention for the static election writer.

Only collection-only cycles are eligible. Generations, packages, approvals,
reconciliation evidence and anything referenced by control JSON stay local.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import ftplib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time

from deploy.frontend import connect, error_report
from .election_release import META, STATE, canonical, digest, parse, targets

BACKUP = '/backup/election-results-platform/ftp-cycles'
CYCLE = re.compile(r'\d{8}T\d{6}-[a-f0-9]{8}')
MANIFEST_LOCK = threading.Lock()


def instant():
    return datetime.now(timezone.utc).isoformat()


def references(root):
    """Read all control records, including historical/recovery/approval files.

    A malformed record blocks retention. References need not be in a specific
    field: nested records and relative cycle IDs are also protected.
    """
    found = set()
    def visit(value):
        if isinstance(value, str):
            found.update(CYCLE.findall(value))
        elif isinstance(value, dict):
            for key, child in value.items():
                visit(key); visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in {
            'cycles', 'generations', 'bootstrap-legacy', '.archive-tmp'}]
        for name in files:
            if name.endswith('.json'):
                path = Path(base)/name
                if path.is_symlink():
                    raise ValueError('symlink_control_record')
                visit(parse(path.read_bytes()))
    return found


def inventory(cycle, *, content=True):
    """Allow only known collector output; never archive arbitrary secret files."""
    result = {}
    for path in sorted(cycle.rglob('*')):
        if path.is_symlink():
            raise ValueError('symlink_cycle')
        if path.is_dir():
            continue
        name = path.relative_to(cycle).as_posix()
        allowed = name in {'review-required.json', 'collection-complete.json'}
        for directory, names in (('collection/state/', STATE),
                                 ('collection/pending/', STATE),
                                 ('collection/stage/', set(targets()) | META)):
            if name.startswith(directory) and name.removeprefix(directory) in names:
                allowed = True
        if not allowed or not path.is_file():
            raise ValueError('unknown_cycle_file')
        if content:
            raw = path.read_bytes()
            result[name] = {'size': len(raw), 'sha256': digest(raw)}
        else:
            result[name] = {'size': path.stat().st_size}
    return result


def plan(root, *, min_age_hours=24, now=None):
    root = Path(root)
    if root.is_symlink() or (root/'cycles').is_symlink():
        raise ValueError('unsafe_retention_root')
    protected = references(root)
    cycles = sorted((root/'cycles').iterdir()) if (root/'cycles').exists() else []
    # Preserve the latest witness of every distinct source/reason per target.
    # captured_at/proposed_sha256 are intentionally excluded: clock changes do
    # not constitute new election evidence. All older witnesses are backed up.
    witnesses = {}
    for cycle in cycles:
        if cycle.is_symlink() or not cycle.is_dir() or not CYCLE.fullmatch(cycle.name):
            protected.add(cycle.name)
            continue
        review = cycle/'review-required.json'
        if review.exists():
            data = parse(review.read_bytes())
            for name, entry in data.items():
                fingerprint = entry.get('source_sha256')
                if not fingerprint:
                    protected.add(cycle.name)
                else:
                    witnesses[(name, entry.get('reason'), fingerprint)] = cycle.name
    protected.update(witnesses.values())
    cutoff = (time.time() if now is None else now) - min_age_hours*3600
    eligible = []
    reasons = {}
    for cycle in cycles:
        reason = None
        if cycle.name in protected:
            reason = 'referenced_or_unique_review'
        elif (cycle/'package').exists() or (cycle/'baseline-marker.json').exists():
            reason = 'publication_or_rollback_package'
        elif cycle.stat().st_mtime > cutoff:
            reason = 'recent'
        elif not (cycle/'review-required.json').is_file():
            reason = 'incomplete_or_unknown'
        else:
            if set(p.name for p in cycle.iterdir()) - {
                    'collection', 'review-required.json', 'collection-complete.json'}:
                reason = 'unknown_or_unsafe_files'
            elif not all((cycle/'collection/stage'/name).is_file() for name in META):
                reason = 'incomplete_collection'
        if reason:
            reasons[reason] = reasons.get(reason, 0)+1
        else:
            eligible.append(cycle.name)
    return {'eligible': eligible, 'preserved': reasons, 'total': len(cycles)}


class ArchiveFTP:
    """Dedicated private backup namespace. Plain passive FTP, existing account."""
    def __init__(self, ftp=None, transfer=None):
        self.ftp = ftp or connect()
        self.transfer = transfer or self.ftp_transfer
        self.ftp.timeout = 15
        self.ftp.sock.settimeout(15)
        if self.ftp.pwd() != '/':
            raise ValueError('ftp_home_mismatch')
        # Require the audited account-home mapping; never fall back to public.
        self.ftp.cwd('/public_html'); self.ftp.cwd('/')
        for part in BACKUP.strip('/').split('/'):
            try:
                self.ftp.cwd(part)
            except ftplib.error_perm as error:
                if not str(error).startswith('550'):
                    raise
                self.ftp.mkd(part); self.ftp.cwd(part)
        if self.ftp.pwd().rstrip('/') != BACKUP:
            raise ValueError('backup_directory_mapping_mismatch')
        self.ftp.voidcmd('TYPE I')

    def ftp_transfer(self, name, raw=None):
        if raw is not None:
            self.ftp.storbinary('STOR '+name, io.BytesIO(raw), blocksize=131072)
            return b''
        result=bytearray()
        def receive(chunk):
            result.extend(chunk)
            if len(result)>64*1024**2:
                raise ValueError('backup_file_too_large')
        self.ftp.retrbinary('RETR '+name,receive,blocksize=131072)
        return bytes(result)


    def verified(self, name, size, sha256):
        self.phase = 'size'
        try:
            actual = self.ftp.size(name)
        except ftplib.error_perm as error:
            if str(error).startswith('550'):
                return False
            raise
        if actual != size:
            raise ValueError('backup_size_mismatch')
        h = hashlib.sha256(); received = 0
        def receive(chunk):
            nonlocal received
            received += len(chunk)
            if received > size:
                raise ValueError('backup_size_mismatch')
            h.update(chunk)
        self.phase = 'download_verification'
        receive(self.transfer(name))
        if received != size or h.hexdigest() != sha256:
            raise ValueError('backup_hash_mismatch')
        return True

    def upload(self, name, stream, size, sha256):
        if self.verified(name, size, sha256):
            return
        temporary = name+'.upload'
        self.phase = 'upload'
        self.transfer(temporary, stream.read())
        if not self.verified(temporary, size, sha256):
            raise ValueError('backup_missing_after_upload')
        self.phase = 'rename'
        self.ftp.rename(temporary, name)
        if not self.verified(name, size, sha256):
            raise ValueError('backup_missing_after_rename')

    def close(self):
        self.ftp.close()


def record(root, value):
    with MANIFEST_LOCK, (root/'archive-manifest.jsonl').open('ab') as stream:
        stream.write(canonical(value)+b'\n'); stream.flush(); os.fsync(stream.fileno())


def archive_one(root, name, remote):
    if not CYCLE.fullmatch(name) or name in references(root):
        raise ValueError('cycle_became_referenced')
    cycle = root/'cycles'/name
    if (cycle/'package').exists() or (cycle/'baseline-marker.json').exists():
        raise ValueError('publication_package_preserved')
    files = inventory(cycle)
    before = digest(canonical(files))
    # One archive at a time; bounded local temporary space even for long runs.
    with tempfile.TemporaryDirectory(prefix='cycle-archive-', dir=root) as temporary:
        archive = Path(temporary)/(name+'.tar.gz')
        with archive.open('wb') as output:
            import gzip
            with gzip.GzipFile(filename='', fileobj=output, mode='wb', mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode='w|') as tar:
                    for relative in files:
                        tar.add(cycle/relative, arcname=name+'/'+relative, recursive=False)
        # Check the compressed archive itself against every source file.
        with tarfile.open(archive, 'r:gz') as tar:
            members = tar.getmembers()
            if len(members) != len(files):
                raise ValueError('archive_inventory_mismatch')
            for member in members:
                relative = member.name.removeprefix(name+'/')
                if not member.isfile() or relative not in files:
                    raise ValueError('archive_inventory_mismatch')
                raw = tar.extractfile(member).read()
                if {'size':len(raw), 'sha256':digest(raw)} != files[relative]:
                    raise ValueError('archive_content_mismatch')
        size = archive.stat().st_size
        sha256 = digest(archive.read_bytes())
        with archive.open('rb') as stream:
            remote.upload(archive.name, stream, size, sha256)
        manifest = {'cycle':name, 'archive':archive.name, 'size':size,
                    'sha256':sha256, 'files':files, 'archived_at':instant(),
                    'destination':BACKUP, 'state':'verified', 'source_inventory_sha256':before}
        raw = canonical(manifest)
        # Immutable per-archive manifest. A retry may have a different timestamp;
        # use the content-addressed name so no existing manifest is overwritten.
        remote.upload(name+'.'+digest(raw)[:12]+'.json', io.BytesIO(raw), len(raw), digest(raw))
        record(root, manifest)
        if name in references(root) or inventory(cycle) != files:
            raise ValueError('cycle_changed_after_backup')
        shutil.rmtree(cycle)
        record(root, {**manifest, 'state':'deleted', 'deleted_at':instant()})
    return size


def storage(root):
    usage = shutil.disk_usage(root)
    return {'free_bytes':usage.free, 'total_bytes':usage.total,
            'used_percent':round(100*usage.used/(usage.used+usage.free), 2)}


def check_storage(root):
    """Fail before collection, leaving room for state writes and recovery.

    A five-minute usage sample bounds expensive scans; the available-space
    guard is checked on every run. Retention never deletes merely to meet a cap.
    """
    status_path = root/'storage.json'
    previous = parse(status_path.read_bytes()) if status_path.exists() else {}
    cycle_bytes = previous.get('cycle_bytes', 0)
    sampled = previous.get('sampled_epoch', 0)
    if time.time()-sampled > 300:
        cycles = root/'cycles'
        cycle_bytes = int(subprocess.check_output(
            ['du','-s','-B1','--',str(cycles)], timeout=60).split()[0]) if cycles.exists() else 0
        sampled = time.time()
    minimum = int(os.environ.get('ELECTION_MIN_FREE_BYTES', str(512*1024**2)))
    maximum = int(os.environ.get('ELECTION_CYCLE_MAX_BYTES', str(4*1024**3)))
    status = {**storage(root), 'cycle_bytes':cycle_bytes, 'sampled_epoch':sampled,
              'min_free_bytes':minimum, 'max_cycle_bytes':maximum,
              'checked_at':instant()}
    status['alert'] = status['free_bytes'] < minimum*1.5 or cycle_bytes > maximum*.8
    temporary = root/('storage.json.'+os.urandom(8).hex()+'.tmp')
    with temporary.open('xb') as stream:
        stream.write(canonical(status)); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(status_path)
    if status['free_bytes'] < minimum or cycle_bytes >= maximum:
        raise ValueError('publisher_storage_limit')
    if status['alert'] and not previous.get('alert'):
        print(json.dumps({'alert':'publisher_storage_warning', **status}), flush=True)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(os.environ.get(
        'ELECTION_STATIC_STATE_DIR', '/var/lib/election-results-platform/static-ftp')))
    parser.add_argument('--apply', action='store_true', help='Archive, verify, then remove eligible cycles')
    parser.add_argument('--min-age-hours', type=float, default=24)
    parser.add_argument('--limit', type=int, default=25)
    parser.add_argument('--workers', type=int, choices=(1,2,3), default=1)
    args = parser.parse_args()
    if args.min_age_hours < 0 or args.limit < 1:
        parser.error('age must be nonnegative and limit positive')
    root = args.root
    with (root/'runner.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'status':'writer_busy_retention_deferred'}), flush=True)
            return 0
        selected = plan(root, min_age_hours=args.min_age_hours)
        print(json.dumps({**selected, 'eligible':len(selected['eligible']),
                          'dry_run':not args.apply, **storage(root)}), flush=True)
        if not args.apply:
            return 0
        count = 0
        sessions = {}
        def process(name):
            worker = threading.get_ident()
            if worker not in sessions:
                sessions[worker] = ArchiveFTP()
            for attempt in range(3):
                remote = sessions[worker]
                try:
                    return archive_one(root, name, remote)
                except (OSError, EOFError, ftplib.error_temp) as error:
                    print(json.dumps({'cycle':name, 'retry':attempt+1,
                                      'phase':getattr(remote,'phase','connect'),
                                      **error_report(error)}), flush=True)
                    if attempt == 2:
                        raise
                    remote.close(); time.sleep(attempt+1)
                    sessions[worker] = ArchiveFTP()
        try:
            from concurrent.futures import ThreadPoolExecutor
            names = selected['eligible'][:args.limit]
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                for start in range(0,len(names),args.workers):
                    # At most three small archives and sessions exist at once.
                    results=list(pool.map(process,names[start:start+args.workers]))
                    previous_count=count; count+=len(results)
                    if count//10 > previous_count//10:
                        print(json.dumps({'archived_deleted':count, **storage(root)}), flush=True)
        except Exception as error:
            print(json.dumps({'archived_deleted':count, **error_report(error)}), flush=True)
            return 1
        finally:
            for remote in sessions.values():
                remote.close()
        print(json.dumps({'archived_deleted':count, 'destination':BACKUP, **storage(root)}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
