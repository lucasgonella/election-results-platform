"""Derive two bounded polygon resolutions from the official IBGE 2025 mesh."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
import shutil

import shapefile
import shapely
from shapely.geometry import shape, mapping

SOURCE = 'https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2025/Brasil/BR_Municipios_2025.zip'


def build(archive, inventory, output):
    expected = {m['ibge_code']: m for m in inventory}
    # IBGE also includes unincorporated areas. Only exact TSE/IBGE matches enter.
    with zipfile.ZipFile(archive) as z:
        if z.testzip(): raise ValueError('municipal_corrupt_geometry_archive')
        source = Path(output).parent / 'ibge-shape'; source.mkdir(exist_ok=True)
        for ext in ['shp','shx','dbf']:
            name='BR_Municipios_2025.'+ext
            if not (source/name).exists():
                with z.open(name) as src,(source/name).open('wb') as dst: shutil.copyfileobj(src,dst,1024*1024)
        reader = shapefile.Reader(str(source/'BR_Municipios_2025.shp'), encoding='utf-8')
        states, seen = {}, set()
        for item in reader.iterShapeRecords():
            record = item.record.as_dict(); code = record['CD_MUN']
            if code not in expected: continue
            if code in seen or record['SIGLA_UF'].lower() != expected[code]['uf']:
                raise ValueError('municipal_geometry_identity_mismatch')
            seen.add(code)
            geometry = shape(item.shape.__geo_interface__)
            if geometry.is_empty or not geometry.is_valid or geometry.geom_type not in ('Polygon','MultiPolygon'):
                raise ValueError('municipal_invalid_official_geometry')
            m=expected[code]
            for level,tolerance in [('national',.012),('detail',.001)]:
                g=geometry.simplify(tolerance,preserve_topology=True)
                if g.is_empty or not g.is_valid: raise ValueError('municipal_simplification_lost_polygon')
                feature={'type':'Feature','properties':{'ibge_code':code,'name':m['name'],'uf':m['uf']},'geometry':mapping(g)}
                states.setdefault((m['uf'],level),[]).append(feature)
    if seen != set(expected): raise ValueError('municipal_geometry_coverage_mismatch')
    # The source passes individual polygon validity, but does not pass GEOS's
    # stricter global edge-matched coverage check. Do not snap/repair borders or
    # invent missing areas: simplify each original polygon preserving topology.
    out = Path(output); out.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(Path(archive).read_bytes()).hexdigest()
    report = {'source_url':SOURCE,'source_sha256':source_hash,'year':2025,'municipalities':len(seen),'simplification':'per_polygon_topology_preserving','tolerance_degrees':{'national':.012,'detail':.001},'files':{}}
    for (uf,level),features in states.items():
        value={'type':'FeatureCollection','schema':1,'uf':uf,'level':level,'year':2025,'source_url':SOURCE,'source_sha256':source_hash,'features':sorted(features,key=lambda f:f['properties']['ibge_code'])}
        raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        name=uf+'-'+level+'.json'; (out/name).write_bytes(raw)
        report['files'][name]={'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'municipalities':len(features)}
    (out/'geometry-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'geometries':len(seen),'files':len(report['files']),'national_bytes':sum(v['size'] for k,v in report['files'].items() if '-national' in k),'detail_bytes':sum(v['size'] for k,v in report['files'].items() if '-detail' in k)}),flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--inventory',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    # EA12 proof comes directly from the configured election.
    ea12=json.loads(a.inventory.read_text())
    items=[{'ibge_code':m['cdi'],'name':m['nm'],'uf':uf['cd']} for uf in ea12['abr'] if uf['cd']!='zz' for m in uf['mu']]
    build(a.archive,items,a.output)
