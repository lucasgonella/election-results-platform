"""P0 contract: complete adjacency is independent of the rendered subgraph."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from tests.raiox_navigation_fixtures import navigation_fixture

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "web/public/eleicoes/goias/raio-x/finance-core.js"


@unittest.skipUnless(shutil.which("node"), "Node required for the finance reader")
class RaioxNavigationTests(unittest.TestCase):
    def run_node(self, body, extra_donors=0):
        script = "const assert=require('node:assert/strict');\n"
        script += f"const F=require({str(CORE)!r});\n"
        script += "const raw=" + json.dumps(navigation_fixture(extra_donors)) + ";\n"
        result = subprocess.run(["node"], input=script + body, text=True,
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_charles_to_izaura_uses_global_adjacency_at_every_hop(self):
        self.run_node("""
const index=F.buildIndex(raw), snapshot=JSON.stringify(raw);
const charles=F.getCompleteDirectConnections(index,'registration:charles');
assert.ok(charles.records.some(r=>r.from_id==='person:izaura'));
assert.ok(!charles.records.some(r=>r.to_id==='person:bia'));
const search=F.searchEntities(index,{q:'PERES IZAURA CRISTINA'}).items;
assert.equal(search.length,2); // homonyms are two different official identities
const direct=F.getCompleteDirectConnections(index,search.find(n=>n.id==='person:izaura').id);
const selectedURL=F.fromQuery('?selected=person%3Aizaura&q=CHARLES+BENTO');
assert.deepEqual(F.getCompleteDirectConnections(index,selectedURL.selected,selectedURL),direct);
const signature=result=>result.records.map(r=>[r.id,r.amount,r.from_id,r.to_id,r.source_record_id,r.source_url]);
for(const via of ['person:charles','person:bia','person:davi','person:paulo','person:charles']) {
  F.graphView(index,F.getCompleteDirectConnections(index,via).records,via,1,{nodes:2,edges:1});
  const click=F.getCompleteDirectConnections(index,'person:izaura',{q:'CHARLES BENTO'});
  assert.deepEqual(signature(click),signature(direct));
}
assert.equal(direct.available,4); assert.equal(direct.excludedByFilters,0);
assert.deepEqual([...new Set(direct.records.map(r=>r.to_id))].sort(),['person:bia','person:charles','person:davi']);
assert.equal(F.sumKnown(direct.records).total,800);
assert.equal(new Set(direct.records.map(r=>r.id)).size,4);
assert.equal(JSON.stringify(raw),snapshot);
assert.equal(F.getExplorationConnections(index,'person:izaura',{},1).records.length,4);
assert.ok(F.getExplorationConnections(index,'person:izaura',{},2).records.some(r=>r.id==='transaction:pb'));
""")

    def test_explicit_filters_report_excluded_connections(self):
        self.run_node("""
const index=F.buildIndex(raw);
const filtered=F.getCompleteDirectConnections(index,'person:izaura',{office:'deputado estadual',q:'Charles'});
assert.equal(filtered.available,4); assert.equal(filtered.excludedByFilters,2);
assert.deepEqual(filtered.records.map(r=>r.id),['transaction:ib','transaction:ib-distinct']);
assert.deepEqual(F.getCompleteDirectConnections(index,'campaign:bia'),F.getCompleteDirectConnections(index,'registration:bia'));
assert.equal(F.getCompleteDirectConnections(index,'missing').entityId,'');
assert.equal(F.getCompleteDirectConnections(index,'person:izaura',{direction:'incoming'}).records.length,0);
assert.equal(F.getCompleteDirectConnections(index,'person:izaura',{min:250}).records.length,1);
""")

    def test_self_transfers_are_counted_once_without_merging_distinct_receipts(self):
        self.run_node("""
raw.transfers.push({...raw.transfers[0],id:'transaction:self',from_id:'person:charles',amount:1});
const index=F.buildIndex(raw), direct=F.getCompleteDirectConnections(index,'person:charles');
assert.equal(direct.records.filter(r=>r.id==='transaction:self').length,1);
assert.equal(F.getCompleteDirectConnections(index,'person:izaura').records.filter(r=>r.amount===200).length,2);
assert.equal(F.sumKnown(index.data.transfers).total,891);
""")

    def test_search_finds_entities_outside_render_limits_and_does_not_merge_names(self):
        self.run_node("""
const index=F.buildIndex(raw);
const view=F.graphView(index,index.data.transfers,'',1,{nodes:2,edges:1});
assert.ok(!view.nodes.some(n=>n.id==='person:paulo'));
assert.equal(F.searchEntities(index,{q:'páulo exemplo'}).items[0].id,'person:paulo');
assert.equal(F.searchEntities(index,{q:'izaura peres'}).total,2);
assert.equal(F.searchEntities(index,{q:'Campanha CHARLES'}).items[0].id,'person:charles');
assert.equal(F.searchEntities(index,{q:'12.345.678/0001-00'}).total,3);
assert.equal(F.resolveSelection(index,'invalid'),'');
assert.equal(F.fromQuery('').selected,'');
""")

    def test_personal_document_queries_fail_closed_and_do_not_serialize(self):
        self.run_node("""
const index=F.buildIndex(raw);
for(const value of ['00000000000','000.000.000-00','nome 00000000000']) {
  assert.equal(F.searchEntities(index,{q:value}).total,0);
  assert.equal(F.filterTransfers(index,{from:value}).length,0);
  assert.equal(F.toQuery({q:value,from:value,to:value,selected:value}), '');
  assert.equal(F.fromQuery('q='+encodeURIComponent(value)).q,'');
}
assert.equal(F.toQuery({cpf:'blocked',selected:'person:izaura'}),'selected=person%3Aizaura');
// UUIDs can contain an eleven-digit hex segment by chance. They are opaque
// source anchors, not personal documents, and must remain shareable.
const opaque='person:00000000-0000-4000-8000-a12345678901';
assert.equal(F.fromQuery(F.toQuery({selected:opaque})).selected,opaque);
""")

    def test_zoom_preserves_cursor_point_and_limits(self):
        self.run_node("""
for(const camera of [{scale:1,x:0,y:0},{scale:2.7,x:-139,y:88},{scale:.4,x:230,y:-40}]) {
  for(const factor of [.001,.8,1.25,100]) {
    const p={x:723,y:148}, next=F.zoomAt(camera,factor,p);
    const world={x:(p.x-camera.x)/camera.scale,y:(p.y-camera.y)/camera.scale};
    assert.ok(Math.abs(next.x+world.x*next.scale-p.x)<1e-8);
    assert.ok(Math.abs(next.y+world.y*next.scale-p.y)<1e-8);
    assert.ok(next.scale>=.35&&next.scale<=8);
  }
}
""")

    def test_large_global_source_bounded_render_and_deterministic_layout(self):
        self.run_node("""
const {performance}=require('node:perf_hooks'), start=performance.now(), index=F.buildIndex(raw);
const complete=F.getCompleteDirectConnections(index,'person:davi');
assert.equal(complete.records.length,10001);
assert.equal(complete.available,10001);
const view=F.graphView(index,complete.records,'person:davi',1);
assert.ok(view.nodes.length<=70&&view.edges.length<=140);
assert.equal(view.totalEdges,10001); assert.ok(view.hiddenEdges>9900);
const a=F.stableLayout(view.nodes,view.edges,{selected:'person:davi'});
const b=F.stableLayout(view.nodes,view.edges,{selected:'person:davi'});
assert.deepEqual([...a],[...b]);
for(const point of a.values()) assert.ok(Number.isFinite(point.x)&&Number.isFinite(point.y));
assert.ok(performance.now()-start<4000,'Complete-source query and bounded layout exceeded 4s');
""", extra_donors=10000)


if __name__ == "__main__":
    unittest.main()
