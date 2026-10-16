"""Bounded private transfer benchmark. Never uses public files as destinations."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import time

from deploy.ssh_transport import transport
from deploy import frontend as wire


ROOT = '/election-ssh-benchmark'


class Policy(wire.Transport):
    def allowed(self, path):
        if not (path.rstrip('/') == ROOT or path.startswith(ROOT+'/')) or '..' in PurePosixPath(path).parts:
            raise ValueError('benchmark_private_namespace_only')
        return path
    def writable(self, path):
        self.allowed(path)
        if not path.endswith('.json'): raise ValueError('benchmark_json_only')
        return path


def run(source, report, selected="ssh", batch=False, cold=False):
    values = {p.relative_to(source).as_posix():p.read_bytes() for p in sorted(source.rglob('*.json'))}
    if not values or len(values) > 150 or sum(map(len, values.values())) > 64*1024*1024:
        raise ValueError('benchmark_bounded_source_required')
    name = secrets.token_hex(16)
    if cold:
        # Unique JSON whitespace changes hashes only in PRIVATE copies; this
        # prevents previous benchmark objects from warming the content cache.
        suffix = bytes(9 if bit == '0' else 32 for c in name for bit in f'{int(c,16):04b}')
        values = {n:raw.rstrip()+b'\n'+suffix+b'\n' for n,raw in values.items()}
    rows = []
    for kind, chosen in [('small', dict(list(values.items())[:1])), ('medium', dict(list(values.items())[:10])),
                         ('release', values), ('unchanged', values), ('few_changed', values)]:
        start = time.monotonic()
        t = transport(Policy, 'benchmark') if selected == 'ssh' else Policy(wire.connect(), reconnect=wire.connect)
        connected = time.monotonic()
        base = ROOT+'/'+name+'/'+('release' if kind in {'unchanged', 'few_changed'} else kind)
        if kind == 'few_changed':
            # Valid JSON, changed only inside this synthetic private benchmark.
            chosen = dict(chosen)
            key = next(iter(chosen))
            chosen[key] = chosen[key] + b' \n'
        transferred = time.monotonic()
        try:
            if batch and kind != 'few_changed': t.put_many({base+'/'+file:raw for file,raw in chosen.items()})
            else:
                for file, raw in chosen.items(): t.put(base+'/'+file, raw, replace=kind=='few_changed' and file==key)
            transferred = time.monotonic()
            for file, raw in chosen.items():
                if t.read(base+'/'+file) != raw: raise ValueError('benchmark_hash_mismatch')
            rows.append({'kind':kind, 'files':len(chosen), 'bytes':sum(map(len, chosen.values())),
                         'connect_seconds':connected-start, 'transfer_seconds':transferred-connected,
                         'verification_seconds':time.monotonic()-transferred,
                         'total_seconds':time.monotonic()-start, 'metrics':dict(getattr(t.ftp, 'metrics', {}))})
        except Exception as error:
            rows.append({'kind':kind, 'status':'failed', 'total_seconds':time.monotonic()-start, **wire.error_report(error)})
            report.write_text(json.dumps({'namespace':ROOT+'/'+name,selected:rows,'public_writes':0},indent=2))
            raise
        finally:
            if selected == 'ssh': t.ftp.shutdown()
            else: t.ftp.close()
        report.write_text(json.dumps({'namespace':ROOT+'/'+name, selected:rows, 'public_writes':0}, indent=2))
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--transport', choices=['ftp','ssh'], default='ssh')
    parser.add_argument('--batch', action='store_true')
    parser.add_argument('--cold', action='store_true')
    args = parser.parse_args()
    try:
        rows = run(args.source, args.report, args.transport, args.batch, args.cold)
        print(json.dumps(rows))
    except Exception as error:
        print(json.dumps(wire.error_report(error)))
        raise SystemExit(1)
