"""Behavioral tests of immutable readers and transactional visual refresh."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "web/public/eleicoes/portal-bridge.js"


def node(body):
    script = "const assert=require('node:assert/strict');const bridge=require(" + json.dumps(str(MODULE)) + ");\n" + r'''
const sid='a'.repeat(64),row={scope:'br',office:1,path:'br/president.json',round:2,election_code:6260,tse_idg:1,captured_at:'source'};
const payload={environment:'oficial',election:{round:2,code:6260},scope:{code:'br'},office:{code:1},
 snapshot:{tse_idg:1,captured_at:'source',sections:{totalized:0}},candidate_count:1,
 candidates:[{tse_candidate_seq:123,ballot_number:13,votes:0,vote_percentage:0}]};
const context={round:2,version:{snapshot_id:sid,generated_at:'source'},dataBase:'/data/turnos/2/releases/'+sid,
 manifest:{environment:'oficial',results:[row]},result:null};
''' + "\n(async()=>{\n" + body + "\n})().catch(e=>{console.error(e);process.exitCode=1;});"
    subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)


def test_snapshot_identity_and_round_are_required():
    node(r'''
assert.equal(bridge.validateResult(payload,row,2,'oficial'),payload);
const wrongRound=structuredClone(payload);wrongRound.election.round=1;
assert.throws(()=>bridge.validateResult(wrongRound,row,2,'oficial'),/identity/);
const stale=structuredClone(payload);stale.snapshot.tse_idg=2;
assert.throws(()=>bridge.validateResult(stale,row,2,'oficial'),/snapshot/);
const wrongOffice=structuredClone(payload);wrongOffice.office.code=3;
assert.throws(()=>bridge.validateResult(wrongOffice,row,2,'oficial'),/identity/);
const wrongCount=structuredClone(payload);wrongCount.candidate_count=2;
assert.throws(()=>bridge.validateResult(wrongCount,row,2,'oficial'),/identity/);
''')


def test_pin_cache_invalidation_and_missing_scope_never_fall_back():
    node(r'''
const urls=[];
const read=bridge.createReader(()=>context,async url=>{urls.push(url);return {ok:true,json:async()=>payload};});
await Promise.all([read('br'),read('br')]);
assert.equal(urls.length,1);
assert.equal(urls[0],'/data/turnos/2/releases/'+sid+'/br/president.json');
assert.equal(await read('zz'),null);assert.equal(urls.length,1);
context.version={snapshot_id:'b'.repeat(64)};context.dataBase='/data/turnos/2/releases/'+'b'.repeat(64);
await read('br');assert.equal(urls.length,2);assert(urls.every(url=>url.startsWith('/data/turnos/2/')));
''')


def test_failed_request_is_not_cached_as_success():
    node(r'''
let attempts=0;
const read=bridge.createReader(()=>context,async()=>{attempts++;if(attempts===1)return {ok:false,status:503};return {ok:true,json:async()=>payload};});
await assert.rejects(read('br'),/result_http_503/);
assert.equal(await read('br'),payload);assert.equal(attempts,2);
''')


def test_abort_and_invalid_manifest_paths_are_rejected():
    node(r'''
const controller=new AbortController();controller.abort();let requests=0;
const read=bridge.createReader(()=>context,async()=>{requests++;throw Error('unexpected network');});
await assert.rejects(read('br',1,{signal:controller.signal}),e=>e.name==='AbortError');assert.equal(requests,0);
assert.throws(()=>bridge.validateManifest({environment:'oficial',results:[{...row,path:'../private.json'}]},2),/inventory/);
assert.throws(()=>bridge.validateManifest({environment:'oficial',results:[row,{...row,round:1}]},2),/inventory/);
assert.throws(()=>bridge.baseFor({environment:'oficial',round:2,snapshot_id:'../private'},2),/marker/);
assert.equal(bridge.baseFor({environment:'oficial',round:2,snapshot_id:sid},2),context.dataBase);
''')


def test_null_values_are_distinct_from_zero_and_csv_is_safe():
    node(r'''
const missing=structuredClone(payload);missing.candidates[0].votes=null;missing.candidates[0].vote_percentage=null;
assert.equal(bridge.validateResult(missing,row,2,'oficial').candidates[0].votes,null);
assert.equal(bridge.csvCell(null),'""');assert.equal(bridge.csvCell(0),'"0"');
assert.equal(bridge.csvCell('=1+1'),'"\'=1+1"');
const bad=structuredClone(payload);bad.candidates[0].vote_percentage=101;
assert.throws(()=>bridge.validateResult(bad,row,2,'oficial'),/candidate/);
''')


def test_failed_visual_refresh_keeps_previous_complete_publication():
    source = (ROOT / "web/public/eleicoes/app.js").read_text()
    source = source[:source.index('document.getElementById(\n    "scope-select"')]
    script = r'''
const assert=require('node:assert/strict'),vm=require('node:vm');
const old={environment:'oficial',results:[{scope:'br',office:1,round:1,path:'br/president.json'}]};
const next={environment:'oficial',results:[{scope:'br',office:1,round:1,path:'br/president.json'}]};
const oldMarker={environment:'oficial',generated_at:'old',snapshot_id:'a'.repeat(64)};
const nextMarker={environment:'oficial',generated_at:'new',snapshot_id:'b'.repeat(64)};
let favoritesCalls=0;
const c={URL,URLSearchParams,console:{error:()=>{}},window:{location:{search:'?turno=1',href:'https://afgnet.com.br/eleicoes/'},
 Favorites:{setManifest:()=>favoritesCalls++}},document:{getElementById:()=>({setAttribute:()=>{},replaceChildren:()=>{}}),
 createElement:()=>({addEventListener:()=>{}})},
 old,next,oldMarker,nextMarker,fetch:async()=>({ok:true,json:async()=>nextMarker})};
vm.createContext(c);vm.runInContext(SOURCE,c);
vm.runInContext(`manifest=old;portalMarker=oldMarker;activeDataBase='/data/releases/'+oldMarker.snapshot_id;
 publishedVersion=publicationToken(oldMarker);selectedScope='br';selectedOffice=1;currentResult={identity:'old'};
 loadManifest=async()=>{manifest=next;};loadAlerts=async()=>{alerts=[{identity:'new'}];};
 renderElectedByState=()=>{};renderScopeSelector=()=>{};renderOfficeTabs=()=>{};
 loadSelectedResult=async()=>{throw Error('source failed');};`,c);
(async()=>{
 await vm.runInContext('refreshIfChanged()',c);
 assert.equal(vm.runInContext('manifest',c),old);
 assert.equal(vm.runInContext('portalMarker',c),oldMarker);
 assert.equal(vm.runInContext('activeDataBase',c),'/data/releases/'+oldMarker.snapshot_id);
 assert.equal(vm.runInContext('currentResult.identity',c),'old');
 assert.equal(vm.runInContext('publishedVersion',c),['oficial','old',oldMarker.snapshot_id,''].join(':'));
 assert.equal(vm.runInContext('portalRefreshPending',c),false);assert.equal(favoritesCalls,0);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''.replace("SOURCE", json.dumps(source))
    subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
