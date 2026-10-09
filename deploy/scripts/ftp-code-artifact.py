"""Prepare/upload immutable code artifacts; never overwrite live application paths."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from collector.src.ftp_delivery import canonical, upload


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
        upload(args.directory,os.environ['LOCAWEB_FTP_CODE_INBOX_DIR'].rstrip('/')+'/'+args.component,
               os.environ['LOCAWEB_FTP_HOST'],os.environ['LOCAWEB_FTP_USER'],os.environ['LOCAWEB_FTP_PASSWORD'])
        print(json.dumps({'status':'staged','artifact_id':args.directory.name}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status':'failed','error_type':type(error).__name__}))
        raise SystemExit(1)
