"""Execute the actual favorites reader in a minimal browser harness."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest


def test_favorites_pins_manifest_and_result_to_one_release():
    node=shutil.which('node')
    if not node: pytest.fail('Node required for FTP frontend contract tests')
    source=(Path(__file__).resolve().parents[1]/'web/public/eleicoes/favorites.js').read_text(encoding='utf-8')
    # Expose internal reader functions, preserving their implementation unchanged.
    source=source.replace('    init();','    window.harness = {refreshManifest, loadFavoriteData, publicationToken};')
    script=r'''
const vm = require('node:vm');
const assert = require('node:assert/strict');
const urls = [];
const id = 'a'.repeat(64);
const version = {environment:'fixture', generated_at:'same', snapshot_id:id, activation_revision:'1'};
const item = {scope:'ac', office:1, path:'ac/president.json', election_code:1, round:1, tse_idg:'1', captured_at:'same'};
const context = {window:{}, document:{}, console, localStorage:{getItem:()=>null}, fetch:async(url)=>{
  urls.push(url);
  return {ok:true,json:async()=>url.endsWith('manifest.json')?{results:[item]}:
    {candidates:[], snapshot:{tse_idg:'1', captured_at:'same'}}};
}};
vm.createContext(context);
vm.runInContext(SOURCE,context);
(async()=>{
  const harness=context.window.harness;
  await harness.refreshManifest(version);
  await harness.loadFavoriteData({scope:'ac',office:1,election_code:1,round:1,tse_candidate_seq:'missing'});
  assert.deepEqual(urls,[`/data/releases/${id}/manifest.json`,`/data/releases/${id}/ac/president.json`]);
  assert.notEqual(harness.publicationToken(version),harness.publicationToken({...version,activation_revision:'2'}));
  assert.notEqual(harness.publicationToken(version),harness.publicationToken({...version,snapshot_id:'b'.repeat(64)}));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''.replace('SOURCE',json.dumps(source))
    subprocess.run([node,'-e',script],check=True,capture_output=True,text=True)


def test_round_two_waiting_page_retries_until_official_activation():
    node=shutil.which('node')
    assert node, 'Node required'
    source=(Path(__file__).resolve().parents[1]/'web/public/eleicoes/app.js').read_text()
    # Run actual initialize/loadVersion/loadManifest, stub DOM rendering only.
    source=source[:source.index('document.getElementById(\n    "scope-select"')]
    script=r'''
const vm=require('node:vm'), assert=require('node:assert/strict');
const timers=new Map(), urls=[], elements=new Map(), classes=new Set();
let available=false, timerId=0;
const sid='a'.repeat(64);
const row={round:2,scope:'ac',office:3,path:'ac/governor.json'};
const context={URLSearchParams,window:{location:{search:'?turno=2'},Favorites:{setManifest:()=>{}}},
 document:{body:{classList:{add:c=>classes.add(c),remove:c=>classes.delete(c)}},
 getElementById:id=>{if(!elements.has(id))elements.set(id,{hidden:true,setAttribute:()=>{}});return elements.get(id);}},
 console,setInterval:fn=>{timers.set(++timerId,fn);return timerId;},clearInterval:id=>timers.delete(id),
 fetch:async url=>{urls.push(url);return {ok:available,json:async()=>url.endsWith('version.json')?
 {environment:'oficial',round:2,snapshot_id:sid,generated_at:'2026-10-25T12:00:00Z'}:{environment:'oficial',results:[row]}};}};
vm.createContext(context);vm.runInContext(SOURCE,context);
vm.runInContext(`loadAlerts=async()=>{};selectInitialRoute=()=>{};renderEnvironment=()=>{};
 renderElectedByState=()=>{};renderScopeSelector=()=>{};renderOfficeTabs=()=>{};updateUrl=()=>{};
 loadSelectedResult=async()=>{};currentManifestItem=()=>({});`,context);
(async()=>{
 await vm.runInContext('initialize()',context);
 assert(classes.has('round-two-unavailable'));
 assert.equal(timers.size,1);
 available=true;await [...timers.values()][0]();
 assert(!classes.has('round-two-unavailable'));
 assert.equal(elements.get('round-unavailable').hidden,true);
 assert.equal(timers.size,1); // replaces waiting interval with the regular refresh
 assert(urls.every(url=>url.startsWith('/data/turnos/2/')));
 assert.equal(vm.runInContext('activeDataBase',context),`/data/turnos/2/releases/${sid}`);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''.replace('SOURCE',json.dumps(source))
    subprocess.run([node,'-e',script],check=True,capture_output=True,text=True)
