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
const context = {URLSearchParams,window:{}, document:{}, console, localStorage:{getItem:()=>null}, fetch:async(url)=>{
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


@pytest.mark.parametrize('round_number',[1,2])
def test_favorites_refresh_stays_in_the_selected_round(round_number):
    source=(Path(__file__).resolve().parents[1]/'web/public/eleicoes/favorites.js').read_text()
    source=source.replace('    init();','    window.harness = {loadVersion, refreshManifest, loadFavoriteData};')
    script=r'''
const vm=require('node:vm'),assert=require('node:assert/strict'),urls=[];
const round=ROUND,root=round===2?'/data/turnos/2':'/data',id='a'.repeat(64);
const version={environment:'oficial',round,snapshot_id:id,generated_at:'2026-10-12T12:00:00Z'};
const item={scope:'ac',office:3,path:'ac/governor.json',election_code:6260,round,tse_idg:'1',captured_at:'same'};
let mixed=false;
const context={URLSearchParams,window:{location:{search:'?turno='+round}},document:{},console,
 localStorage:{getItem:()=>null},fetch:async url=>{urls.push(url);return {ok:true,json:async()=>
 url.endsWith('version.json')?version:url.endsWith('manifest.json')?
 {environment:'oficial',results:[{...item,round:mixed?1:round}]}:
 {candidates:[],snapshot:{tse_idg:'1',captured_at:'same'}}};}};
vm.createContext(context);vm.runInContext(SOURCE,context);
(async()=>{
 const h=context.window.harness;await h.refreshManifest(await h.loadVersion());
 await h.loadFavoriteData({scope:'ac',office:3,election_code:6260,round,tse_candidate_seq:'missing'});
 assert.deepEqual(urls,[root+'/version.json',root+'/releases/'+id+'/manifest.json',root+'/releases/'+id+'/ac/governor.json']);
 if(round===2){mixed=true;await assert.rejects(h.refreshManifest(version),/second_round_not_official/);}
})().catch(e=>{console.error(e);process.exitCode=1;});
'''.replace('ROUND',str(round_number)).replace('SOURCE',json.dumps(source))
    subprocess.run([shutil.which('node'),'-e',script],check=True,capture_output=True,text=True)


def test_candidate_and_favorite_cards_show_waiting_before_round_two_count():
    root=Path(__file__).resolve().parents[1]/'web/public/eleicoes'
    app=(root/'app.js').read_text();app=app[:app.index('document.getElementById(\n    "scope-select"')]
    favorites=(root/'favorites.js').read_text().replace('    init();','    window.favoriteHarness = {createCard};')
    script=r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
class Element{
 constructor(){this.children=[];this.style={};this.classList={add:()=>{},remove:()=>{}};}
 append(...nodes){this.children.push(...nodes);}appendChild(node){this.children.push(node);}
 setAttribute(){}addEventListener(){}
 set textContent(value){this.text=String(value);}get textContent(){return (this.text||'')+this.children.map(n=>n.textContent).join(' ');}
 set innerHTML(value){this.text=value.replace(/<[^>]*>/g,'');}
}
const context={URLSearchParams,console,window:{location:{search:'?turno=2'},Favorites:{isFavorite:()=>false}},
 document:{createElement:()=>new Element()},localStorage:{getItem:()=>null}};
vm.createContext(context);vm.runInContext(APP,context);vm.runInContext(FAVORITES,context);
const candidate={tse_candidate_seq:1,ballot_name:'Candidatura oficial',name:'Nome oficial',ballot_number:13,
 party_acronym:'PTST',votes:0,vote_percentage:0,result_status:'',elected:false};
const result={election:{round:2},office:{name:'Governador'},scope:{code:'ac'},
 snapshot:{sections:{totalized:0,percentage:0},captured_at:'2026-10-12T12:00:00Z'},candidate_count:1,candidates:[candidate]};
context.result=result;context.candidate=candidate;
vm.runInContext(`selectedScope='ac';selectedOffice=3;currentResult=result;`,context);
let card=vm.runInContext('renderCandidateCard(candidate,1,true)',context);
assert(card.textContent.includes('Candidatura oficial'));assert(card.textContent.includes('Aguardando apuração'));
assert(!card.textContent.includes('0%'));assert(!card.textContent.includes('0 votos'));
const favorite={scope:'ac',scope_name:'Acre',office:3,office_name:'Governador'};
let favoriteCard=context.window.favoriteHarness.createCard({favorite,candidate,result,synced:true});
assert(favoriteCard.textContent.includes('Aguardando apuração'));assert(!favoriteCard.textContent.includes('0%'));
result.snapshot.sections.totalized=1;candidate.votes=123;candidate.vote_percentage=50;
card=vm.runInContext('renderCandidateCard(candidate,1,true)',context);
assert(card.textContent.includes('123'));assert(card.textContent.includes('50,00%'));
assert(!card.textContent.includes('Aguardando apuração'));
'''.replace('APP',json.dumps(app)).replace('FAVORITES',json.dumps(favorites))
    subprocess.run([shutil.which('node'),'-e',script],check=True,capture_output=True,text=True)
