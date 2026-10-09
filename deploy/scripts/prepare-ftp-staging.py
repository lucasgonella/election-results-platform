"""Build a NEW local synthetic test namespace. No network or activation.

Uses the same 137-target fixtures as the publication tests (dev dependencies).
Future remote installation/writes require separate authorization.
"""
import argparse
import json
from pathlib import Path
import secrets
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'))
from test_ftp_publication import dataset


def prepare(output):
    output=Path(output)
    if not output.name.startswith('ftp-staging-') or output.exists() or output.is_symlink():
        raise ValueError('new_fixture_namespace_required')
    output.mkdir(parents=True)
    for name in ['private','public','inbox','spool']:
        (output/name).mkdir(mode=0o700 if name!='public' else 0o755)
    dataset(output/'fixtures/full')
    dataset(output/'fixtures/delta',2,True)
    shutil.copyfile(ROOT/'deploy/locaweb/ftp-publication.php',output/'private/ftp-publication.php')
    shutil.copyfile(ROOT/'deploy/locaweb/ftp-staging-probe.php',output/'public/probe.php')
    # This is a disposable fixture key, never a copy of the production key.
    config={'fixture_only':True,'environment':'fixture','root':str(output.resolve()),'fixture_key':secrets.token_hex(32)}
    path=output/'private/staging-config.json';path.write_text(json.dumps(config),encoding='utf-8');path.chmod(0o600)
    (output/'public/probe-marker.json').write_text('{"fixture":"replace_a"}',encoding='utf-8')
    return {'status':'fixture_prepared','targets':137}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    try: print(json.dumps(prepare(parser.parse_args().output)))
    except Exception as error: print(json.dumps({'status':'failed','error_type':type(error).__name__}));raise SystemExit(1)
