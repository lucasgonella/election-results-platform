"""Synthetic, offline contract checks for the visual finance reader."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "web/public/eleicoes/goias/raio-x/finance-core.js"


@unittest.skipUnless(shutil.which("node"), "Node is required for frontend reader tests")
class PremiumFinanceGraphTests(unittest.TestCase):
    def run_node(self, body):
        script = "const assert = require('node:assert/strict');\n"
        script += f"const F = require({str(CORE)!r});\n"
        script += """
const c = (id, name='Pessoa', extras={}) => ({id,name,party:'EX',number:'9999',office:'deputado federal',revenue:null,expenses:null,votes:null,...extras});
const t = (id, from_id, to_id, amount=100, extras={}) => ({id,from_id,to_id,from_name:from_id,to_name:to_id,amount,date:'01/09/2026',type:'Doação documentada',source_url:'https://dadosabertos.tse.jus.br/dataset/fixture',...extras});
const data = (candidates, transfers) => ({scope:'GO',year:2026,candidates,transfers});
"""
        result = subprocess.run(["node", "-e", script + body], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_source_urls_fail_closed(self):
        self.run_node("""
assert.equal(F.safeSource('https://dadosabertos.tse.jus.br/dataset/a'), 'https://dadosabertos.tse.jus.br/dataset/a');
assert.equal(F.safeSource('https://cdn.tse.jus.br/file.zip'), 'https://cdn.tse.jus.br/file.zip');
for (const url of ['http://dadosabertos.tse.jus.br/a','https://tse.jus.br.evil.example/a','https://evil.example/tse.jus.br','javascript:alert(1)','https://user:pass@tse.jus.br/a','https://tse.jus.br:8443/a',null]) assert.equal(F.safeSource(url),null);
""")

    def test_scope_schema_and_unique_source_ids(self):
        self.run_node("""
assert.throws(()=>F.validateData({...data([],[]),scope:'SP'}));
assert.throws(()=>F.validateData({...data([],[]),year:2022}));
assert.throws(()=>F.validateData(data([c('a'),c('a')],[])));
assert.throws(()=>F.validateData(data([c('a')],[t('1','b','a'),t('1','b','a')])));
assert.throws(()=>F.validateData(data([c('a',{},{office:'governador'})],[])));
assert.throws(()=>F.validateData(data([c('a')],[t('1','b','a','100')])));
assert.throws(()=>F.validateData(data([c('a',{},{votes:Infinity})],[])));
assert.equal(F.validateData(data([],[])).transfers.length,0);
""")

    def test_identity_uses_ids_and_types_are_not_guessed(self):
        self.run_node("""
const idx=F.buildIndex(data([c('candidate-a','Mesmo nome')],[t('1','donor:a','candidate-a',100,{from_name:'Mesmo nome'}),t('2','donor:b','candidate-a',100,{from_name:'Mesmo nome'})]));
assert.equal(idx.nodes.size,3);
assert.equal(idx.nodes.get('donor:a').kind,'counterparty');
assert.equal(idx.nodes.get('candidate-a').kind,'candidate');
assert.equal(F.findPath(idx.data.transfers,'donor:a','donor:b').status,'missing');
""")

    def test_proven_person_identity_and_campaign_projection_preserve_rows(self):
        self.run_node("""
const candidates=[c('a','Urna A',{person_id:'person:a',civil_name:'Nome civil A'}),c('b','Urna B',{person_id:'person:b'})];
const entities=[{id:'person:a',kind:'person',name:'Urna A',civil_name:'Nome civil A',roles:['candidate','donor','campaign_financier'],candidate_ids:['a'],campaign_ids:['campaign:a'],aliases:['Nome civil A']},{id:'person:b',kind:'person',name:'Urna B',roles:['candidate'],candidate_ids:['b'],aliases:[]},{id:'campaign:a',kind:'campaign',owner_person_id:'person:a',name:'Campanha A',roles:['campaign'],candidate_ids:['a'],aliases:[]}];
const raw={...data(candidates,[t('1','person:a','person:b',10,{from_role:'person'}),t('2','campaign:a','person:b',20,{from_role:'campaign',from_campaign_id:'campaign:a'})]),identity_schema:1,entities};
const idx=F.buildIndex(raw);
assert.equal(idx.nodes.size,2); assert.equal(idx.aliases.get('a'),'person:a');
assert.equal(idx.nodes.get('person:a').kind,'candidate-donor');
assert.equal(idx.data.transfers[1].from_id,'person:a');
assert.equal(idx.data.transfers[1].original_from_id,'campaign:a');
assert.equal(idx.data.transfers[1].from_role,'campaign');
assert.equal(F.sumKnown(idx.data.transfers).total,30);
assert.deepEqual(F.filterTransfers(idx,{selected:'person:a',direction:'personal'}).map(r=>r.id),['1']);
assert.deepEqual(F.filterTransfers(idx,{selected:'person:a',direction:'campaign'}).map(r=>r.id),['2']);
assert.equal(F.filterTransfers(idx,{kind:'multi'}).length,2);
assert.equal(F.filterCandidates(idx,{q:'Nome civil A'}).length,1);
assert.equal(F.aggregate(idx.data.transfers).length,2);
assert.equal(raw.transfers[1].from_id,'campaign:a');
assert.equal(F.fromQuery(F.toQuery({selected:'person:a',direction:'campaign'})).direction,'campaign');
assert.throws(()=>F.validateData({...raw,entities:entities.filter(e=>e.id!=='person:a')}));
assert.throws(()=>F.validateData({...raw,entities:entities.map(e=>e.kind==='campaign'?{...e,owner_person_id:'missing'}:e)}));
""")

    def test_dates_validate_calendar_and_brazilian_format(self):
        self.run_node("""
assert.equal(F.dateKey('01/09/2026'),'2026-09-01');
assert.equal(F.dateKey('2026-10-12T15:20:00Z'),'2026-10-12');
assert.equal(F.dateKey('29/02/2024'),'2024-02-29');
for (const value of ['29/02/2026','31/04/2026','2026-13-01',null,'invalid']) assert.equal(F.dateKey(value),null);
""")

    def test_null_zero_and_filtered_intervals_are_distinct(self):
        self.run_node("""
const idx=F.buildIndex(data([c('a')],[t('0','x','a',0),t('n','x','a',null),t('100','y','a',100,{date:null})]));
assert.deepEqual(F.sumKnown(idx.data.transfers),{total:100,known:2,missing:1,count:3});
assert.equal(F.sumKnown([t('n','x','a',null)]).total,null);
assert.equal(F.sumKnown([t('0','x','a',0)]).total,0);
const missingData=data([c('a')],[t('n','x','a',null)]);
const missingView=F.graphView(F.buildIndex(missingData),missingData.transfers,'a');
assert.equal(missingView.nodes.find(n=>n.id==='x').volume,null);
assert.equal(missingView.totalNodes,2);
assert.deepEqual(F.filterTransfers(idx,{min:'0',max:'0'}).map(r=>r.id),['0']);
assert.deepEqual(F.filterTransfers(idx,{start:'2026-09-01',end:'2026-09-01'}).map(r=>r.id),['0','n']);
assert.equal(F.filterTransfers(idx,{start:'2026-09-02'}).length,0);
""")

    def test_shared_filters_use_actual_candidate_and_connection_metadata(self):
        self.run_node("""
const idx=F.buildIndex(data([c('a','Álvaro',{party:'AAA'}),c('b','Bia',{party:'BBB',office:'deputado estadual'})],[t('1','x','a',10,{from_name:'João',type:'Categoria A'}),t('2','x','b',20,{from_name:'João',type:'Categoria B'})]));
assert.equal(F.filterCandidates(idx,{q:'alvaro'}).length,1);
assert.deepEqual(F.filterTransfers(idx,{office:'deputado estadual'}).map(r=>r.id),['2']);
assert.deepEqual(F.filterTransfers(idx,{party:'AAA',from:'joao',type:'Categoria A'}).map(r=>r.id),['1']);
assert.equal(F.filterTransfers(idx,{to:'bia',kind:'candidate'}).length,1);
assert.equal(F.filterTransfers(idx,{to:'inexistente'}).length,0);
""")

    def test_candidate_subtotals_survive_person_projection_and_metrics(self):
        self.run_node("""
const coverage=(status,known_records=0,missing_records=0,zero_declarations=[],known_subtotal=(known_records||zero_declarations.length)?0:null)=>({status,known_records,missing_records,zero_declarations,known_subtotal});
const a=c('a','Urna A',{person_id:'person:a',revenue:null,expenses:0,financial_coverage:{revenue:coverage('partial',1,1,[],25),expenses:coverage('known',1)}});
const b=c('b','Urna B',{person_id:'person:a',financial_coverage:{revenue:coverage('missing'),expenses:coverage('missing')}});
const d=c('d','Urna D',{person_id:'person:d',revenue:0,expenses:null,financial_coverage:{revenue:coverage('known',0,0,[{source_file:'receitas_candidatos_2026_GO.csv',source_row:2}]),expenses:coverage('missing')}});
const raw={...data([a,b,d],[]),financial_schema:1,identity_schema:1,entities:[{id:'person:a',kind:'person',name:'Urna A',roles:['candidate'],candidate_ids:['a','b'],aliases:[]},{id:'person:d',kind:'person',name:'Urna D',roles:['candidate'],candidate_ids:['d'],aliases:[]}]};
assert.equal(F.validateData(raw),raw);
assert.deepEqual(F.sumKnown(raw.candidates,'revenue'),{total:25,known:2,missing:2,count:3});
const idx=F.buildIndex(raw), person=idx.nodes.get('person:a');
assert.equal(person.revenue,25); assert.equal(person.expenses,0);
assert.deepEqual(person.financial_summary.revenue,{total:25,known:1,missing:2,count:2});
assert.equal(person.financial_summary.expenses.missing,1);
assert.equal(F.sumKnown(idx.data.candidates,'revenue').missing,1);
assert.equal(F.sumKnown(idx.data.candidates,'revenue').total,25);
assert.equal(raw.candidates[0].financial_coverage.revenue.status,'partial');
// A reader ignoring additive metadata must never see a partial sum as total.
assert.equal(raw.candidates[0].revenue,null);
assert.equal(F.sumKnown(raw.candidates.map(({revenue})=>({revenue})),'revenue').total,0);
assert.equal(F.buildIndex(data([c('legacy','Legacy',{revenue:0,expenses:0})],[])).nodes.get('legacy').revenue,0);
""")

    def test_value_coverage_schema_rejects_inconsistent_claims(self):
        self.run_node("""
const metric=(status,known_records,missing_records=0,zero_declarations=[])=>({status,known_records,missing_records,zero_declarations,known_subtotal:(known_records||zero_declarations.length)?0:null});
const base=c('a','A',{revenue:0,financial_coverage:{revenue:metric('known',1),expenses:metric('missing',0)}});
assert.doesNotThrow(()=>F.validateData({...data([base],[]),financial_schema:1}));
for (const revenue of [metric('known',0),metric('known',1,1),metric('missing',1),metric('known',-1),metric('known',1.5),metric('known',0,0,[{source_file:'wrong.csv',source_row:2}])]) {
  assert.throws(()=>F.validateData({...data([{...base,financial_coverage:{...base.financial_coverage,revenue}}],[]),financial_schema:1}));
}
assert.throws(()=>F.validateData({...data([c('a')],[]),financial_schema:1}));
assert.throws(()=>F.validateData({...data([base],[]),financial_schema:2}));
assert.throws(()=>F.validateData({...data([{...base,revenue:null}],[]),financial_schema:1}));
""")

    def test_graph_volumes_keep_partial_and_zero_evidence(self):
        self.run_node("""
const rows=[t('positive','x','a',10),t('missing','x','a',null),t('zero','y','a',0),t('unknown','z','a',null),t('self','a','a',2)];
const index=F.buildIndex(data([c('a')],rows));
const view=F.graphView(index,rows,'a');
assert.equal(view.nodes.find(n=>n.id==='x').volume,10);
assert.equal(view.nodes.find(n=>n.id==='x').volume_summary.missing,1);
assert.equal(view.nodes.find(n=>n.id==='y').volume,0);
assert.equal(view.nodes.find(n=>n.id==='y').volume_summary.missing,0);
assert.equal(view.nodes.find(n=>n.id==='z').volume,null);
assert.equal(view.nodes.find(n=>n.id==='a').volume,12);
assert.deepEqual(F.filterTransfers(index,{min:'0',max:'0'}).map(r=>r.id),['zero']);
assert.equal(F.aggregate(rows).find(g=>g.from_id==='x').missing,1);
""")

    def test_grouping_preserves_direction_categories_and_original_records(self):
        self.run_node("""
const groups=F.aggregate([t('1','a','b',100),t('2','a','b',null),t('3','b','a',50),t('4','a','b',25,{type:'Outra categoria'})]);
assert.equal(groups.length,3);
const first=groups.find(g=>g.from_id==='a'&&g.type==='Doação documentada');
assert.equal(first.total,100); assert.equal(first.missing,1); assert.equal(first.reciprocal,true);
assert.deepEqual(first.rows.map(r=>r.id),['1','2']);
assert.equal(F.aggregate([t('1','a','b')])[0].reciprocal,false);
""")

    def test_directed_paths_preserve_each_hop_and_do_not_add_a_direct_edge(self):
        self.run_node("""
const rows=[t('ab','a','b',20),t('bc','b','c',40,{date:'02/09/2026'})];
const found=F.findPath(rows,'a','c');
assert.equal(found.status,'found'); assert.deepEqual(found.rows.map(r=>r.id),['ab','bc']);
assert.equal(found.rows[1].date,'02/09/2026');
assert.equal(F.findPath(rows,'c','a').status,'missing');
assert.equal(F.findPath(rows,'a','c',{maxHops:1}).status,'missing');
assert.equal(F.aggregate(rows).length,2); assert.equal(rows.length,2);
assert.equal(F.findPath(rows,'a','a').status,'invalid');
""")

    def test_paths_and_rendering_respect_bounded_work(self):
        self.run_node("""
const rows=Array.from({length:250},(_,i)=>t('r'+i,'donor:'+i,'a',i));
const idx=F.buildIndex(data([c('a')],rows));
const view=F.graphView(idx,rows,'a',1,{nodes:12,edges:10});
assert.ok(view.nodes.length<=12); assert.ok(view.edges.length<=10); assert.ok(view.nodes.some(n=>n.id==='a'));
assert.equal(view.totalEdges,250); assert.equal(view.hiddenEdges,250-view.edges.length);
assert.equal(F.findPath([t('ab','a','b'),t('bc','b','c')],'a','c',{maxVisited:2}).status,'limit');
""")

    def test_neighborhood_expands_only_documented_relationships(self):
        self.run_node("""
const rows=[t('xa','x','a'),t('xb','x','b'),t('yc','y','c')];
assert.deepEqual([...F.neighborhood(rows,'a',1).ids].sort(),['a','x']);
assert.deepEqual([...F.neighborhood(rows,'a',2).ids].sort(),['a','b','x']);
assert.equal(F.neighborhood(rows,'a',2).distance.get('b'),2);
""")

    def test_url_state_roundtrip_and_invalid_filters(self):
        self.run_node("""
const state={q:'João & Maria',office:'deputado estadual',selected:'donor:abc',type:'Recursos próprios',min:'0',view:'table',depth:2};
const round=F.fromQuery(F.toQuery(state));
for (const key of Object.keys(state)) assert.equal(round[key],state[key]);
const bad=F.fromQuery('min=no&max=-1&start=2026-13-01&end=invalid&depth=999&view=bad');
assert.equal(bad.min,''); assert.equal(bad.max,''); assert.equal(bad.start,''); assert.equal(bad.end,''); assert.equal(bad.depth,1); assert.equal(bad.view,'graph');
""")

    def test_external_reader_uses_stable_financial_path(self):
        app = (CORE.parent / "finance-app.js").read_text()
        self.assertIn("fetch('/eleicoes/goias/raio-x/data/go-2026.json'", app)
        self.assertNotIn("fetch('./data", app)
        self.assertNotIn("innerHTML = data", app)


if __name__ == "__main__":
    unittest.main()
