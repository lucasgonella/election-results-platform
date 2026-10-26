"""Two-file, journaled biometry publication in its own namespace."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from deploy import frontend as wire
from .biometry import ELECTION, canonical, now, sha, validate
from .second_round_publish import save, load

SITE = '/public_html/biometria-2026/presidente/turno-2'
PRIVATE = '/election-biometry-deploy/2'
PUBLIC = 'https://afgnet.com.br/biometria-2026/presidente/turno-2/'


class Transport(wire.Transport):
    def allowed(self, path):
        if (not isinstance(path, str) or not path.startswith('/') or '\\' in path
                or '..' in PurePosixPath(path).parts or '//' in path
                or any(ord(c) < 32 for c in path)):
            raise ValueError('biometry_unsafe_remote_path')
        roots = {SITE, PRIVATE}
        ancestors = {str(parent) for root in roots for parent in PurePosixPath(root).parents}
        if path.rstrip('/') in ancestors | roots or any(path.startswith(root + '/') for root in roots):
            return path
        raise ValueError('biometry_outside_namespace')

    def writable(self, path):
        self.allowed(path)
        if path == SITE + '/version.json':
            return path
        if re.fullmatch(re.escape(SITE) + r'/releases/[a-f0-9]{64}/panel\.json', path):
            return path
        if path in {PRIVATE + '/lock/owner.json', PRIVATE + '/current.json'}:
            return path
        if re.fullmatch(re.escape(PRIVATE) + r'/transactions/[a-f0-9]{64}/(journal|before-marker)\.json', path):
            return path
        raise ValueError('biometry_protected_destination')


def http(name):
    if name != 'version.json' and not re.fullmatch(r'releases/[a-f0-9]{64}/panel\.json', name):
        raise ValueError('biometry_unsafe_public_path')
    try:
        with build_opener(wire.NoRedirect()).open(Request(PUBLIC + name,
                headers={'Cache-Control': 'no-cache'}), timeout=30) as response:
            raw = response.read(wire.MAX_BYTES + 1)
            if len(raw) > wire.MAX_BYTES:
                raise ValueError('biometry_oversized_public_file')
            return raw
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


def marker_for(raw):
    data = validate(json.loads(raw))
    return canonical({'schema': 1, 'election': ELECTION, 'snapshot_id': sha(raw),
                      'sha256': sha(raw), 'size': len(raw), 'generated_at': data['generated_at']})


class Publisher:
    """Caller holds the private collector flock. Unknown owners are never adopted."""
    def __init__(self, transport, state, *, http_read=http, fault=lambda _: None):
        self.t, self.state, self.http, self.fault = transport, Path(state), http_read, fault
        self.job_path = self.state / 'pending-publish.json'

    def marker(self):
        raw = self.t.read(SITE + '/version.json', optional=True)
        if self.http('version.json') != raw:
            raise RuntimeError('biometry_marker_visibility_unknown')
        if raw:
            value = json.loads(raw)
            if value.get('election') != ELECTION or not re.fullmatch('[a-f0-9]{64}', value.get('snapshot_id', '')):
                raise ValueError('biometry_wrong_public_marker')
        return raw

    def verify(self, marker):
        value = json.loads(marker)
        path = 'releases/' + value['snapshot_id'] + '/panel.json'
        raw = self.t.read(SITE + '/' + path)
        if self.http(path) != raw or len(raw) != value['size'] or sha(raw) != value['sha256'] or marker_for(raw) != marker:
            raise ValueError('biometry_public_integrity_mismatch')
        return raw

    def put(self, job, path, raw, *, replace=False, old=None):
        """Record intent before transfer; reconcile only this known owner's temporary."""
        intents = job.setdefault('transfers', {})
        fingerprint = sha(raw)
        temporary = path + '.upload'
        pending = self.t.read(temporary, optional=True)
        if pending is not None:
            if intents.get(path) != fingerprint:
                raise RuntimeError('biometry_unknown_temporary')
            current = self.t.read(path, optional=True)
            if current == raw:
                self.t.ftp.delete(temporary)
                return
            if current != old or not raw.startswith(pending):
                raise RuntimeError('biometry_transfer_not_reconciled')
            if pending == raw:
                self.t._rename(temporary, path)
                if self.t.read(path) != raw:
                    raise RuntimeError('biometry_reconciled_transfer_mismatch')
                return
            # A proven partial temporary under this journal's lock can be
            # removed. The unchanged destination was inspected first.
            self.t.ftp.delete(temporary)
        intents[path] = fingerprint
        save(self.job_path, job)
        self.t.put(path, raw, replace=replace)

    def recover(self):
        job = load(self.job_path)
        if not job:
            if self.t.metadata(PRIVATE + '/lock/'):
                raise RuntimeError('biometry_unknown_remote_lock')
            return None
        raw = (self.state / 'publish-candidate.json').read_bytes()
        marker = bytes.fromhex(job['marker'])
        before = bytes.fromhex(job['before']) if job['before'] else None
        if marker_for(raw) != marker:
            raise ValueError('biometry_local_candidate_changed')
        selected = self.marker()
        if selected not in (before, marker):
            raise RuntimeError('biometry_external_marker_change')
        lock = PRIVATE + '/lock'
        exists = self.t.metadata(lock + '/')
        if job.get('committed'):
            if selected != marker or self.t.read(PRIVATE + '/current.json') != marker:
                raise RuntimeError('biometry_committed_marker_changed')
            self.verify(marker)
            if exists:
                owner = self.t.read(lock + '/owner.json', optional=True)
                if owner not in (None, canonical({'owner': job['owner']})):
                    raise RuntimeError('biometry_unknown_remote_owner')
                if owner:
                    self.t.ftp.delete(lock + '/owner.json')
                self.t.ftp.rmd(lock)
            save(self.job_path, None)
            return load(self.state / 'publication.json')
        if not exists:
            if job.get('locked'):
                raise RuntimeError('biometry_remote_lock_disappeared')
            self.t.directory(PRIVATE)
            self.t.ftp.mkd(lock)
            self.t.put(lock + '/owner.json', canonical({'owner': job['owner']}))
            job['locked'] = True
            save(self.job_path, job)
        owner = self.t.read(lock + '/owner.json', optional=True)
        if owner != canonical({'owner': job['owner']}):
            raise RuntimeError('biometry_unknown_remote_owner')
        journal = PRIVATE + '/transactions/' + job['owner'] + '/journal.json'
        self.put(job, journal, canonical({'snapshot_id': job['snapshot_id'], 'owner': job['owner']}))
        if before:
            self.verify(before) if selected == before else None
            self.put(job, PRIVATE + '/transactions/' + job['owner'] + '/before-marker.json', before)
        if selected != marker:
            self.put(job, SITE + '/releases/' + job['snapshot_id'] + '/panel.json', raw)
            self.verify(marker)
            self.fault('before_activation')
            if self.marker() != before:
                raise RuntimeError('biometry_external_marker_change')
            self.put(job, SITE + '/version.json', marker, replace=True, old=before)
            self.fault('after_activation')
        if self.marker() != marker:
            raise RuntimeError('biometry_activation_unconfirmed')
        self.verify(marker)
        receipt = {'status': 'published', 'snapshot_id': job['snapshot_id'], 'verified_at': now()}
        current = self.t.read(PRIVATE + '/current.json', optional=True)
        if current not in (None, before, marker):
            raise RuntimeError('biometry_private_marker_changed')
        self.put(job, PRIVATE + '/current.json', marker, replace=True,
                 old=current)
        save(self.state / 'publication.json', receipt)
        job['committed'] = True
        save(self.job_path, job)
        self.fault('before_cleanup')
        # Finish only the known lock, after verifying the active payload again.
        if self.t.read(lock + '/owner.json') != owner:
            raise RuntimeError('biometry_remote_owner_changed')
        self.t.ftp.delete(lock + '/owner.json')
        self.fault('after_owner_cleanup')
        self.t.ftp.rmd(lock)
        self.fault('after_lock_cleanup')
        save(self.job_path, None)
        return receipt

    def publish(self, data):
        self.recover()
        raw = canonical(validate(data))
        marker = marker_for(raw)
        before = self.marker()
        if before is None and (load(self.state / 'publication.json')
                               or self.t.metadata(SITE + '/')
                               or self.t.read(PRIVATE + '/current.json', optional=True)):
            raise RuntimeError('biometry_existing_namespace_without_marker')
        if before == marker:
            self.verify(marker)
            return {'status': 'unchanged', 'snapshot_id': sha(raw)}
        if before:
            self.verify(before)
        if self.t.metadata(PRIVATE + '/lock/'):
            raise RuntimeError('biometry_unknown_remote_lock')
        import secrets
        save(self.state / 'publish-candidate.json', data)
        job = {'schema': 1, 'owner': secrets.token_hex(32), 'snapshot_id': sha(raw),
               'marker': marker.hex(), 'before': before.hex() if before else None,
               'created_at': now(), 'transfers': {}}
        save(self.job_path, job)
        return self.recover()


def connect():
    from deploy.ssh_transport import selection, transport
    if selection() == 'ssh':
        return transport(Transport, 'biometry-2')
    return Transport(wire.connect(), reconnect=wire.connect)


def publish(state, data):
    t = connect()
    try:
        return Publisher(t, state).publish(data)
    finally:
        t.ftp.close()
