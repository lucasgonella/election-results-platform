"""Bounded FTP21 municipality writer. Remote journal/backup; HTTPS activation gate."""
from __future__ import annotations
import argparse
import ftplib
import io
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import time
from http.client import IncompleteRead
from urllib.error import HTTPError,URLError
from urllib.request import Request, build_opener

from deploy import frontend as wire
from .election_release import canonical, digest, parse
from .municipal_release import verify

SITE='/public_html/municipal-2026'
PUBLIC='https://afgnet.com.br/municipal-2026/'
PRIVATE='/election-municipal-deploy'


def sid(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value): raise ValueError('municipal_invalid_release_id')
    return value


def http(path):
    if not re.fullmatch(r'(turnos/[12]/(version\.json|releases/[a-f0-9]{64}/[a-z0-9/-]+\.json)|geography/[a-f0-9]{64}/[a-z-]+\.json)',path): raise ValueError('municipal_unsafe_https_path')
    for attempt in range(3):
        try:
            with build_opener(wire.NoRedirect()).open(Request(PUBLIC+path,headers={'Cache-Control':'no-cache'}),timeout=30) as response:
                raw=response.read(wire.MAX_BYTES+1)
                if len(raw)>wire.MAX_BYTES: raise ValueError('municipal_oversized_https_response')
                return raw
        except HTTPError as error:
            if error.code==404:return None
            if error.code not in {408,500,502,503,504} or attempt==2:raise
        except (OSError,EOFError,URLError,IncompleteRead):
            if attempt==2:raise
        time.sleep(attempt+1)


class Transport(wire.Transport):
    def __init__(self,ftp,round_number,**kwargs):
        super().__init__(ftp,**kwargs)
        if round_number not in (1,2):raise ValueError('municipal_wrong_round')
        self.round=round_number
        self.private=PRIVATE+'/'+str(round_number)
        self.site=SITE+'/turnos/'+str(round_number)

    def allowed(self,path):
        if not isinstance(path,str) or not path.startswith('/') or any(c in path for c in ('\\','\r','\n')) or '..' in PurePosixPath(path).parts or '//' in path:
            raise ValueError('municipal_unsafe_ftp_path')
        base=path.rstrip('/')
        ancestors={'/public_html',SITE,SITE+'/turnos',PRIVATE}
        if base in ancestors or base==self.private or path.startswith(self.private+'/') or base==self.site or path.startswith(self.site+'/') or base==SITE+'/geography' or path.startswith(SITE+'/geography/'):
            return path
        raise ValueError('municipal_outside_namespace')

    def writable(self,path):
        self.allowed(path)
        if path==self.site+'/version.json':return path
        if re.fullmatch(re.escape(self.site)+r'/releases/[a-f0-9]{64}/(manifest|catalog|overview|coverage)\.json',path):return path
        if re.fullmatch(re.escape(self.site)+r'/releases/[a-f0-9]{64}/[a-z]{2}/president\.json',path):return path
        if re.fullmatch(re.escape(SITE)+r'/geography/[a-f0-9]{64}/[a-z]{2}-(national|detail)\.json',path):return path
        if path in {self.private+'/pending.json',self.private+'/current.json'}:return path
        if path==self.private+'/lock/owner.json':return path
        if re.fullmatch(re.escape(self.private)+r'/transactions/[a-f0-9]{64}/(journal|before-marker)\.json',path):return path
        raise ValueError('municipal_protected_destination')

    def metadata(self,path):
        # Read-only control reconnection, matching the existing isolated writer.
        for attempt in range(3):
            try:return super().metadata(path)
            except (OSError,EOFError,ftplib.error_temp):
                if attempt==2 or self.reconnect is None:raise
                self.ftp.close();self.ftp=self.reconnect()

    def read(self,path,*,optional=False):
        # A reset after RETR may discard a partial buffer. Start a fresh read;
        # never repeat STOR, and retain all path/size/hash and marker checks.
        for attempt in range(3):
            try:return super().read(path,optional=optional)
            except (OSError,EOFError,ftplib.error_temp) as error:
                wire.control_failure(error,'retr')
                if attempt==2 or self.reconnect is None:raise
                self.ftp.close();self.ftp=self.reconnect()

    def directory(self,path):
        self.allowed(path+'/')
        meta=self.metadata(path+'/')
        if meta:
            if meta['type']!='dir':raise ValueError('municipal_namespace_collision')
            return
        parent=str(PurePosixPath(path).parent)
        if parent not in ('/','/public_html'):self.directory(parent)
        # Reuse the component MKD procedure established for Locaweb.
        self.ftp.cwd('/')
        for part in PurePosixPath(parent).parts[1:]:self.ftp.cwd(part)
        self.ftp.mkd(PurePosixPath(path).name);self.ftp.cwd('/')
        if not self.metadata(path+'/'):raise RuntimeError('municipal_mkd_unconfirmed')

    def put(self,path,raw,*,replace=False):
        self.writable(path)
        if len(raw)>wire.MAX_BYTES:raise ValueError('municipal_file_too_large')
        old=self.read(path,optional=True)
        if old is not None and not replace:
            if old!=raw:raise RuntimeError('municipal_immutable_collision')
            return
        # Every attempt owns a new temporary; never adopt an unknown abandoned file.
        temporary=path+'.'+secrets.token_hex(16)+'.upload'
        self.allowed(temporary)
        if self.metadata(temporary):raise RuntimeError('municipal_temporary_collision')
        self.directory(str(PurePosixPath(path).parent))
        try:
            self.ftp.storbinary('STOR '+temporary,io.BytesIO(raw))
            if self.read(temporary)!=raw:raise RuntimeError('municipal_transfer_integrity')
            self._rename(temporary,path)
            if self.read(path)!=raw:raise RuntimeError('municipal_activation_integrity')
        except (OSError,EOFError,ftplib.error_temp):
            if not self.reconnect:raise
            self.ftp.close();self.ftp=self.reconnect()
            current=self.read(path,optional=True);pending=self.read(temporary,optional=True)
            if current==raw and pending is None:return
            if pending!=raw:raise RuntimeError('municipal_transfer_not_reconciled')
            self._rename(temporary,path)
            if self.read(path)!=raw:raise RuntimeError('municipal_activation_integrity')


class Publisher:
    def __init__(self,transport,*,http_read=http,fault=lambda _:None):
        self.t,self.http,self.fault=transport,http_read,fault
        self.private=transport.private;self.marker_path=transport.site+'/version.json'
        self.relative='turnos/'+str(transport.round)+'/version.json'

    def marker(self):
        raw=self.t.read(self.marker_path,optional=True)
        if self.http(self.relative)!=raw:raise RuntimeError('municipal_marker_visibility_unknown')
        if raw:
            value=parse(raw);sid(value['release_id'])
            if value['round']!=self.t.round or value.get('environment')!='oficial' or not value.get('coverage_complete'):raise ValueError('municipal_invalid_remote_marker')
        return raw

    def verify_remote(self,marker):
        value=parse(marker);release=sid(value['release_id']);prefix='turnos/'+str(self.t.round)+'/releases/'+release+'/'
        raw=self.t.read(SITE+'/'+prefix+'manifest.json')
        if digest(raw)!=value['manifest_sha256'] or len(raw)!=value['manifest_size'] or self.http(prefix+'manifest.json')!=raw:raise RuntimeError('municipal_manifest_visibility')
        m=parse(raw)
        if m['release_id']!=release or digest(canonical(m['seed']))!=release or m['election']['round']!=self.t.round or not m['coverage_complete']:raise ValueError('municipal_remote_manifest_mismatch')
        for name,entry in [(prefix+n,e) for n,e in m['files'].items()]+[(e['path'],e) for e in m['geometry'].values()]:
            raw=self.t.read(SITE+'/'+name)
            wire.verify_bytes(raw,entry)
            if self.http(name)!=raw:raise RuntimeError('municipal_https_hash_mismatch')
        return m

    def pending(self):
        raw=self.t.read(self.private+'/pending.json',optional=True)
        return parse(raw) if raw else None

    def finish(self,job,status):
        self.t.put(self.private+'/transactions/'+job['release_id']+'/journal.json',canonical({**job,'phase':status}),replace=True)
        owner=self.t.read(self.private+'/lock/owner.json',optional=True)
        if owner is not None:
            if owner!=canonical({'owner':job['owner'],'release_id':job['release_id']}):raise RuntimeError('municipal_unknown_lock_owner')
            self.t.ftp.delete(self.private+'/lock/owner.json')
        self.t.ftp.rmd(self.private+'/lock')
        self.t.put(self.private+'/pending.json',canonical(None),replace=True)
        return {'status':status,'round':self.t.round,'release_id':job['release_id'],'marker_url':PUBLIC+self.relative,'multinode_guarantee':False}

    def status(self):
        raw=self.marker()
        if raw:self.verify_remote(raw)
        return {'status':'verified' if raw else 'awaiting_municipal_data','round':self.t.round,
                'release_id':parse(raw)['release_id'] if raw else None,'pending':bool(self.pending()),'lock':self.t.metadata(self.private+'/lock/') is not None}

    def recover(self):
        job=self.pending();lock=self.t.metadata(self.private+'/lock/')
        if not job:
            if lock:raise RuntimeError('municipal_orphan_lock_without_journal')
            return self.status()
        sid(job['release_id'])
        if job['round']!=self.t.round or not re.fullmatch('[a-f0-9]{64}',job.get('owner','')):raise ValueError('municipal_recovery_round_mismatch')
        old=bytes.fromhex(job['before']) if job['before'] else None
        new=bytes.fromhex(job['marker'])
        current=self.marker()
        if current not in (old,new):raise RuntimeError('municipal_external_marker_change')
        if not lock:
            self.t.ftp.mkd(self.private+'/lock')
            self.t.put(self.private+'/lock/owner.json',canonical({'owner':job['owner'],'release_id':job['release_id']}))
        else:
            owner=self.t.read(self.private+'/lock/owner.json',optional=True)
            if owner!=canonical({'owner':job['owner'],'release_id':job['release_id']}):
                history=self.t.read(self.private+'/transactions/'+job['release_id']+'/journal.json',optional=True)
                if owner is not None or not history or parse(history).get('phase') not in ('published','restored'):
                    raise RuntimeError('municipal_unknown_lock_owner')
        if current==new:
            self.verify_remote(new)
            return self.finish(job,'published')
        if old:self.verify_remote(old)
        # A prepared release is unreferenced; recovery preserves the verified
        # prior pointer and clears only this journal's exclusive lock.
        return self.finish(job,'restored')

    def publish(self,directory):
        package,values=verify(directory)
        marker=canonical(package['marker'])
        if package['marker']['round']!=self.t.round:raise ValueError('municipal_publish_round_mismatch')
        if self.pending():raise RuntimeError('municipal_requires_recovery')
        if self.t.metadata(self.private+'/lock/'):raise RuntimeError('municipal_orphan_lock_without_journal')
        old=self.marker()
        if old==marker:
            self.verify_remote(old)
            return {'status':'unchanged','release_id':parse(old)['release_id']}
        if old:self.verify_remote(old)
        if old is None and self.t.metadata(self.t.site+'/'):
            # A directory from an interrupted, officially recovered transaction
            # is recognized only if private journal history exists.
            if not self.t.metadata(self.private+'/transactions/'):raise RuntimeError('municipal_namespace_collision')
        self.t.directory(self.private)
        release=package['marker']['release_id']
        job={'schema':1,'round':self.t.round,'release_id':release,'before':old.hex() if old else None,'marker':marker.hex(),'phase':'prepared','owner':secrets.token_hex(32)}
        self.t.ftp.mkd(self.private+'/lock');self.fault('after_lock')
        self.t.put(self.private+'/lock/owner.json',canonical({'owner':job['owner'],'release_id':job['release_id']}))
        self.t.put(self.private+'/pending.json',canonical(job),replace=True)
        self.t.put(self.private+'/transactions/'+release+'/journal.json',canonical(job),replace=True)
        self.fault('after_journal')
        if old:self.t.put(self.private+'/transactions/'+release+'/before-marker.json',old)
        for name,raw in sorted(values.items()):self.t.put(SITE+'/'+name,raw);self.fault('after_file')
        self.verify_remote(marker)
        self.fault('before_activation')
        if self.marker()!=old:raise RuntimeError('municipal_external_marker_change')
        self.t.put(self.marker_path,marker,replace=True)
        self.fault('after_activation')
        if self.marker()!=marker:raise RuntimeError('municipal_activation_unconfirmed')
        self.verify_remote(marker)
        self.t.put(self.private+'/current.json',marker,replace=True)
        return self.finish(job,'published')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('operation',choices=['publish','status','recover']);p.add_argument('--round',type=int,choices=[1,2],required=True);p.add_argument('--package',type=Path)
    a=p.parse_args()
    try:
        # Frontend recovery gates remain in force; this writer never repairs them.
        visual=wire.Transport(wire.connect(),reconnect=wire.connect)
        try:
            for component in ['portal','raio-x']:
                if visual.metadata('/frontend-deploy/'+component+'/lock/') is not None:raise RuntimeError('frontend_requires_recovery')
        finally:visual.ftp.close()
        t=Transport(wire.connect(),a.round,reconnect=wire.connect)
        try:
            publisher=Publisher(t)
            import json
            print(json.dumps(publisher.publish(a.package) if a.operation=='publish' else getattr(publisher,a.operation)()),flush=True)
        finally:t.ftp.close()
    except Exception as error:
        import json
        print(json.dumps(wire.error_report(error)),flush=True)
        raise SystemExit(1)
