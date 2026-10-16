"""Backup-first retention of verified duplicate round-two collection cycles."""
import argparse
from datetime import datetime, timezone
import gzip
import io
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import time

from .cycle_retention import ArchiveFTP
from .election_release import canonical, digest, tree
from .second_round_publish import describe, load, local_lock, result_name, save, STATE

BACKUP = '/backup/election-results-platform/round2-cycles'
CYCLE = re.compile(r'(?<![a-f0-9])[a-f0-9]{32}(?![a-f0-9])')


def references(state):
    found = set()
    def visit(v):
        if isinstance(v, str): found.update(CYCLE.findall(v))
        elif isinstance(v, dict):
            for key, value in v.items(): visit(key); visit(value)
        elif isinstance(v, list):
            for value in v: visit(value)
    for base, dirs, files in os.walk(state, followlinks=False):
        dirs[:] = [d for d in dirs if d not in {'cycles', 'http-cache', 'work'}]
        for name in files:
            if not name.endswith('.json'): continue
            path = Path(base) / name
            if path.is_symlink(): raise ValueError('unsafe_round2_control_record')
            visit(load(path))
    return found


def inventory(cycle):
    files = {}
    for path in sorted(cycle.rglob('*')):
        if path.is_symlink(): raise ValueError('unsafe_round2_cycle_symlink')
        if path.is_dir(): continue
        name = path.relative_to(cycle).as_posix()
        if name != 'source-proof.json' and not (name.startswith('package/') and result_name(name[8:])):
            raise ValueError('unknown_round2_cycle_file')
        raw = path.read_bytes()
        files[name] = {'size': len(raw), 'sha256': digest(raw)}
    return files


def plan(state, *, min_age_hours=24, now=None):
    from .second_round_runner import verify_proof
    state = Path(state)
    if state.is_symlink() or (state / 'cycles').is_symlink(): raise ValueError('unsafe_round2_retention_root')
    pending = load(state / 'pending.json')
    if pending and pending.get('phase') not in {'prepared', 'verified', 'committed'}:
        raise ValueError('unknown_round2_transaction_state')
    protected = references(state)
    checkpoint = load(state / 'checkpoint.json') or {}
    receipts = set()
    for path in (state / 'receipts').glob('*.json'):
        receipt = load(path) or {}
        if (not re.fullmatch('[a-f0-9]{64}', path.stem) or receipt.get('status') != 'published'
                or receipt.get('snapshot_id') != path.stem):
            raise ValueError('unknown_round2_publication_receipt')
        receipts.add(path.stem)
    current = time.time() if now is None else now
    eligible, preserved = [], {}
    cycles = sorted((state / 'cycles').iterdir()) if (state / 'cycles').exists() else []
    for cycle in cycles:
        reason = None
        if cycle.is_symlink() or not cycle.is_dir() or not CYCLE.fullmatch(cycle.name): reason = 'unknown_cycle'
        elif cycle.name in protected: reason = 'referenced_recovery_or_audit'
        elif cycle.stat().st_mtime > current - min_age_hours * 3600: reason = 'recent'
        else:
            try:
                files = inventory(cycle)
                verified = verify_proof(cycle / 'package')
                sid = verified['snapshot_id']
                if sid not in receipts: reason = 'unpublished_evidence'
                else:
                    # All journals protect original publishing packages. Keep an
                    # additional current duplicate as a restoration witness.
                    if sid == checkpoint.get('snapshot_id') and not any(
                            p != cycle and p.name in protected and
                            (p / 'package').is_dir() and describe(tree(p / 'package'))['snapshot_id'] == sid
                            for p in cycles if p.is_dir() and not p.is_symlink()):
                        reason = 'active_snapshot_without_protected_package'
                    else:
                        eligible.append({'cycle': cycle.name, 'snapshot_id': sid,
                            'allocated_bytes': sum(p.stat().st_blocks * 512 for p in [cycle, *cycle.rglob('*')]),
                            'content_bytes': sum(x['size'] for x in files.values()),
                            'reason': 'old_verified_duplicate_with_publication_receipt'})
            except (ValueError, OSError, KeyError, TypeError): reason = 'incomplete_or_unknown'
        if reason: preserved[reason] = preserved.get(reason, 0) + 1
    return {'dry_run': True, 'total': len(cycles), 'eligible': eligible,
            'estimated_reclaimed_bytes': sum(x['allocated_bytes'] for x in eligible), 'preserved': preserved}


def record(state, value):
    with (state / 'retention-manifest.jsonl').open('ab') as stream:
        stream.write(canonical(value) + b'\n'); stream.flush(); os.fsync(stream.fileno())


def archive_one(state, selected, remote):
    name = selected['cycle']
    if not CYCLE.fullmatch(name) or name in references(state): raise ValueError('round2_cycle_became_referenced')
    cycle = state / 'cycles' / name
    files = inventory(cycle)
    with tempfile.TemporaryDirectory(prefix='round2-archive-', dir=state) as folder:
        archive = Path(folder) / (name + '.tar.gz')
        with archive.open('wb') as output, gzip.GzipFile(filename='', fileobj=output, mode='wb', mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|') as tar:
                for relative in files: tar.add(cycle / relative, arcname=name + '/' + relative, recursive=False)
        with tarfile.open(archive, 'r:gz') as tar:
            members = tar.getmembers()
            if len(members) != len(files): raise ValueError('round2_archive_inventory_mismatch')
            for member in members:
                relative = member.name.removeprefix(name + '/')
                if not member.isfile() or relative not in files: raise ValueError('round2_archive_unsafe_member')
                raw = tar.extractfile(member).read()
                if {'size': len(raw), 'sha256': digest(raw)} != files[relative]: raise ValueError('round2_archive_content_mismatch')
        raw = archive.read_bytes()
        remote.upload(archive.name, io.BytesIO(raw), len(raw), digest(raw))
        manifest = {**selected, 'archive': archive.name, 'size': len(raw), 'sha256': digest(raw),
                    'files': files, 'state': 'verified', 'archived_at': datetime.now(timezone.utc).isoformat(),
                    'destination': BACKUP}
        encoded = canonical(manifest)
        remote.upload(name + '.' + digest(encoded)[:12] + '.json', io.BytesIO(encoded), len(encoded), digest(encoded))
        record(state, manifest)
        if name in references(state) or inventory(cycle) != files: raise ValueError('round2_cycle_changed_after_backup')
        shutil.rmtree(cycle)
        record(state, {**manifest, 'state': 'deleted', 'deleted_at': datetime.now(timezone.utc).isoformat()})
    return manifest


def main():
    from .second_round_runner import credentials
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=Path(STATE))
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--min-age-hours', type=float, default=24)
    parser.add_argument('--limit', type=int, default=25)
    args = parser.parse_args()
    if args.min_age_hours < 0 or args.limit < 1: parser.error('Invalid age/limit')
    import json
    try:
        with local_lock(args.state):
            selected = plan(args.state, min_age_hours=args.min_age_hours)
            print(json.dumps(selected), flush=True)
            if not args.apply: return 0
            credentials()
            remote = ArchiveFTP(destination=BACKUP)
            try:
                for item in selected['eligible'][:args.limit]:
                    done = archive_one(args.state, item, remote)
                    print(json.dumps({key: value for key, value in done.items() if key != 'files'}), flush=True)
            finally: remote.close()
            from .second_round_metrics import storage
            previous = load(args.state / 'storage.json') or {}
            save(args.state / 'storage.json', {**previous, 'sampled_epoch': 0})
            try: storage(args.state)
            except RuntimeError as error:
                if str(error) != 'round2_storage_limit': raise
                print(json.dumps({'status': 'retention_complete_storage_limit_remains'}))
    except RuntimeError as error:
        if str(error) != 'second_round_writer_busy': raise
        print(json.dumps({'status': 'writer_busy_retention_deferred'}))
    return 0


if __name__ == '__main__': raise SystemExit(main())
