"""Prepare/upload immutable code artifacts; never overwrite live application paths."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from collector.src.ftp_delivery import canonical, upload
from collector.src.ftp_safety import validate_inbox


def validate_artifact(directory, component):
    """Recheck the bytes to be uploaded, including allowlist and no extra files."""
    if directory.is_symlink() or any(p.is_symlink() for p in directory.rglob('*')):
        raise ValueError('unsafe_artifact')
    raw=(directory/'artifact.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=directory.name or (directory/'READY').read_text().strip()!=directory.name:
        raise ValueError('artifact_integrity_error')
    manifest=json.loads(raw)
    if manifest.get('component')!=component or not manifest.get('files'):
        raise ValueError('invalid_component')
    expected={'artifact.json','READY'}
    for name,entry in manifest['files'].items():
        from pathlib import PurePosixPath
        parts=PurePosixPath(name).parts
        if (not parts or PurePosixPath(name).is_absolute() or '\\' in name
                or any(p.startswith('.') or p in {'goias','data','node_modules'} for p in parts)):
            raise ValueError('unsafe_artifact')
        if component=='control' and name not in {'election-ftp-control.php','tools/ftp-publication.php','tools/prepare-ftp-baseline.php'}:
            raise ValueError('unsafe_artifact')
        if component=='portal' and Path(name).suffix not in {'.html','.css','.js','.svg','.png','.ico'}:
            raise ValueError('unsafe_artifact')
        path=directory/'files'/name
        if any(p.is_symlink() for p in [path,*path.parents] if p==directory or directory in p.parents):
            raise ValueError('unsafe_artifact')
        value=path.read_bytes()
        if len(value)!=entry['size'] or hashlib.sha256(value).hexdigest()!=entry['sha256']:
            raise ValueError('artifact_integrity_error')
        expected.add('files/'+name)
    if any(p.is_symlink() for p in directory.rglob('*')) or {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}!=expected:
        raise ValueError('unsafe_artifact')
    return manifest


def package(component, root, output):
    if component == 'portal':
        source = root / 'web/public/eleicoes'
        candidates = [p for p in source.rglob('*') if p.is_file() and 'goias' not in p.relative_to(source).parts]
        extensions = {'.html', '.css', '.js', '.svg', '.png', '.ico'}
    elif component == 'control':
        source = root / 'deploy/locaweb'
        candidates = [source / name for name in ['election-ftp-control.php', 'ftp-publication.php']]
        extensions = {'.php'}
    else:
        raise ValueError('invalid_component')
    contents = {}
    for path in candidates:
        relative = path.relative_to(source)
        if path.is_symlink() or any(part.startswith('.') or part in {'data','node_modules','__pycache__'} for part in relative.parts):
            raise ValueError('unsafe_artifact')
        if path.suffix not in extensions:
            continue
        contents[relative.as_posix()] = path.read_bytes()
    if component == 'control':
        if (source/'prepare-ftp-baseline.php').is_symlink():
            raise ValueError('unsafe_artifact')
        # A single self-contained public file can be installed by atomic rename.
        # Keep offline adoption tools private; no runtime dependency on a second
        # PHP file being overwritten in the middle of a request.
        helper = contents['ftp-publication.php'].decode('utf-8').split('declare(strict_types=1);', 1)[1]
        endpoint = contents['election-ftp-control.php'].decode('utf-8').split('declare(strict_types=1);', 1)[1]
        endpoint = endpoint.replace("require_once __DIR__ . '/ftp-publication.php';", '')
        contents = {'election-ftp-control.php': ('<?php\ndeclare(strict_types=1);\n' + helper + '\n' + endpoint).encode('utf-8'),
                    'tools/ftp-publication.php': (source/'ftp-publication.php').read_bytes(),
                    'tools/prepare-ftp-baseline.php': (source/'prepare-ftp-baseline.php').read_bytes()}
    if not contents:
        raise ValueError('empty_artifact')
    manifest = canonical({'component':component,'files':{name:{'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)} for name,raw in contents.items()}})
    artifact = output / hashlib.sha256(manifest).hexdigest()
    artifact.mkdir(parents=True, exist_ok=False)
    for name, raw in contents.items():
        target = artifact / 'files' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (artifact/'artifact.json').write_bytes(manifest)
    (artifact/'READY').write_text(artifact.name)
    return artifact


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['package','upload'])
    parser.add_argument('--component',choices=['portal','control'])
    parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args()
    if args.action=='package':
        print(package(args.component,Path(__file__).resolve().parents[2],args.directory))
    else:
        if os.environ.get('LOCAWEB_FTP_ISOLATION_APPROVED')!='true': raise ValueError('ftp_isolation_not_approved')
        if os.environ.get('LOCAWEB_FTP_PORT','21')!='21': raise ValueError('ftp_port_must_be_21')
        validate_inbox(os.environ['LOCAWEB_FTP_CODE_INBOX_DIR'])
        validate_artifact(args.directory,args.component)
        upload(args.directory,os.environ['LOCAWEB_FTP_CODE_INBOX_DIR'].rstrip('/')+'/'+args.component,
               os.environ['LOCAWEB_FTP_HOST'],os.environ['LOCAWEB_FTP_USER'],os.environ['LOCAWEB_FTP_PASSWORD'])
        print(json.dumps({'status':'staged','artifact_id':args.directory.name}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status':'failed','error_type':type(error).__name__}))
        raise SystemExit(1)
