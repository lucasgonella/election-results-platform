"""Prepare a recoverable activation plan from an explicitly approved artifact.

Writes only a NEW plan directory. Never activates files or contacts a server.
The public code component and electoral /data tree remain independent.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re


def sha(raw): return hashlib.sha256(raw).hexdigest()


def prepare(artifact: Path, expected_id: str, public_root: Path, output: Path):
    if not re.fullmatch('[a-f0-9]{64}', expected_id) or artifact.name != expected_id:
        raise ValueError('unapproved_artifact')
    raw=(artifact/'artifact.json').read_bytes()
    if sha(raw)!=expected_id or (artifact/'READY').read_text().strip()!=expected_id:
        raise ValueError('unapproved_artifact')
    manifest=json.loads(raw); component=manifest.get('component')
    if component not in {'portal','control'} or not manifest.get('files'):
        raise ValueError('invalid_component')
    contents={}
    for name,entry in manifest['files'].items():
        parts=PurePosixPath(name).parts
        if not parts or PurePosixPath(name).is_absolute() or '\\' in name or any(p.startswith('.') or p in {'data','goias','node_modules'} for p in parts):
            raise ValueError('unsafe_path')
        path=artifact/'files'/name
        if path.is_symlink() or not str(path.resolve()).startswith(str((artifact/'files').resolve()) + os.sep):
            raise ValueError('unsafe_path')
        value=path.read_bytes()
        if len(value)!=entry['size'] or sha(value)!=entry['sha256']:
            raise ValueError('artifact_integrity_error')
        contents[name]=value
    if component=='control' and set(contents)!={'election-ftp-control.php','tools/ftp-publication.php','tools/prepare-ftp-baseline.php'}:
        raise ValueError('invalid_control_artifact')
    if component=='portal' and ('index.html' not in contents or any(PurePosixPath(p).suffix not in {'.html','.css','.js','.svg','.png','.ico'} for p in contents)):
        raise ValueError('invalid_portal_artifact')
    public_root=public_root.resolve()
    if output.resolve()==public_root or str(output.resolve()).startswith(str(public_root)+os.sep):
        raise ValueError('private_output_required')
    if output.exists(): raise ValueError('output_exists')
    output.mkdir(parents=True)
    operations=[]
    for name,value in contents.items():
        # Private offline tools are never installed into public_html/api.
        if component=='control' and name.startswith('tools/'):
            continue
        if component=='portal':
            if name.endswith('.html'):
                text=value.decode('utf-8')
                def reference(match):
                    attr,url=match.group(1),match.group(2)
                    normalized=url[2:] if url.startswith('./') else url
                    file=normalized.split('?',1)[0]
                    if file in contents:
                        url='/eleicoes/releases/'+expected_id+'/'+normalized
                    elif file.startswith('goias/'):
                        url='/eleicoes/'+normalized
                    return attr+'="'+url+'"'
                value=re.sub(r'(src|href)="([^"#]+)"',reference,text).encode('utf-8')
            target=public_root/'eleicoes/releases'/expected_id/name
        else:
            target=public_root/'api'/name
        if target.is_symlink(): raise ValueError('unsafe_target')
        if component=='portal' and target.exists() and (not target.is_file() or sha(target.read_bytes())!=sha(value)):
            raise ValueError('immutable_code_conflict')
        generated=output/'files'/name; generated.parent.mkdir(parents=True,exist_ok=True); generated.write_bytes(value)
        operations.append({'role':'immutable_asset' if component=='portal' else 'entrypoint',
                           'source':'files/'+name,'target':str(target),'sha256':sha(value),
                           'previous_sha256':sha(target.read_bytes()) if target.is_file() else None})
    if component=='portal':
        # HTML entrypoints switch last; every referenced asset is pinned to the
        # immutable artifact ID. Existing root assets and Goiás remain intact.
        for name in ['index.html','composition.html']:
            if name not in contents: continue
            target=public_root/'eleicoes'/name
            operations.append({'role':'entrypoint','source':'files/'+name,'target':str(target),
                'sha256':sha((output/'files'/name).read_bytes()),
                'previous_sha256':sha(target.read_bytes()) if target.is_file() else None})
    plan={'schema_version':1,'component':component,'approved_artifact_id':expected_id,
          'operations':operations,'activation':'supervised_same_filesystem_file_rename',
          'backup':'private_backup_of_each_existing_entrypoint_required'}
    (output/'activation-plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    return plan


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--artifact',type=Path,required=True)
    parser.add_argument('--expected-id',required=True)
    parser.add_argument('--public-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        result=prepare(args.artifact,args.expected_id,args.public_root,args.output)
        print(json.dumps({'status':'plan_prepared','component':result['component'],'artifact_id':result['approved_artifact_id']}))
    except Exception as error:
        print(json.dumps({'status':'failed','error_type':type(error).__name__})); raise SystemExit(1)
