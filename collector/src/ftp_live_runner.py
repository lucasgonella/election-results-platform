"""Opt-in app01 runner. The existing service and publisher are unchanged."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil

from .ftp_delivery import Control, freeze, key_from_file, publish, upload
from .ftp_safety import validate_runner_environment


def save(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def acknowledge(root: Path, job: dict):
    """Resume an interrupted state swap using the recorded delivery identity."""
    active, frozen = root / 'state', root / 'ftp-queue' / ('state-' + job['id'])
    previous = root / 'ftp-queue' / ('previous-' + job['id'])
    if frozen.exists():
        if active.exists() and not previous.exists():
            active.replace(previous)
        if active.exists():
            raise RuntimeError('state_swap_conflict')
        frozen.replace(active)
    elif not active.is_dir():
        raise RuntimeError('state_swap_incomplete')
    save(root / 'ftp-queue' / 'confirmed.json', {'snapshot_id': job['receipt']['snapshot_id'], 'delivery_id': job['id']})
    (root / 'ftp-queue' / 'current.json').unlink()
    # Keep prior states and frozen deliveries for supervised retention/recovery.


def run():
    # Reject incomplete/unapproved configuration before touching live state or TSE.
    validate_runner_environment(os.environ)
    import fcntl  # app01/Linux only; no Windows production runner.
    from . import live_publisher
    active, pending, stage = live_publisher.state_paths()
    root = active.parent
    queue = root / 'ftp-queue'
    queue.mkdir(parents=True, exist_ok=True)
    with (queue / 'runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        job_path = queue / 'current.json'
        if job_path.exists():
            job = json.loads(job_path.read_text())
        else:
            if not (queue / 'confirmed.json').exists() and active.exists():
                raise RuntimeError('migration_baseline_requires_review')
            live_publisher.prepare()
            if not stage.exists():
                return {'status': 'unchanged'}
            baseline = json.loads((queue / 'confirmed.json').read_text())['snapshot_id'] if (queue / 'confirmed.json').exists() else None
            delivery = freeze(stage, queue / 'deliveries', key_from_file(os.environ['ELECTION_HMAC_KEY_FILE']), baseline)
            frozen = queue / ('state-' + delivery.name)
            if frozen.exists():
                raise RuntimeError('orphan_state_requires_review')
            shutil.copytree(pending, frozen)
            job = {'id': delivery.name}
            save(job_path, job)
        if 'receipt' not in job:
            delivery = queue / 'deliveries' / job['id']
            key = key_from_file(os.environ['ELECTION_HMAC_KEY_FILE'])
            receipt = publish(delivery, Control(os.environ['ELECTION_FTP_CONTROL_URL'], key), lambda: upload(
                delivery, os.environ['LOCAWEB_FTP_ELECTION_INBOX_DIR'], os.environ['LOCAWEB_FTP_HOST'],
                os.environ['LOCAWEB_FTP_USER'], os.environ['LOCAWEB_FTP_PASSWORD']))
            job['receipt'] = receipt
            save(job_path, job)
        acknowledge(root, job)
        return {'status': 'committed', 'delivery_id': job['id']}


if __name__ == '__main__':
    try:
        print(json.dumps(run()))
    except Exception:
        # Exception bodies may contain remote messages; log only the class.
        import logging
        logging.exception('ftp_live_failed', exc_info=False)
        raise SystemExit(1)
