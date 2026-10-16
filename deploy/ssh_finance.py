"""Opt-in SSH publication of the existing single Goiás finance JSON.

The importer is unchanged. Unlike the legacy in-place FTP upload, SSH keeps a
private before image and pending journal and requires explicit recovery on error.
"""
from pathlib import PurePosixPath
import re
import secrets

from . import frontend as wire
from .ssh_transport import transport

PUBLIC = '/public_html/eleicoes/goias/raio-x/data/go-2026.json'
PRIVATE = '/goias-finance-deploy'


class Policy(wire.Transport):
    def allowed(self, path):
        if (not path.startswith('/') or '..' in PurePosixPath(path).parts or '//' in path
                or any(c in path for c in ('\\','\n','\r'))): raise ValueError('unsafe_finance_path')
        base = path.rstrip('/')
        if base in {PUBLIC, str(PurePosixPath(PUBLIC).parent)} or path.startswith(PUBLIC+'.') or base == PRIVATE or path.startswith(PRIVATE+'/'):
            return path
        raise ValueError('outside_finance_namespace')

    def writable(self, path):
        self.allowed(path)
        if path == PUBLIC or path in {PRIVATE+'/current.json', PRIVATE+'/pending.json', PRIVATE+'/lock/owner.json'}:
            return path
        if re.fullmatch(PRIVATE+r'/transactions/[a-f0-9]{32}/(before|journal)\.json', path): return path
        raise ValueError('protected_finance_destination')


def recover(t, https):
    pending = wire.decode(t.read(PRIVATE+'/pending.json'))
    if pending.get('phase') not in {'prepared','complete','restored'} or not re.fullmatch('[a-f0-9]{32}', pending.get('transaction','')):
        raise ValueError('unknown_finance_journal')
    owner = wire.decode(t.read(PRIVATE+'/lock/owner.json'))
    if owner != {'transaction':pending['transaction']}: raise ValueError('unknown_finance_lock_owner')
    before = t.read(PRIVATE+'/transactions/'+pending['transaction']+'/before.json')
    if wire.digest(before) != pending['before_sha256']: raise ValueError('finance_backup_corrupt')
    actual, visible = t.read(PUBLIC), https()
    permitted = {pending['before_sha256'], pending['after_sha256']}
    if wire.digest(actual) not in permitted or visible != actual: raise ValueError('external_finance_publication')
    if pending['phase'] == 'complete':
        current = wire.decode(t.read(PRIVATE+'/current.json'))
        if current != pending or wire.digest(actual) != pending['after_sha256']:
            raise ValueError('finance_commit_not_verified')
        t.ftp.delete(PRIVATE+'/lock/owner.json'); t.ftp.rmd(PRIVATE+'/lock')
        return {'status':'completed', 'transport':'ssh_rsync', 'sha256':wire.digest(actual)}
    if actual != before: t.put(PUBLIC, before, replace=True)
    if t.read(PUBLIC) != before or https() != before: raise ValueError('finance_restore_not_verified')
    t.put(PRIVATE+'/pending.json', wire.encode({**pending,'phase':'restored'}), replace=True)
    t.ftp.delete(PRIVATE+'/lock/owner.json'); t.ftp.rmd(PRIVATE+'/lock')
    return {'status':'recovered', 'transport':'ssh_rsync', 'sha256':wire.digest(before)}


def publish(raw, https):
    t = transport(Policy, 'finance')
    try:
        before = t.read(PUBLIC)
        if https() != before: raise ValueError('finance_baseline_visibility_unknown')
        if t.metadata(PRIVATE+'/lock') is not None: raise ValueError('finance_requires_recovery')
        prior = t.read(PRIVATE+'/pending.json', optional=True)
        if prior and wire.decode(prior).get('phase') == 'prepared': raise ValueError('finance_requires_recovery')
        if before == raw:
            return {'status':'unchanged', 'transport_metrics':dict(t.ftp.metrics)}
        transaction = secrets.token_hex(16)
        t.directory(PRIVATE); t.ftp.mkd(PRIVATE+'/lock')
        t.put(PRIVATE+'/lock/owner.json', wire.encode({'transaction':transaction}))
        base = PRIVATE+'/transactions/'+transaction
        t.put(base+'/before.json', before)
        job = {'transaction':transaction, 'phase':'prepared', 'before_sha256':wire.digest(before), 'after_sha256':wire.digest(raw)}
        t.put(base+'/journal.json', wire.encode(job))
        t.put(PRIVATE+'/pending.json', wire.encode(job), replace=True)
        if t.read(PUBLIC) != before or https() != before: raise ValueError('external_finance_publication')
        t.put(PUBLIC, raw, replace=True)
        if t.read(PUBLIC) != raw or https() != raw: raise ValueError('finance_publication_not_verified')
        job['phase'] = 'complete'
        t.put(base+'/journal.json', wire.encode(job), replace=True)
        t.put(PRIVATE+'/current.json', wire.encode(job), replace=True)
        t.put(PRIVATE+'/pending.json', wire.encode(job), replace=True)
        t.ftp.delete(PRIVATE+'/lock/owner.json'); t.ftp.rmd(PRIVATE+'/lock')
        return {'status':'published', 'transport_metrics':dict(t.ftp.metrics)}
    finally: t.ftp.close()


if __name__ == '__main__':
    import argparse
    import json
    from tools.goias_finance_publish import https_read
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['status','recover'])
    parser.add_argument('--writer-stopped', action='store_true')
    args = parser.parse_args()
    try:
        t = transport(Policy, 'finance')
        try:
            if args.operation == 'recover':
                if not args.writer_stopped: raise ValueError('finance_recovery_requires_stopped_writer')
                result = recover(t, https_read)
            else:
                raw = t.read(PUBLIC)
                if https_read() != raw: raise ValueError('finance_visibility_unknown')
                pending = t.read(PRIVATE+'/pending.json', optional=True)
                result = {'status':'verified', 'sha256':wire.digest(raw), 'bytes':len(raw),
                          'lock':t.metadata(PRIVATE+'/lock') is not None,
                          'journal_phase':wire.decode(pending).get('phase') if pending else None}
            print(json.dumps(result))
        finally: t.ftp.close()
    except Exception as error:
        print(json.dumps({'status':'failed', **wire.error_report(error)}))
        raise SystemExit(1)
