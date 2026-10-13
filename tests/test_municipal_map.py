import shutil,subprocess
from pathlib import Path
import pytest

@pytest.mark.skipif(shutil.which('node') is None,reason='Node required')
def test_municipal_pure_zoom_and_path_bounds():
    root=Path(__file__).resolve().parents[1]
    script="""const assert=require('node:assert/strict'),F=require('./web/public/eleicoes/municipal-map.js');
const c={scale:2,x:-100,y:50},p={x:500,y:350},n=F.zoom(c,p,1.4);
assert.ok(Math.abs((p.x-c.x)/c.scale-(p.x-n.x)/n.scale)<1e-9);
assert.ok(Math.abs((p.y-c.y)/c.scale-(p.y-n.y)/n.scale)<1e-9);
assert.equal(F.zoom(c,p,100).scale,40);assert.equal(F.zoom(c,p,.001).scale,.8);
assert.equal(F.normalize('GOIÂNIA'),'goiania');
const found=F.searchRows([{ibge_code:'1',name:'APARECIDA DE GOIÂNIA',uf:'go'},{ibge_code:'2',name:'ARAGOIÂNIA',uf:'go'},{ibge_code:'3',name:'GOIÂNIA',uf:'go'}],'goiania');
assert.equal(found.length,3);assert.equal(found[0].ibge_code,'3');
assert.equal(F.searchRows([{ibge_code:'1',name:'Mesmo nome',uf:'go'},{ibge_code:'2',name:'Mesmo nome',uf:'mg'}],'Mesmo nome').length,2);
for(const path of ['../data/version.json','turnos/1/../../version.json','https://evil.test/file.json','turnos/3/version.json'])assert.equal(F.validPath(path),false);
assert.equal(F.validPath('turnos/1/version.json'),true);
"""
    r=subprocess.run(['node'],cwd=root,input=script,text=True,capture_output=True,timeout=30)
    assert r.returncode==0,r.stdout+r.stderr

@pytest.mark.skipif(shutil.which('node') is None,reason='Node required')
def test_reader_checks_hashes_pinned_pointer_and_turn_isolation(tmp_path):
    import json
    from collector.src.election_release import canonical
    from collector.src.municipal_release import assemble,verify
    from tests.municipal_fixtures import make_dataset,make_geometry
    data=make_dataset();make_geometry(data,tmp_path/'geometry');marker=assemble(data,tmp_path/'geometry',tmp_path/'package')
    _,values=verify(tmp_path/'package');values['turnos/1/version.json']=canonical(marker)
    path=tmp_path/'reader.json';path.write_text(json.dumps({k:v.decode() for k,v in values.items()}))
    root=Path(__file__).resolve().parents[1]
    script="""const assert=require('node:assert/strict'),fs=require('node:fs'),F=require('./web/public/eleicoes/municipal-map.js');
const original=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));
const source=files=>async url=>{const name=url.replace('/municipal-2026/','');return new Response(files[name]??'',{status:files[name]?200:404});};
(async()=>{
 const reader=new F.Reader(source(original)),context=await reader.pin(1);
 assert.equal((await reader.data(context,'go/president.json')).election.round,1);
 await assert.rejects(()=>reader.pin(2),F.Waiting);
 const tampered={...original};tampered[context.prefix+'overview.json']+='bad';
 const broken=new F.Reader(source(tampered)),pinned=await broken.pin(1);
 await assert.rejects(()=>broken.data(pinned,'overview.json'),/integrity/);
 let count=0;const changing=new F.Reader(async url=>{
  if(url.endsWith('/version.json')&&++count===2){const marker=JSON.parse(original['turnos/1/version.json']);marker.release_id='b'.repeat(64);return new Response(JSON.stringify(marker));}
  return source(original)(url);
 });
 await assert.rejects(()=>changing.pin(1),/activation_changed/);
})();
"""
    r=subprocess.run(['node','-e',script,str(path)],cwd=root,text=True,capture_output=True,timeout=30)
    assert r.returncode==0,r.stdout+r.stderr
