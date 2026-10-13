"""Content-addressed municipality packages, coverage and exact geometry joins."""
from pathlib import Path
import re

from .election_release import canonical, digest, parse
from .municipal_collection import UF_CODES


def assemble(dataset, geometry_directory, output):
    if dataset.get('schema') != 1 or dataset.get('environment') != 'oficial' or dataset['election']['year'] != 2026 or dataset['election']['round'] not in (1,2):
        raise ValueError('municipal_invalid_dataset')
    municipalities = dataset['municipalities']
    if len({m['ibge_code'] for m in municipalities}) != len(municipalities): raise ValueError('municipal_duplicate_inventory')
    scopes = sorted(dataset['coverage'])
    complete = set(scopes) == set(UF_CODES)
    for uf in scopes:
        rows=[m for m in municipalities if m['uf']==uf]
        report=dataset['coverage'][uf]
        if report['expected']!=len(rows) or report['processed']!=len(rows) or report['pending'] or report['failed'] or report['coverage_percentage']!=100:
            raise ValueError('municipal_incomplete_partition')
        if any(m['election']!=dataset['election'] or m['office']!=1 for m in rows): raise ValueError('municipal_mixed_election')
    geometry=Path(geometry_directory)
    geo_report=parse((geometry/'geometry-report.json').read_bytes())
    geo_id=digest(canonical(geo_report))
    geo_files={}; values={}
    for uf in scopes:
        expected={m['ibge_code'] for m in municipalities if m['uf']==uf}
        for level in ['national','detail']:
            name=uf+'-'+level+'.json';raw=(geometry/name).read_bytes();entry=geo_report['files'][name]
            if len(raw)!=entry['size'] or digest(raw)!=entry['sha256']: raise ValueError('municipal_geometry_hash_mismatch')
            features=parse(raw)['features']
            codes=[f['properties']['ibge_code'] for f in features]
            if len(codes)!=len(set(codes)) or set(codes)!=expected or any(f['properties']['uf']!=uf for f in features):
                raise ValueError('municipal_geometry_join_mismatch')
            path='geography/'+geo_id+'/'+name
            values[path]=raw
            geo_files[uf+'-'+level]={'path':path,'sha256':digest(raw),'size':len(raw)}
    ordinary={
        'catalog.json':{'schema':1,'election':dataset['election'],'candidates':dataset['catalog']},
        'overview.json':{'schema':1,'election':dataset['election'],'municipalities':[{k:v for k,v in m.items() if k not in {'candidates','source_sha256','captured_at','electorate','source_url','election','office'}} for m in municipalities]},
        'coverage.json':{'schema':1,'election':dataset['election'],'national_complete':complete,'municipalities':len(municipalities),'ufs':dataset['coverage'],'exterior_included':False,'sources':dataset['sources']}}
    for uf in scopes:
        ordinary[uf+'/president.json']={'schema':1,'election':dataset['election'],'uf':uf,'municipalities':[m for m in municipalities if m['uf']==uf],'state':dataset['states'][uf]}
    seed={'schema':1,'election':dataset['election'],'geometry_id':geo_id,'files':{k:digest(canonical(v)) for k,v in ordinary.items()}}
    sid=digest(canonical(seed))
    files={}
    for name,value in ordinary.items():
        raw=canonical({**value,'release_id':sid})
        values['turnos/'+str(dataset['election']['round'])+'/releases/'+sid+'/'+name]=raw
        files[name]={'size':len(raw),'sha256':digest(raw)}
    manifest={'schema':1,'environment':'oficial','election':dataset['election'],'release_id':sid,'seed':seed,'files':files,
              'geometry_id':geo_id,'geometry':geo_files,'coverage_complete':complete,'municipalities':len(municipalities),
              'ufs':scopes,'exterior_included':False,'geometry_year':2025}
    raw=canonical(manifest)
    values['turnos/'+str(dataset['election']['round'])+'/releases/'+sid+'/manifest.json']=raw
    root=Path(output)
    if root.exists(): raise ValueError('municipal_output_already_exists')
    root.mkdir(parents=True)
    for name,body in values.items():
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body)
    marker={'schema':1,'environment':'oficial','year':2026,'round':dataset['election']['round'],'election_code':dataset['election']['code'],
            'release_id':sid,'manifest_sha256':digest(raw),'manifest_size':len(raw),'municipalities':len(municipalities),'coverage_complete':complete}
    (root/'package.json').write_bytes(canonical({'marker':marker,'manifest':manifest}))
    verify(root, require_complete=False)
    return marker


def safe_name(name):
    return name in {'catalog.json','overview.json','coverage.json'} or bool(re.fullmatch('('+'|'.join(UF_CODES)+')/president.json',name))


def verify(directory, require_complete=True):
    root=Path(directory)
    if root.is_symlink(): raise ValueError('municipal_unsafe_package')
    package=parse((root/'package.json').read_bytes());marker=package['marker'];m=package['manifest']
    sid=m['release_id'];round_number=m['election']['round']
    if not re.fullmatch('[a-f0-9]{64}',sid) or sid!=digest(canonical(m['seed'])) or marker['release_id']!=sid or round_number not in (1,2) or m['election']['year']!=2026 or m['environment']!='oficial':
        raise ValueError('municipal_invalid_release_identity')
    if require_complete and (not m['coverage_complete'] or set(m['ufs'])!=set(UF_CODES)): raise ValueError('municipal_incomplete_national_release')
    prefix='turnos/'+str(round_number)+'/releases/'+sid+'/'
    values={}
    for name,entry in m['files'].items():
        if not safe_name(name): raise ValueError('municipal_unsafe_file')
        path=prefix+name;file=root/path
        if file.is_symlink(): raise ValueError('municipal_unsafe_package')
        raw=file.read_bytes()
        if digest(raw)!=entry['sha256'] or len(raw)!=entry['size']: raise ValueError('municipal_package_hash_mismatch')
        value=parse(raw)
        if value.pop('release_id')!=sid or value['election']!=m['election'] or digest(canonical(value))!=m['seed']['files'][name]:
            raise ValueError('municipal_release_content_mismatch')
        values[path]=raw
    for entry in m['geometry'].values():
        path=entry['path']
        if not re.fullmatch(r'geography/[a-f0-9]{64}/[a-z]{2}-(national|detail)\.json',path): raise ValueError('municipal_unsafe_geometry')
        file=root/path
        if file.is_symlink(): raise ValueError('municipal_unsafe_package')
        raw=file.read_bytes()
        if digest(raw)!=entry['sha256'] or len(raw)!=entry['size']: raise ValueError('municipal_geometry_hash_mismatch')
        values[path]=raw
    raw=(root/(prefix+'manifest.json')).read_bytes()
    if raw!=canonical(m) or marker['manifest_sha256']!=digest(raw) or marker['manifest_size']!=len(raw): raise ValueError('municipal_manifest_mismatch')
    values[prefix+'manifest.json']=raw
    expected=set(values)|{'package.json'}
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual!=expected: raise ValueError('municipal_unexpected_package_file')
    return package, values


if __name__=='__main__':
    import argparse,json
    p=argparse.ArgumentParser();p.add_argument('--dataset',type=Path,required=True);p.add_argument('--geometry',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(assemble(parse(a.dataset.read_bytes()),a.geometry,a.output)),flush=True)
