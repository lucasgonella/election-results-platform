"""Assisted baseline checkpoint: preserve all existing live state and pending data."""
import argparse
from contextlib import contextmanager
import hashlib
import hmac
import json
from pathlib import Path

from .ftp_delivery import key_from_file
from .ftp_live_runner import save

STATE_FILES = {'manifest.json', 'version.json', 'alerts.json', 'target-state.json', 'state-meta.json'}


def verify(root, directory, marker, key):
    raw = (directory / 'plan.json').read_bytes()
    if not hmac.compare_digest(hmac.new(key, raw, 'sha256').hexdigest(), (directory / 'plan.sig').read_text().strip()):
        raise ValueError('invalid_plan_signature')
    plan = json.loads(raw)
    if plan.get('schema_version') != 1 or set(plan.get('state_hashes', {})) != STATE_FILES:
        raise ValueError('invalid_plan')
    if hashlib.sha256(marker.read_bytes()).hexdigest() != plan['marker_sha256']:
        raise ValueError('baseline_changed')
    if json.loads(marker.read_bytes()).get('snapshot_id') != plan['snapshot_id']:
        raise ValueError('baseline_changed')
    if len(plan.get('inventory', {})) != 140 or len(plan.get('watermarks', {})) != 137:
        raise ValueError('invalid_plan')
    for name, expected in plan['state_hashes'].items():
        path = root / 'state' / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('state_changed')
    return plan


@contextmanager
def lock(path):
    with path.open('a+b') as stream:
        try:
            import fcntl
        except ImportError:
            import msvcrt
            if stream.seek(0, 2) == 0:
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            try: yield
            finally:
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try: yield
            finally: fcntl.flock(stream, fcntl.LOCK_UN)


def adopt(root: Path, directory: Path, marker: Path, key: bytes):
    queue = root / 'ftp-queue'
    queue.mkdir(exist_ok=True)
    with lock(queue / 'runner.lock'):
        plan = verify(root, directory, marker, key)
        if (queue / 'current.json').exists():
            raise ValueError('delivery_in_flight')
        checkpoint = {'snapshot_id': plan['snapshot_id'], 'adopted_baseline': True,
                      'adoption_plan_sha256': hashlib.sha256((directory / 'plan.json').read_bytes()).hexdigest()}
        confirmed = queue / 'confirmed.json'
        if confirmed.exists():
            if json.loads(confirmed.read_text()) != checkpoint:
                raise ValueError('checkpoint_conflict')
        else:
            save(confirmed, checkpoint)
        return {'status': 'baseline_adopted', 'snapshot_id': plan['snapshot_id']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--marker', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(adopt(args.root, args.plan, args.marker, key_from_file(args.key_file))))
    except Exception as error:
        print(json.dumps({'status':'failed','error_type':type(error).__name__}))
        raise SystemExit(1)
