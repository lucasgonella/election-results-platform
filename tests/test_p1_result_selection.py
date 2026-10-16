"""Run the actual portal selection and consumers against deferred synthetic reads."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


WEB = Path(__file__).resolve().parents[1] / "web/public/eleicoes"


def run_portal(body, round_number=1):
    app = (WEB / "app.js").read_text(encoding="utf-8")
    app = app.replace("initialize().catch(initializationFailed);", "")
    script = r"""
const assert = require('node:assert/strict'), vm = require('node:vm');
const round = ROUND, root = round === 2 ? '/data/turnos/2' : '/data';
function deferred() { let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject}; }
class Element {
 constructor(tag='div') { this.tagName=tag;this.children=[];this.attrs={};this.events={};this.dataset={};this.value='';
  this.hidden=false;this.disabled=false;this.open=false;this.style={setProperty(k,v){this[k]=v;}};
  const classes=new Set();this.classList={add:k=>classes.add(k),remove:k=>classes.delete(k),
   toggle:(k,on)=>on?classes.add(k):classes.delete(k),contains:k=>classes.has(k)}; }
 set textContent(value) { this.text=String(value);this.children=[]; }
 get textContent() { return (this.text||'')+this.children.map(node=>node.textContent).join(' '); }
 set innerHTML(value) { this.text=String(value).replace(/<[^>]*>/g,'');this.children=[]; }
 append(...nodes) { for(const node of nodes) {node.parent=this;this.children.push(node);} }
 appendChild(node) { this.append(node);return node; }
 replaceChildren(...nodes) { this.text='';this.children=[];this.append(...nodes); }
 setAttribute(k,v) { this.attrs[k]=String(v); }
 getAttribute(k) { return this.attrs[k] ?? null; }
 removeAttribute(k) { delete this.attrs[k]; }
 addEventListener(k,fn) { (this.events[k] ||= []).push(fn); }
 dispatchEvent(event) { return Promise.all((this.events[event.type]||[]).map(fn=>fn(event))); }
 click() { return this.dispatchEvent({type:'click',target:this}); }
 closest(selector) { return selector==='.race-card' ? this.parent : null; }
 scrollIntoView() {} focus() {} showModal() {this.open=true;} close(){this.open=false;}
}
const elements=new Map(), listeners=new Map(), announcements=[], requests=[], favorites=[], timers=[];
const $=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
function descendants(node) {return node.children.flatMap(child=>[child,...descendants(child)]);}
const compareButton=new Element('button');
const document={hidden:false,body:new Element('body'),createElement:tag=>new Element(tag),getElementById:$,
 querySelector:()=>null,querySelectorAll:selector=>selector==='[data-dialog-open="compare-dialog"]'?[compareButton]:
  selector==='[data-race-candidate]'?descendants($('presidential-race')).filter(node=>node.dataset.raceCandidate):
  selector==='#results .candidate'?$('results').children:[],
 addEventListener:(type,fn)=>{if(!listeners.has(type))listeners.set(type,[]);listeners.get(type).push(fn);},
 dispatchEvent:event=>{if(event.type==='election:context')announcements.push(event.detail);
  for(const fn of listeners.get(event.type)||[])fn(event);}};
const fetch=url=>{const request={url,...deferred()};requests.push(request);return request.promise;};
const location={search:'?turno='+round,href:'https://example.test/eleicoes/?turno='+round};
const window={location,fetch,matchMedia:()=>({matches:true}),Favorites:{isFavorite:()=>false,toggle:()=>false,
 setManifest:(...args)=>favorites.push(args)}};
const c={document,window,URL,URLSearchParams,fetch,console:{error:()=>{}},
 CustomEvent:class{constructor(type,options){this.type=type;this.detail=options?.detail;}},
 history:{replaceState:(_,__,url)=>{location.href=String(url);}},setTimeout:fn=>fn(),
 setInterval:(fn,delay)=>{timers.push({fn,delay,active:true});return timers.length;},clearInterval:id=>{timers[id-1].active=false;},
 Blob:class {constructor(parts){this.parts=parts;}},navigator:{}};
vm.createContext(c);
vm.runInContext(BRIDGE,c);vm.runInContext(APP,c);
const run=source=>vm.runInContext(source,c), api=window.ElectionPortal;
const row=(scope,office)=>({scope,office,round,path:scope+'/'+(office===1?'president':'governor')+'.json',
 office_name:office===1?'Presidente':'Governador',election_code:123,tse_idg:'fixture',captured_at:'2026-10-01T10:00:00Z'});
const manifest={environment:'oficial',results:['br','ac','go'].flatMap(scope=>[row(scope,1),row(scope,3)])};
const marker={environment:'oficial',round,generated_at:'2026-10-01T10:00:00Z',snapshot_id:'a'.repeat(64)};
const nextMarker={...marker,generated_at:'2026-10-01T10:05:00Z',snapshot_id:'b'.repeat(64)};
function payload(scope='ac',office=1,name='Initial') {return {environment:'oficial',election:{round,code:123},scope:{code:scope},
 office:{code:office,name:office===1?'Presidente':'Governador'},snapshot:{tse_idg:'fixture',captured_at:marker.generated_at,
 generated_at:marker.generated_at,sections:{total:10,totalized:5,percentage:50}},candidate_count:1,
 candidates:[{tse_candidate_seq:'123',ballot_name:name,ballot_number:13,party_acronym:'TEST',votes:100,vote_percentage:50,result_status:''}]};}
c.fixtureManifest=manifest;c.fixtureMarker=marker;c.initial=payload();
run(`manifest=fixtureManifest;portalMarker=fixtureMarker;activeDataBase=dataBaseForVersion(portalMarker);
 publishedVersion=publicationToken(portalMarker);selectedScope='ac';selectedOffice=1;applySelectedResult(initial);`);
const initialContext=api.getContext();
const respond=(request,body,status=200)=>request.resolve({ok:status>=200&&status<300,status,json:async()=>body});
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
const mountPremium=()=>vm.runInContext(PREMIUM,c);
(async()=>{
BODY
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    for key, value in {
        "ROUND": str(round_number),
        "BRIDGE": json.dumps((WEB / "portal-bridge.js").read_text(encoding="utf-8")),
        "APP": json.dumps(app),
        "PREMIUM": json.dumps((WEB / "premium-controller.js").read_text(encoding="utf-8")),
        "BODY": body,
    }.items():
        script = script.replace(key, value)
    result = subprocess.run([shutil.which("node") or "node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("round_number", [1, 2])
def test_scope_and_office_changes_immediately_invalidate_every_selected_value(round_number):
    run_portal(r"""
$('results-table').textContent='Old table';$('pagination').textContent='Old pagination';
const loading=api.selectScope('go',3);
assert.equal(api.getContext().result,null);assert.equal(api.getContext().status,'loading');
assert.equal(api.getContext().scope,'go');assert.equal(api.getContext().office,3);
assert.equal(api.getCandidates().length,0);assert.equal(api.getResultPage().candidates.length,0);
assert.equal($('location-summary').textContent,'Goiás');assert.equal($('office-summary').textContent,'Governador');
assert.equal($('candidate-count-summary').textContent,'—');assert.equal($('progress-bar').style.width,'0%');
assert.equal($('sections-progress').getAttribute('aria-valuenow'),null);
assert.equal($('results-table').textContent,'');assert.equal($('pagination').textContent,'');
assert.equal($('results').getAttribute('aria-busy'),'true');assert(! $('results').textContent.includes('Initial'));
assert.equal($('download-results').disabled,true);assert.equal($('search').disabled,true);
const current=announcements.at(-1);assert.equal(current.scope,'go');assert.equal(current.office,3);assert.equal(current.result,null);
assert(requests[0].url.startsWith(root+'/releases/'));assert(requests[0].url.endsWith('/go/governor.json'));
respond(requests[0],payload('go',3,'New governor'));assert.equal(await loading,true);
assert.equal(api.getContext().result.candidates[0].ballot_name,'New governor');
assert.equal($('sections-summary').textContent,'50,00%');assert.equal($('results').getAttribute('aria-busy'),'false');
assert.equal($('download-results').disabled,false);assert.equal($('search').disabled,false);
""", round_number)


@pytest.mark.parametrize("failure", ["http", "network", "validation", "json"])
def test_current_failure_is_explicit_and_retry_uses_the_current_selection(failure):
    run_portal(r"""
const loading=api.selectScope('go',3);
const failure=FAILURE;
if(failure==='http')respond(requests[0],{},503);
if(failure==='network')requests[0].reject(new TypeError('Synthetic offline'));
if(failure==='validation')respond(requests[0],payload('ac',1,'Wrong identity'));
if(failure==='json')requests[0].resolve({ok:true,json:async()=>{throw SyntaxError('Synthetic JSON');}});
assert.equal(await loading,false);
assert.equal(api.getContext().result,null);assert.equal(api.getContext().status,'error');
assert.equal(api.getCandidates().length,0);assert.equal($('results').getAttribute('aria-busy'),'false');
assert($('results').textContent.includes('Não foi possível'));assert($('results').textContent.includes('Tentar novamente'));
assert.equal($('sections-summary').textContent,'Dados indisponíveis');
assert.equal($('download-results').disabled,true);assert.equal(announcements.at(-1).status,'error');
const retry=$('results').children[0].children[0];await retry.click();
assert.equal(api.getContext().status,'loading');assert.equal($('results').getAttribute('aria-busy'),'true');
assert.equal(requests[1].url,requests[0].url);respond(requests[1],payload('go',3,'Recovered'));await flush();
assert.equal(api.getContext().status,'ready');assert.equal(api.getContext().result.candidates[0].ballot_name,'Recovered');
""".replace("FAILURE", json.dumps(failure)))


@pytest.mark.parametrize("late_failure", [False, True])
def test_late_success_or_rejection_cannot_change_the_latest_error(late_failure):
    run_portal(r"""
const first=api.selectScope('go',1),latest=api.selectScope('ac',3);
respond(requests[1],{},503);await latest;
const lastEvent=announcements.at(-1),notice=$('results').textContent;
if(LATE_FAILURE)requests[0].reject(new TypeError('Late offline'));else respond(requests[0],payload('go',1,'Late'));
assert.equal(await first,false);assert.equal(api.getContext().scope,'ac');assert.equal(api.getContext().office,3);
assert.equal(api.getContext().status,'error');assert.equal(api.getContext().result,null);
assert.equal($('results').textContent,notice);assert.equal(announcements.at(-1),lastEvent);
assert.equal($('results').getAttribute('aria-busy'),'false');
""".replace("LATE_FAILURE", json.dumps(late_failure)))


def test_a_b_a_and_same_selection_overlaps_keep_only_the_latest_generation():
    run_portal(r"""
const a=api.selectScope('ac',1),b=api.selectScope('go',3),aAgain=api.selectScope('ac',1);
respond(requests[0],payload('ac',1,'First A'));assert.equal(await a,false);
requests[1].reject(new TypeError('Late B'));assert.equal(await b,false);
assert.equal(api.getContext().result,null);assert.equal(api.getContext().status,'loading');
assert.equal($('results').getAttribute('aria-busy'),'true');
respond(requests[2],payload('ac',1,'Latest A'));assert.equal(await aAgain,true);
const sameA=api.selectScope('ac',1),newestA=api.selectScope('ac',1);
respond(requests[4],payload('ac',1,'Newest A'));assert.equal(await newestA,true);
requests[3].reject(new TypeError('Late same selection'));assert.equal(await sameA,false);
assert.equal(api.getContext().result.candidates[0].ballot_name,'Newest A');
assert.equal(api.getCandidates()[0].ballot_name,'Newest A');
assert.equal($('results').getAttribute('aria-busy'),'false');
""")


@pytest.mark.parametrize("failure", [False, True])
def test_refresh_never_restores_a_selection_changed_during_staging(failure):
    run_portal(r"""
const refresh=run('refreshIfChanged()');assert.equal(requests.length,1);
await run('refreshIfChanged()');assert.equal(requests.length,1); // marker read is serialized
respond(requests[0],nextMarker);await flush();
assert.equal(requests.length,3);respond(requests[1],manifest);respond(requests[2],{alerts:[]});await flush();
assert.equal(requests.length,4);assert(requests[3].url.includes(nextMarker.snapshot_id));
assert.equal(api.getContext().result,initialContext.result);assert.equal(api.getContext().dataBase,initialContext.dataBase);
const selection=api.selectScope('go',3);respond(requests[4],{},503);await selection;
if(FAILURE)requests[3].reject(new TypeError('Late refresh'));else respond(requests[3],payload('ac',1,'Old selection refresh'));
await refresh;
assert.equal(api.getContext().scope,'go');assert.equal(api.getContext().office,3);
assert.equal(api.getContext().result,null);assert.equal(api.getContext().status,'error');
assert.equal($('results').getAttribute('aria-busy'),'false');
assert.equal($('publication-update-status').hidden,true);
assert.equal(api.getContext().dataBase,initialContext.dataBase);assert.equal(api.getContext().manifest,manifest);
assert.equal(run('publishedVersion'),run('publicationToken(fixtureMarker)'));
assert.equal(run('portalRefreshPending'),false);assert.equal(favorites.length,0);
""".replace("FAILURE", json.dumps(failure)))


def test_failed_refresh_keeps_complete_publication_and_success_commits_all_together():
    run_portal(r"""
let refresh=run('refreshIfChanged()');respond(requests[0],nextMarker);await flush();
respond(requests[1],manifest);respond(requests[2],{alerts:[{kind:'fixture'}]});await flush();
respond(requests[3],{},503);await refresh;
assert.equal(api.getContext().result,initialContext.result);assert.equal(api.getContext().version,marker);
assert.equal(run('portalRefreshPending'),false);assert.equal(favorites.length,0);
assert.equal($('publication-update-status').hidden,false);
assert($('publication-update-status').textContent.includes('publicação anterior'));
refresh=$('publication-update-status').children[1].click();respond(requests[4],nextMarker);await flush();
respond(requests[5],manifest);respond(requests[6],{alerts:[]});await flush();
respond(requests[7],payload('ac',1,'New publication'));await refresh;
assert.equal(api.getContext().version,nextMarker);assert.equal(api.getContext().result.candidates[0].ballot_name,'New publication');
assert(api.getContext().dataBase.endsWith(nextMarker.snapshot_id));assert.equal(favorites.length,1);
assert.equal(announcements.at(-1).version,nextMarker);assert.equal(run('portalRefreshPending'),false);
assert.equal($('publication-update-status').hidden,true);
""")


@pytest.mark.parametrize("round_number", [1, 2])
def test_polling_gate_is_scoped_for_both_rounds(round_number):
    run_portal(r"""
const calls=[];window.LiveData={paused:namespace=>{calls.push(['paused',namespace]);return false;},
 shouldPoll:(base,namespace)=>{calls.push(['poll',base,namespace]);return false;},fetch};
await run('refreshIfChanged()');assert.equal(requests.length,0);
assert.deepEqual(calls,[['paused',root],['poll',initialContext.dataBase,root]]);
""", round_number)


def test_premium_consumers_clear_table_csv_presidency_and_ignore_late_race_reads():
    run_portal(r"""
const presidential=deferred();api.loadResult=()=>presidential.promise;$('result-view').value='table';mountPremium();
assert($('results-table').textContent.includes('Initial'));
const selection=api.selectScope('go',3);
assert.equal($('results-table').textContent,'');assert.equal($('results-table').hidden,true);assert.equal($('results').hidden,false);
assert.equal($('breadcrumb-scope').textContent,'Goiás');assert.equal($('download-results').disabled,true);
assert.equal(compareButton.disabled,true);assert(! $('presidential-race').textContent.includes('Initial'));
respond(requests[0],{},503);await selection;
const notice=$('presidential-race').textContent;presidential.resolve(payload('br',1,'Late presidency'));await flush();
assert.equal($('presidential-race').textContent,notice);assert.equal($('national-presidency').textContent,'—');
assert.equal($('results-table').textContent,'');assert.equal($('download-results').disabled,true);
await $('download-results').click(); // cannot enter Blob/URL export on an invalid selection
""")


def test_comparison_stale_completion_cannot_overwrite_new_selection_or_newer_comparison():
    run_portal(r"""
api.loadResult=async()=>payload('br',1,'Presidency');
const comparisons=[];api.loadRoundResult=(number,scope)=>{const read={number,scope,...deferred()};comparisons.push(read);return read.promise;};
mountPremium();await flush();await compareButton.click();assert.equal(comparisons.length,2);
const selection=api.selectScope('go',3);
assert($('round-comparison').textContent.includes('Aguardando'));
for(const read of comparisons)read.resolve({result:payload('ac',1,'Stale comparison')});await flush();
assert(! $('round-comparison').textContent.includes('Stale comparison'));
respond(requests[0],payload('go',3,'Governor'));await selection;await flush();
await compareButton.click();await compareButton.click();assert.equal(comparisons.length,6);
comparisons[4].resolve({result:payload('go',1,'Current comparison')});comparisons[5].resolve(null);await flush();
const current=$('round-comparison').textContent;assert(current.includes('Current comparison'));assert(current.includes('Goiás'));
comparisons[2].resolve({result:payload('go',1,'Superseded comparison')});comparisons[3].reject(new TypeError('Late comparison'));
await flush();assert.equal($('round-comparison').textContent,current);
""")


def test_new_publication_invalidates_presidential_values_before_the_new_read_completes():
    run_portal(r"""
const races=[];api.loadResult=()=>{const read=deferred();races.push(read);return read.promise;};
mountPremium();races[0].resolve(payload('br',1,'Old presidential publication'));await flush();
assert($('presidential-race').textContent.includes('Old presidential publication'));
const refresh=run('refreshIfChanged()');respond(requests[0],nextMarker);await flush();
respond(requests[1],manifest);respond(requests[2],{alerts:[]});await flush();
respond(requests[3],payload('ac',1,'New local publication'));await refresh;
assert.equal(races.length,2);assert(! $('presidential-race').textContent.includes('Old presidential publication'));
assert.equal($('national-presidency').textContent,'—');
assert($('race-context').textContent.includes('Conferindo'));
races[1].resolve(payload('br',1,'New presidential publication'));await flush();
assert($('presidential-race').textContent.includes('New presidential publication'));
""")


def test_native_scope_and_office_controls_use_the_same_invalidation_and_retry():
    run_portal(r"""
const scopeChange=$('scope-select').dispatchEvent({type:'change',target:{value:'go'}});
assert.equal(api.getContext().scope,'go');assert.equal(api.getContext().result,null);
respond(requests[0],payload('go',1,'New scope'));await scopeChange;
const governor=$('office-tabs').children.find(button=>button.textContent==='Governador');
const officeChange=governor.click();assert.equal(api.getContext().office,3);assert.equal(api.getContext().result,null);
respond(requests[1],{},503);await officeChange;
assert.equal(api.getContext().status,'error');assert.equal($('results').getAttribute('aria-busy'),'false');
const notice=$('results').textContent;
await $('search').dispatchEvent({type:'input',target:{value:'old'}});
assert.equal(api.getCandidates().length,0);assert.equal($('results').textContent,notice);
""")


def test_initialization_error_has_a_working_full_publication_retry():
    run_portal(r"""
run('initializationFailed(new Error("Synthetic initialization error"))');
assert.equal(api.getContext().status,'error');assert($('results').textContent.includes('Tentar novamente'));
const retry=$('results').children[0].children[0];await retry.click();await retry.click();
assert.equal(requests.length,1);assert.equal(api.getContext().status,'loading');
assert.equal($('results').getAttribute('aria-busy'),'true');
respond(requests[0],marker);await flush();respond(requests[1],manifest);respond(requests[2],{alerts:[]});await flush();
respond(requests[3],payload('br',1,'Initialized'));await flush();
assert.equal(api.getContext().status,'ready');assert.equal(api.getContext().result.candidates[0].ballot_name,'Initialized');
assert.equal($('results').getAttribute('aria-busy'),'false');
""")


@pytest.mark.parametrize("failure", ["network", "http", "marker", "manifest404", "manifest503", "manifest_validation"])
def test_round_two_initial_failure_is_an_error_instead_of_waiting_for_absent_data(failure):
    run_portal(r"""
const initialization=run('initialize().catch(initializationFailed)'),failure=FAILURE;
if(failure==='network')requests[0].reject(new TypeError('Synthetic offline'));
else if(failure==='http')respond(requests[0],{},503);
else if(failure==='marker')respond(requests[0],{...marker,round:1});
else {
 respond(requests[0],marker);await flush();
 if(failure==='manifest404')respond(requests[1],{},404);
 if(failure==='manifest503')respond(requests[1],{},503);
 if(failure==='manifest_validation')respond(requests[1],{environment:'oficial',results:[{...row('ac',1),round:1}]});
}
await initialization;
assert.equal(api.getContext().status,'error');assert.equal(api.getContext().result,null);
assert.equal($('round-unavailable').hidden,true);assert(!document.body.classList.contains('round-two-unavailable'));
assert($('results').textContent.includes('Tentar novamente'));assert.equal($('results').getAttribute('aria-busy'),'false');
assert.equal(timers.length,0);assert(requests.every(request=>request.url.startsWith(root+'/')));
""".replace("FAILURE", json.dumps(failure)), 2)


def test_round_two_waiting_timer_obeys_visibility_and_scoped_polling_and_reports_later_errors():
    run_portal(r"""
run('manifest=null;portalMarker=null;selectedScope=null;selectedOffice=null;activeDataBase=ROUND_DATA_ROOT;showResultState("loading");');
const first=run('initialize()');respond(requests[0],{},404);await first;
assert.equal($('round-unavailable').hidden,false);assert(document.body.classList.contains('round-two-unavailable'));
assert.equal(timers.length,1);assert.equal(run('roundTwoWaitingTimer'),1);
let paused=true,poll=false;const gates=[];
window.LiveData={fetch,paused:namespace=>{gates.push(['paused',namespace]);return paused;},
 shouldPoll:(base,namespace)=>{gates.push(['poll',base,namespace]);return poll;}};
document.hidden=true;await timers[0].fn();assert.equal(requests.length,1);assert.equal(gates.length,0);
document.hidden=false;await timers[0].fn();assert.equal(requests.length,1);assert.deepEqual(gates.at(-1),['paused',root]);
paused=false;await timers[0].fn();assert.equal(requests.length,1);assert.deepEqual(gates.at(-1),['poll',root,root]);
poll=true;const retry=timers[0].fn();assert.equal(requests.length,2);respond(requests[1],{},503);await retry;
assert.equal(api.getContext().status,'error');assert.equal($('round-unavailable').hidden,true);
assert.equal(timers[0].active,false);assert.equal(run('roundTwoWaitingTimer'),null);
assert(!document.body.classList.contains('round-two-unavailable'));assert($('results').textContent.includes('Tentar novamente'));
""", 2)


@pytest.mark.parametrize("failure", ["network", "http", "validation"])
def test_current_refresh_failure_shows_a_retry_notice_without_clearing_verified_data(failure):
    run_portal(r"""
const refresh=run('refreshIfChanged()'),failure=FAILURE;
if(failure==='network')requests[0].reject(new TypeError('Synthetic offline'));
else if(failure==='http')respond(requests[0],{},503);
else respond(requests[0],{...marker,snapshot_id:'invalid'});
await refresh;
assert.equal(api.getContext().status,'ready');assert.equal(api.getContext().result,initialContext.result);
assert($('results').textContent.includes('Initial'));assert.equal($('publication-update-status').hidden,false);
assert($('publication-update-status').textContent.includes('Tentar novamente'));
const retry=$('publication-update-status').children[1].click();respond(requests[1],marker);await retry;
assert.equal($('publication-update-status').hidden,true);assert.equal(api.getContext().result,initialContext.result);
""".replace("FAILURE", json.dumps(failure)))
