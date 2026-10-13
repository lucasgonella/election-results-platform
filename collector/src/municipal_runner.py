"""Main-only workflow producer, persistent cache and exact official geometry."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import requests

from deploy.frontend import error_report
from .municipal_collection import HTTP,collect,Unavailable,Throttled
from .municipal_release import assemble
from .second_round_publish import save


def run(round_number,state,output):
    from tools.municipal_geometry import build,SOURCE
    state=Path(state);state.mkdir(parents=True,exist_ok=True)
    if output.exists():raise ValueError('municipal_output_already_exists')
    data=collect(HTTP(state/'http-cache'/str(round_number)),round_number,progress=lambda v:print(json.dumps(v),flush=True))
    save(state/('round-'+str(round_number)+'-latest.json'),data)
    archive=state/'BR_Municipios_2025.zip'
    if not archive.exists():
        temporary=state/'BR_Municipios_2025.zip.download'
        response=requests.get(SOURCE,stream=True,timeout=(20,90),allow_redirects=False)
        if response.status_code!=200:raise ValueError('municipal_geometry_download_failed')
        length=0
        with temporary.open('wb') as stream:
            for chunk in response.iter_content(1024*1024):
                length+=len(chunk)
                if length>400*1024*1024:raise ValueError('municipal_geometry_archive_too_large')
                stream.write(chunk)
        temporary.replace(archive)
    geometry=state/'geometry'
    if not (geometry/'geometry-report.json').exists():build(archive,data['municipalities'],geometry)
    return assemble(data,geometry,output)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--round',type=int,choices=[1,2],required=True);p.add_argument('--state',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    try:print(json.dumps({'status':'ready','marker':run(a.round,a.state,a.output)}),flush=True)
    except (Unavailable,Throttled) as error:
        print(json.dumps({'status':'awaiting_official_municipal_data' if isinstance(error,Unavailable) else 'source_rate_limited','round':a.round,**error_report(error)}),flush=True)
    except Exception as error:
        print(json.dumps({'status':'failed','round':a.round,**error_report(error)}),flush=True)
        raise SystemExit(1)
