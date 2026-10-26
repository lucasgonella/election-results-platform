"""Offline accounting, strict round/section boundaries and crash recovery."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from collector.src import biometry as b, biometry_publish as p, biometry_runner as r
from collector.src.second_round_publish import load
from deploy import ssh_remote
from tests.biometry_fixtures import TARGET, bu, dataset
from tests.test_frontend_deploy import FakeFTP


class BUAccountingTests(unittest.TestCase):
    def test_three_counters_have_official_order_and_balance(self):
        result=b.parse_bu(bu(), TARGET)
        self.assertEqual([result[key] for key in b.FIELDS], [183,163,10,10,0])

    def test_absent_authentication_is_unknown_including_manual_sa(self):
        for raw in [bu(counters=None),bu(counters=None,manual=True,attendance=0)]:
            result=b.parse_bu(raw,TARGET)
            self.assertEqual([result[key] for key in b.FIELDS], [183,0,0,0,183])

    def test_wrong_election_section_phase_and_inconsistent_counts_fail(self):
        for arguments in [dict(code=6251),dict(pleito=3219),dict(phase=1),dict(section=176),
                          dict(counters=(10,162,10)),dict(presidential=182),dict(votes=182)]:
            with self.subTest(arguments=arguments),self.assertRaises(ValueError):
                b.parse_bu(bu(**arguments),TARGET)

    def test_truncated_and_indefinite_ber_fail(self):
        for raw in [bu()[:-1],b'\x30\x80'+b'0'*50,b'\x30\x84\xff\xff\xff\xff'+b'0'*50]:
            with self.assertRaises(ValueError):b.parse_bu(raw,TARGET)

    def test_resume_replaces_same_section_instead_of_double_counting(self):
        with tempfile.TemporaryDirectory() as state:
            db=b.database(state)
            db.execute('INSERT INTO sections(uf,municipality,zone,section,name,stamp,priority) VALUES(?,?,?,?,?,?,?)',
                       ('ac','01074','0004','0175','Sintética','synthetic',0))
            for _ in range(2):b.store(db,TARGET,bu(),'https://resultados.tse.jus.br/synthetic')
            self.assertEqual(db.execute('SELECT COUNT(*),SUM(attendance) FROM sections').fetchone()[:],(1,183))
            self.assertEqual(db.execute('SELECT source_sha256 FROM sections').fetchone()[0],b.sha(bu()))
            db.close()

    def test_aggregates_reject_tampering_and_unsupported_scope(self):
        b.validate(dataset())
        for mutate in [lambda d:d['election'].update(round=1),lambda d:d['totals'].update(biometric=164),
                       lambda d:d['municipalities'].append(d['municipalities'][0]),
                       lambda d:d.update(complete=True),lambda d:d['national_reference'].update(attendance=1),
                       lambda d:d['municipalities'][0].update(uf='xx')]:
            value=deepcopy(dataset());mutate(value)
            with self.assertRaises(ValueError):b.validate(value)

    def test_aux_only_accepts_one_totalized_bu_with_expected_filename(self):
        class Client:
            value={'st':'Totalizada','hashes':[{'st':'Totalizado','hash':'a'*88,'arq':[{'tp':'bu','nm':'o03221ac0107400040175-bu.dat'}]}]}
            def json(self,url):return self.value,'hash'
            def get(self,url):return bu()
        client=Client()
        self.assertEqual(r.fetch_bu(client,TARGET)[0],bu())
        client.value=deepcopy(client.value);client.value['hashes']*=2
        with self.assertRaisesRegex(ValueError,'ambiguous'):r.fetch_bu(client,TARGET)

    def test_http_rejects_non_official_and_unbounded_rates(self):
        for url in ['http://resultados.tse.jus.br/oficial/x','https://evil.example/oficial/x',
                    'https://resultados.tse.jus.br/oficial/x?other=1']:
            with self.assertRaises(ValueError):r.OfficialHTTP().get(url)
        with self.assertRaises(ValueError):r.OfficialHTTP(6)

    def test_inventory_deduplicates_aggregated_sections_and_invalidates_changed_bu(self):
        class Client:
            revision=0
            def json(self,url):
                if url==r.CONFIG:return {},'synthetic'
                if url==r.NATIONAL:
                    return dict(ele='6258',t='2',cdabr='br',carg=[dict(cd='1')],s=dict(ts='56'),e=dict(c=str(56*183))),'synthetic'
                uf=url.split('/')[-2]
                sections=[dict(ns='0175',da=str(self.revision)),dict(ns='0176'),dict(ns='0177',nsp='0175')]
                return dict(cdp='3221',abr=[dict(cd=uf,ds='Sintética '+uf,mu=[dict(cd='01074',nm='Sintética',zon=[dict(cd='0004',sec=sections)])])]),'synthetic'
        with tempfile.TemporaryDirectory() as state,patch('collector.src.municipal_collection.election',return_value=dict(code=6258,pleito=3221)):
            db=b.database(state);client=Client();r.initialize(db,client)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sections').fetchone()[0],56)
            target=dict(db.execute("SELECT * FROM sections WHERE uf='ac' AND section='0175'").fetchone())
            b.store(db,target,bu(),'synthetic');b.store(db,target,bu(),'synthetic')
            value=b.aggregate(db);self.assertEqual(value['totals']['processed'],1)
            self.assertEqual(value['totals']['biometric'],163)
            client.revision=1;r.initialize(db,client)
            self.assertEqual(b.aggregate(db)['totals']['processed'],0)
            db.close()

    def test_rate_limit_sets_shared_cooldown_without_retrying(self):
        client=r.OfficialHTTP()
        from unittest.mock import MagicMock
        session=MagicMock();response=session.get.return_value.__enter__.return_value
        response.status_code=429;response.headers={'Retry-After':'120'};client.local.session=session
        with self.assertRaises(r.Throttled):client.get(r.NATIONAL)
        with self.assertRaises(r.Throttled):client.get(r.NATIONAL)
        self.assertEqual(session.get.call_count,1)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name);self.ftp=FakeFTP();self.t=p.Transport(self.ftp)
        self.pub=p.Publisher(self.t,self.state,http_read=lambda name:self.ftp.files.get(p.SITE+'/'+name))
        self.ftp.files['/public_html/data/turnos/2/version.json']=b'protected'

    def test_publication_is_verified_idempotent_and_keeps_other_namespaces(self):
        first=self.pub.publish(dataset());self.assertEqual(first['status'],'published')
        uploads=len(self.ftp.events)
        self.assertEqual(self.pub.publish(dataset())['status'],'unchanged')
        self.assertEqual(len(self.ftp.events),uploads)
        self.assertEqual(self.ftp.files['/public_html/data/turnos/2/version.json'],b'protected')
        self.assertNotIn(p.PRIVATE+'/lock',self.ftp.dirs)
        self.pub.verify(self.pub.marker())

    def test_crash_boundaries_recover_same_journal_without_double_publication(self):
        for boundary in ['before_activation','after_activation','before_cleanup','after_owner_cleanup','after_lock_cleanup']:
            with self.subTest(boundary=boundary):
                self.setUp()
                def fault(phase):
                    if phase==boundary:raise RuntimeError('synthetic_crash')
                self.pub.fault=fault
                with self.assertRaisesRegex(RuntimeError,'synthetic_crash'):self.pub.publish(dataset())
                self.pub.fault=lambda _:None
                self.assertEqual(self.pub.recover()['status'],'published')
                self.assertIsNone(load(self.state/'pending-publish.json'))
                self.pub.verify(self.pub.marker())

    def test_unknown_lock_or_owner_is_not_adopted(self):
        self.t.directory(p.PRIVATE);self.ftp.mkd(p.PRIVATE+'/lock')
        with self.assertRaisesRegex(RuntimeError,'unknown_remote_lock'):self.pub.publish(dataset())
        self.assertIn(p.PRIVATE+'/lock',self.ftp.dirs)

    def test_corruption_stops_before_activation_and_can_recover(self):
        def fault(phase):
            if phase=='before_activation':
                path=next(x for x in self.ftp.files if '/releases/' in x)
                self.ftp.files[path]+=b'bad'
        self.pub.fault=fault
        # Final post-activation verification catches even a changed immutable payload.
        with self.assertRaises(ValueError):self.pub.publish(dataset())
        self.assertIn(p.PRIVATE+'/lock',self.ftp.dirs)

    def test_existing_unmanaged_namespace_and_outside_writes_are_rejected(self):
        self.t.directory(p.SITE)
        with self.assertRaisesRegex(RuntimeError,'existing_namespace'):self.pub.publish(dataset())
        for path in ['/public_html/data/version.json',p.SITE+'/other.json',p.SITE+'/../bad']:
            with self.assertRaises(ValueError):self.t.writable(path)
        with tempfile.TemporaryDirectory() as remote:
            for path in ['/public_html/data/version.json','/frontend-deploy/portal/current.json']:
                with self.assertRaises(ValueError):ssh_remote.path_for(path,'biometry-2',remote)

    def test_browser_reader_checks_hash_scope_and_csv_formula_escape(self):
        script=r'''
const assert=require('node:assert/strict');globalThis.crypto=require('node:crypto').webcrypto;
const api=require('./web/public/eleicoes/biometry.js');const data=JSON.parse(process.argv[1]);
const bytes=Buffer.from(JSON.stringify(data));const hash=require('node:crypto').createHash('sha256').update(bytes).digest('hex');
const marker={schema:1,election:data.election,snapshot_id:hash,sha256:hash,size:bytes.length};
const calls=[];const fetcher=async path=>{calls.push(path);return path.endsWith('version.json')?{ok:true,json:async()=>marker}:{ok:true,arrayBuffer:async()=>bytes};};
(async()=>{const result=await api.read(fetcher);assert.equal(result.data.totals.biometric,163);assert.equal(calls.length,2);
 marker.election={...data.election,round:1};await assert.rejects(api.read(fetcher));marker.election=data.election;
 marker.sha256='0'.repeat(64);await assert.rejects(api.read(fetcher));marker.sha256=hash;
 marker.size++;await assert.rejects(api.read(fetcher));
 assert(api.csv([{...data.states[0],name:'=SYNTHETIC'}]).includes("'=SYNTHETIC"));
})();'''
        subprocess.run(['node','-e',script,json.dumps(dataset())],check=True,cwd=Path(__file__).resolve().parents[1])
