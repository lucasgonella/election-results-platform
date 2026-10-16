"""Complete election JSON releases over plain passive FTP 21.

No HMAC, PHP controller or assertion of FTP account isolation. One final marker
rename selects already verified immutable files. No distributed/NFS durability
guarantee; interrupted transactions remain for explicit recovery.
"""
from __future__ import annotations
import argparse
import ftplib
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import re
import secrets
from pathlib import Path, PurePosixPath
from urllib.request import Request, build_opener

from deploy import frontend as wire
from .election_release import META, canonical, candidates, digest, parse, source, stamp, targets, tree, transition, validate_release


def instant():
    return datetime.now(timezone.utc).isoformat()


def layout(environment):
    if environment not in {'production', 'staging'}:
        raise ValueError('invalid_environment')
    site = '/public_html/data' if environment == 'production' else '/public_html/__election_static_staging/data'
    return site, '/election-static-deploy/' + environment


def identity(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('invalid_release_id')
    return value


class Transport(wire.Transport):
    def __init__(self, ftp, environment='production', **kwargs):
        super().__init__(ftp, **kwargs)
        self.environment = environment
        self.site, self.private = layout(environment)

    def _readonly_retry(self, operation):
        """Keep transport failure types so put can reconcile a lost response."""
        import time
        for attempt in range(3):
            try:
                return operation()
            except (OSError, EOFError, ftplib.error_temp) as error:
                if isinstance(error, ftplib.error_temp) and not str(error).startswith('421'):
                    raise
                if attempt == 2 or self.reconnect is None:
                    # Wrapping this in RuntimeError hid timeouts from the
                    # shared put/read-after-write reconciliation mechanism.
                    raise
                self.ftp.close()
                time.sleep(attempt + 1)
                self.ftp = self.reconnect()

    def metadata(self, path):
        if getattr(self, '_reading', False):
            return super().metadata(path)
        return self._readonly_retry(lambda: super(Transport, self).metadata(path))

    def read(self, path, *, optional=False):
        self.allowed(path)
        self._reading = True
        try:
            return self._readonly_retry(
                lambda: super(Transport, self).read(path, optional=optional))
        finally:
            self._reading = False

    def allowed(self, path):
        if (not isinstance(path, str) or any(c in path for c in ('\r', '\n', '\\'))
                or '..' in PurePosixPath(path).parts or '//' in path):
            raise ValueError('unsafe_election_path')
        ancestors={'/election-static-deploy'}
        if self.environment=='staging': ancestors.add('/public_html/__election_static_staging')
        if path.rstrip('/') not in ancestors and not any(path.rstrip('/') == root or path.startswith(root + '/') for root in (self.site, self.private)):
            raise ValueError('outside_election_namespace')
        return path

    def writable(self, path):
        self.allowed(path)
        if path == self.site + '/version.json':
            return path
        if path.startswith(self.site + '/releases/'):
            parts = path[len(self.site+'/releases/'):].split('/', 1)
            if len(parts) == 2 and identity(parts[0]) and parts[1] in set(targets()) | META:
                return path
        relative = path.removeprefix(self.private+'/')
        if relative in {'current.json', 'pending.json', 'watermarks.json'}:
            return path
        match = re.fullmatch(r'(transactions|staging)/([a-f0-9]{64})/(.+)', relative)
        if match:
            name = match[3]
            if name in {'journal.json', 'descriptor.json', 'before-marker.json', 'before-descriptor.json'}:
                return path
            if name.startswith(('before/', 'files/')) and name.split('/',1)[1] in set(targets()) | META:
                return path
        backup=re.fullmatch(r'backups/([a-f0-9]{64})/files/(.+)',relative)
        if backup and backup[2] in set(targets())|META:return path
        raise ValueError('protected_election_destination')

    def put(self, path, raw, *, replace=False):
        if replace and path.startswith(self.site+'/releases/'):
            raise ValueError('immutable_release')
        return super().put(path, raw, replace=replace)

    def directory(self, path):
        """Use short MKD basenames, as the isolated round-two client does."""
        self.allowed(path+'/')
        actual = self.metadata(path+'/')
        if actual is not None:
            if actual['type'] != 'dir': raise RuntimeError('not_directory')
            return
        parent = str(PurePosixPath(path).parent)
        if parent not in {'/', '/public_html'}: self.directory(parent)
        try:
            self.ftp.cwd('/')
            for part in PurePosixPath(parent).parts[1:]: self.ftp.cwd(part)
            self.ftp.mkd(PurePosixPath(path).name)
            self.ftp.cwd('/')
            actual = self.metadata(path+'/')
            if actual is None or actual['type'] != 'dir':
                raise RuntimeError('election_directory_creation_unconfirmed')
        except (OSError, EOFError, ftplib.Error):
            if self.reconnect is None: raise
            self.ftp.close()
            self.ftp = self.reconnect()
            actual = self.metadata(path+'/')
            if actual is None or actual['type'] != 'dir':
                raise RuntimeError('election_directory_creation_unconfirmed') from None
            # Only a directory actually inspected after a lost response is
            # adopted. Never replay an uncertain MKD or remove another path.

    @contextmanager
    def lock(self):
        self.directory(self.private)
        lock = self.private + '/lock'
        self.ftp.mkd(lock)
        finished = False
        try:
            yield
            finished = True
        finally:
            if finished and self.metadata(lock+'/') is not None:
                self.ftp.rmd(lock)


ELECTION_FTP_TIMEOUT = 15
ELECTION_FTP_DATA_TIMEOUT = 60


def election_ftp_connect():
    """Keep the shared EPSV transport, but bound election FTP I/O to 15s.

    The shared frontend/Goias FTP client retains its original timeout.
    Both control and future data sockets must use the shorter timeout.
    """
    ftp = wire.connect()
    # Data sockets need enough time for complete JSONs/backups. Keep control
    # commands bounded separately, including reconnects after an idle session.
    ftp.timeout = ELECTION_FTP_DATA_TIMEOUT
    ftp.sock.settimeout(ELECTION_FTP_TIMEOUT)
    return ftp


def connect(environment):
    """Retry only FTP session establishment, before any transaction writes.

    Never retry publish/activate here: a failed write may already have
    succeeded remotely, and requires explicit reconciliation.
    """
    from deploy.ssh_transport import selection, transport
    if selection() == 'ssh':
        return transport(Transport, 'first-' + environment, environment)
    import time
    last_error = None
    for attempt in range(3):
        try:
            ftp = election_ftp_connect()
            return Transport(ftp, environment, reconnect=election_ftp_connect)
        except (ConnectionError, TimeoutError, EOFError, OSError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(attempt + 1)
    raise RuntimeError('election_ftp_connect_failed') from last_error


def http_read(environment, relative):
    site, _ = layout(environment)
    url = 'https://afgnet.com.br' + site.removeprefix('/public_html') + '/' + relative
    from urllib.error import URLError, HTTPError
    import time
    for attempt in range(3):
        try:
            with build_opener(wire.NoRedirect).open(Request(url, headers={
                    'Cache-Control':'no-cache', 'Accept-Encoding':'identity'}), timeout=30) as response:
                if response.status != 200 or response.geturl() != url:
                    raise RuntimeError('unexpected_public_response')
                raw = response.read(wire.MAX_BYTES+1)
            if len(raw) > wire.MAX_BYTES:
                raise RuntimeError('oversized_public_file')
            return raw
        except (OSError, URLError) as error:
            if isinstance(error, HTTPError) and error.code not in {408,429,500,502,503,504}:
                raise
            if attempt == 2:
                raise
            time.sleep(attempt+1)


def descriptor(values):
    version = parse(values['version.json'])
    manifest = parse(values['manifest.json'])
    round_number = manifest['results'][0]['round']
    validate_release(values, version['environment'], round_number)
    return {'schema_version':1, 'environment':version['environment'], 'round':round_number,
            'generated_at':version['generated_at'], 'files':{
                name:{'sha256':digest(raw), 'size':len(raw)} for name,raw in sorted(values.items())}}


def read_release(transport, marker):
    sid = identity(marker['snapshot_id'])
    values = {name:transport.read(transport.site+'/releases/'+sid+'/'+name) for name in sorted(set(targets())|META)}
    desc = descriptor(values)
    if any(marker.get(key) != desc[key] for key in ('environment','generated_at')):
        raise ValueError('baseline_marker_mismatch')
    return values, desc


def _verify_public(transport, marker_raw, desc, *, http=None, selected=True):
    if (desc.get('schema_version')!=1 or set(desc.get('files',{}))!=set(targets())|META
            or desc.get('environment') not in {'oficial','fixture'} or type(desc.get('round')) is not int or desc['round'] not in (1,2)):
        raise ValueError('invalid_election_inventory')
    stamp(desc['generated_at'])
    for entry in desc['files'].values():
        if (type(entry.get('size')) is not int or not 0 < entry['size'] <= wire.MAX_BYTES
                or not isinstance(entry.get('sha256'),str) or not re.fullmatch('[a-f0-9]{64}',entry['sha256'])):
            raise ValueError('invalid_election_inventory')
    http = http or (lambda path: http_read(transport.environment, path))
    sid = identity(parse(marker_raw)['snapshot_id'])
    if selected and http('version.json') != marker_raw:
        raise RuntimeError('public_marker_mismatch')
    from concurrent.futures import ThreadPoolExecutor
    names = sorted(desc['files'])
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = dict(zip(names, pool.map(lambda name:http('releases/'+sid+'/'+name), names)))
    for name, raw in values.items():
        wire.verify_bytes(raw, desc['files'][name])
    validate_release(values, desc['environment'], desc['round'])
    if selected and http('version.json') != marker_raw:
        raise RuntimeError('public_selection_changed')
    return {'results':137, 'files':140, 'snapshot_id':sid, 'verified_at':instant()}


def verify_public(transport, marker_raw, desc, *, http=None, selected=True):
    # A full HTTPS audit can outlast the FTP server's idle timeout. The remote
    # MKD lock and journal survive closing the control connection; reconnect
    # before the next FTP command instead of using a stale socket.
    if transport.reconnect is None:
        return _verify_public(transport,marker_raw,desc,http=http,selected=selected)
    transport.ftp.close()
    try:return _verify_public(transport,marker_raw,desc,http=http,selected=selected)
    finally:transport.ftp=transport.reconnect()


def compare(before, after, reviews=None):
    reviews = reviews or {}
    for name in targets():
        old, new = parse(before[name]), parse(after[name])
        transition(name, old, new)
        if source(old) == source(new):
            continue
        oldc, newc = candidates(old), candidates(new)
        ambiguous = name.startswith('am/') or set(oldc) != set(newc)
        for seq in oldc.keys() & newc.keys():
            # IDG ordering alone never approves a roster/status/identity change.
            stable = lambda c:{k:v for k,v in c.items() if k not in {'votes','vote_percentage'}}
            ambiguous |= stable(oldc[seq]) != stable(newc[seq])
        if ambiguous and reviews.get(name) != digest(after[name]):
            raise ValueError('candidate_change_requires_specific_review')


def validate_watermarks(transport, before, baseline_snapshot=None):
    raw = transport.read(transport.private+'/watermarks.json', optional=True)
    marks = parse(raw) if raw else None
    current = transport.read(transport.private+'/current.json', optional=True)
    if marks is None:
        if current is not None:
            raise ValueError('lost_watermarks')
        return {name:parse(value) for name,value in before.items() if name in targets()}
    if set(marks) != set(targets()):
        raise ValueError('invalid_watermarks')
    restored=parse(transport.read(transport.private+'/pending.json',optional=True) or b'{}')
    rolled_back=restored.get('status')=='restored' and restored.get('snapshot_id')==baseline_snapshot
    for name in targets():
        try:transition(name, marks[name], parse(before[name]))
        except ValueError:
            if not rolled_back:raise
    return marks


def activate(transport, values, *, reviews=None, http=None):
    desc = descriptor(values)
    expected_environment = 'oficial' if transport.environment == 'production' else 'fixture'
    if desc['environment'] != expected_environment:
        raise ValueError('wrong_election_environment')
    sid = digest(canonical(desc))
    marker_raw = canonical(parse(values['version.json']) | {'snapshot_id':sid})
    old_marker = transport.read(transport.site+'/version.json')
    old = parse(old_marker)
    before, prior_desc = read_release(transport, old)
    verify_public(transport, old_marker, prior_desc, http=http)
    compare(before, values, reviews)
    watermarks = validate_watermarks(transport, before,old['snapshot_id'])
    for name in targets():
        transition(name, watermarks[name], parse(values[name]))
    if identity(old['snapshot_id']) == sid:
        current=parse(transport.read(transport.private+'/current.json'))
        if current.get('snapshot_id')!=sid or current.get('descriptor')!=desc:
            raise ValueError('remote_checkpoint_mismatch')
        return {'status':'unchanged', **verify_public(transport, marker_raw, desc, http=http), 'published_at':current['published_at']}
    if stamp(desc['generated_at']) <= stamp(old['generated_at']):
        raise ValueError('stale_release_generation')
    transaction=secrets.token_hex(32)
    journal_root = transport.private+'/transactions/'+transaction
    backup_root=transport.private+'/backups/'+identity(old['snapshot_id'])+'/files'
    if hasattr(transport, 'put_many'):
        transport.put_many({backup_root+'/'+name:raw for name,raw in before.items()})
    # Previous-snapshot backups are immutable and reusable across retries.
    # Verify the exact bytes before reusing; never trust an existing path alone.
    # For an absent file, upload and then verify it before proceeding.
    # A mismatched existing backup is a hard failure, not an overwrite.
    for name, raw in before.items():
        destination = backup_root+'/'+name
        saved = transport.read(destination, optional=True)
        if saved is None:
            transport.put(destination, raw)
            saved = transport.read(destination)
        if saved != raw:
            raise ValueError('existing_backup_content_mismatch')
    transport.put(journal_root+'/before-marker.json', old_marker)
    transport.put(journal_root+'/before-descriptor.json', canonical(prior_desc))
    journal = {'schema_version':1, 'status':'prepared', 'snapshot_id':sid,
               'transaction':transaction,
               'backup_snapshot_id':old['snapshot_id'],
               'before_marker':old, 'marker':parse(marker_raw), 'descriptor':desc,
               'previous_current':parse(transport.read(transport.private+'/current.json',optional=True) or b'{}')}
    transport.put(journal_root+'/journal.json', canonical(journal))
    transport.put(transport.private+'/pending.json', canonical(journal), replace=True)
    staged = transport.private+'/staging/'+sid+'/files'
    if hasattr(transport, 'put_many'):
        transport.put_many({staged+'/'+name:raw for name,raw in values.items()})
    else:
        for name, raw in values.items():
            transport.put(staged+'/'+name, raw)
    # Re-read the full staging inventory before promoting its directory.
    for name, entry in desc['files'].items():
        wire.verify_bytes(transport.read(staged+'/'+name), entry)
    transport.directory(transport.site+'/releases')
    release_root = transport.site+'/releases/'+sid
    if hasattr(transport, 'promote_release') and transport.metadata(staged+'/') is not None:
        transport.promote_release(staged, release_root, desc['files'])
    elif transport.metadata(release_root+'/') is None:
        try:
            transport.ftp.rename(staged, release_root)
        except (OSError, EOFError, ftplib.error_temp) as error:
            if isinstance(error, ftplib.error_temp) and not str(error).startswith('421'):
                raise
            if transport.reconnect is None: raise
            transport.ftp.close()
            transport.ftp = transport.reconnect()
            destination = transport.metadata(release_root+'/')
            original = transport.metadata(staged+'/')
            if destination is None or destination['type'] != 'dir' or original is not None:
                raise RuntimeError('directory_promotion_not_confirmed') from None
            # Lost RNTO completion: never repeat the rename. The full FTP and
            # HTTPS inventory is still verified below before marker selection.
    for name, entry in desc['files'].items():
        wire.verify_bytes(transport.read(release_root+'/'+name), entry)
    verify_public(transport, marker_raw, desc, http=http, selected=False)
    if transport.read(transport.site+'/version.json') != old_marker:
        raise RuntimeError('external_election_writer')
    # One final marker rename, never deletion of the current marker.
    transport.put(transport.site+'/version.json', marker_raw, replace=True)
    result = verify_public(transport, marker_raw, desc, http=http)
    journal.update(status='published', published_at=result['verified_at'])
    current = {'schema_version':1, 'snapshot_id':sid, 'descriptor':desc,
               'previous_snapshot_id':old['snapshot_id'], 'transaction':transaction,
               'published_at':result['verified_at']}
    for name in targets():
        watermarks[name] = parse(values[name])
    transport.put(transport.private+'/watermarks.json', canonical(watermarks), replace=True)
    transport.put(transport.private+'/current.json', canonical(current), replace=True)
    transport.put(journal_root+'/journal.json', canonical(journal), replace=True)
    transport.put(transport.private+'/pending.json', canonical({'status':'complete','snapshot_id':sid}), replace=True)
    return {'status':'published', **result, 'published_at':result['verified_at'],
            'transaction':transaction,
            'activation':'verified_release_then_single_marker_rename', 'multinode_guarantee':False,
            'physical_durability_guarantee':False, 'transport_authenticated_by_hmac':False}


def recover(transport, *, http=None, expected_snapshot=None):
    # Caller must establish that the writer stopped; never steal a live lock.
    if transport.metadata(transport.private+'/lock/') is None:
        raise RuntimeError('no_abandoned_election_lock')
    pending=transport.read(transport.private+'/pending.json',optional=True)
    if pending is None:
        marker_raw=transport.read(transport.site+'/version.json');marker=parse(marker_raw)
        if expected_snapshot is None or identity(expected_snapshot)!=marker['snapshot_id']:
            raise ValueError('unrecorded_lock_requires_baseline_review')
        before,desc=read_release(transport,marker);validate_watermarks(transport,before)
        result=verify_public(transport,marker_raw,desc,http=http)
        transport.ftp.rmd(transport.private+'/lock')
        return {'status':'recovered_before_journal',**result}
    journal = parse(pending)
    if journal.get('status') == 'complete':
        marker_raw=transport.read(transport.site+'/version.json')
        before, desc=read_release(transport, parse(marker_raw))
        validate_watermarks(transport,before,parse(marker_raw)['snapshot_id'])
        result=verify_public(transport,marker_raw,desc,http=http)
    elif journal.get('status') == 'prepared':
        sid=identity(journal['transaction']); base=transport.private+'/transactions/'+sid
        old_marker=transport.read(base+'/before-marker.json')
        if parse(old_marker)!=journal['before_marker']:
            raise ValueError('invalid_recovery_marker')
        desc=parse(transport.read(base+'/before-descriptor.json'))
        backup_root=transport.private+'/backups/'+identity(journal['backup_snapshot_id'])+'/files'
        # Verify all backup bytes and the retained previous release before rollback.
        for name,entry in desc['files'].items():
            wire.verify_bytes(transport.read(backup_root+'/'+name),entry)
        verify_public(transport,old_marker,desc,http=http,selected=False)
        actual=transport.read(transport.site+'/version.json')
        if parse(actual) not in (journal['before_marker'],journal['marker']):
            raise RuntimeError('external_election_writer')
        transport.put(transport.site+'/version.json',old_marker,replace=True)
        result=verify_public(transport,old_marker,desc,http=http)
        # Never lower watermarks after rollback; explicit local reconciliation follows.
        transport.put(transport.private+'/current.json',canonical(journal['previous_current']),replace=True)
        transport.put(transport.private+'/pending.json',canonical({'status':'restored','snapshot_id':parse(old_marker)['snapshot_id']}),replace=True)
    elif journal.get('status') == 'restored':
        marker_raw=transport.read(transport.site+'/version.json')
        _,desc=read_release(transport,parse(marker_raw));result=verify_public(transport,marker_raw,desc,http=http)
    else:
        raise ValueError('unknown_election_recovery_state')
    transport.ftp.rmd(transport.private+'/lock')
    return {'status':'recovered',**result}



def finalize_published(transport, expected_snapshot, *, http=None):
    """Finish an abandoned publication only after full remote/public verification."""
    sid=identity(expected_snapshot)
    lock=transport.private+'/lock'
    if transport.metadata(lock+'/') is None:
        raise ValueError('missing_abandoned_lock')
    marker_raw=transport.read(transport.site+'/version.json')
    marker=parse(marker_raw)
    if marker.get('snapshot_id')!=sid:
        raise ValueError('published_snapshot_changed')
    current=parse(transport.read(transport.private+'/current.json'))
    pending=parse(transport.read(transport.private+'/pending.json'))
    tx=identity(current.get('transaction'))
    journal_path=transport.private+'/transactions/'+tx+'/journal.json'
    journal=parse(transport.read(journal_path))
    desc=current.get('descriptor')
    if (marker.get('snapshot_id')!=sid or current.get('snapshot_id')!=sid
            or pending.get('status')!='prepared' or pending.get('snapshot_id')!=sid
            or pending.get('transaction')!=tx or journal.get('transaction')!=tx
            or journal.get('status') not in {'prepared','published'}
            or journal.get('snapshot_id')!=sid or journal.get('marker')!=marker
            or journal.get('descriptor')!=desc):
        raise ValueError('forward_finalization_state_mismatch')
    values,inventory=read_release(transport,marker)
    if inventory!=desc:
        raise ValueError('forward_finalization_inventory_mismatch')
    marks=parse(transport.read(transport.private+'/watermarks.json'))
    if set(marks)!=set(targets()) or any(marks[name]!=parse(values[name]) for name in targets()):
        raise ValueError('forward_finalization_watermark_mismatch')
    receipt=verify_public(transport,marker_raw,desc,http=http)
    if journal['status']=='prepared':
        published=journal|{'status':'published','published_at':current['published_at']}
        transport.put(journal_path,canonical(published),replace=True)
        if parse(transport.read(journal_path))!=published:
            raise RuntimeError('forward_finalization_journal_mismatch')
    completed={'status':'complete','snapshot_id':sid}
    transport.put(transport.private+'/pending.json',canonical(completed),replace=True)
    if parse(transport.read(transport.private+'/pending.json'))!=completed:
        raise RuntimeError('forward_finalization_pending_mismatch')
    if transport.read(transport.site+'/version.json')!=marker_raw:
        raise ValueError('forward_finalization_marker_changed')
    transport.ftp.rmd(lock)
    return {'status':'forward_finalized',**receipt,'transaction':tx}

def rollback(transport, *, http=None):
    current=parse(transport.read(transport.private+'/current.json'))
    sid=identity(current['transaction'])
    journal=parse(transport.read(transport.private+'/transactions/'+sid+'/journal.json'))
    actual=parse(transport.read(transport.site+'/version.json'))
    if actual!=journal['marker']:
        raise ValueError('rollback_current_mismatch')
    # A rollback becomes a recoverable transaction under the same exclusive lock.
    journal['status']='prepared'
    transport.put(transport.private+'/pending.json',canonical(journal),replace=True)
    return recover(transport,http=http)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['verify','publish','recover','rollback','finalize-published'])
    parser.add_argument('--environment',choices=['production','staging'],default='production')
    parser.add_argument('--directory',type=Path)
    parser.add_argument('--reviews',type=Path)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--writer-stopped',action='store_true')
    parser.add_argument('--expected-snapshot')
    args=parser.parse_args()
    try:
        if args.operation in {'recover','finalize-published'} and not args.writer_stopped:
            raise ValueError('confirm_writer_stopped_before_recovery')
        values=tree(args.directory) if args.directory else None
        reviews=parse(args.reviews.read_bytes()) if args.reviews else {}
        if args.operation=='verify':
            result={'status':'verified','snapshot_id':digest(canonical(descriptor(values))),'files':140}
        else:
            transport=connect(args.environment)
            try:
                if args.operation=='recover': result=recover(transport,expected_snapshot=args.expected_snapshot)
                elif args.operation=='finalize-published':
                    if not args.expected_snapshot:raise ValueError('expected_snapshot_required')
                    result=finalize_published(transport,args.expected_snapshot)
                elif args.operation=='rollback':
                    with transport.lock():
                        result=rollback(transport)
                else:
                    with transport.lock(): result=activate(transport,values,reviews=reviews)
            finally: transport.ftp.close()
        code=0
    except Exception as error:
        result={'status':'failed',**wire.error_report(error)};code=1
    if args.report: args.report.write_bytes(canonical(result))
    print(json.dumps(result));return code


if __name__=='__main__':
    raise SystemExit(main())
