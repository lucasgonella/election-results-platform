import copy
import ftplib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch,Mock
from urllib.error import HTTPError

import requests
from collector.src.election_release import canonical,parse,digest
from collector.src.municipal_collection import HTTP,Unavailable,Throttled,election,inventory,result,UF_CODES,collect,source_url,CONFIG
from collector.src.municipal_release import assemble,verify
from collector.src.municipal_publish import Transport,Publisher,SITE,PRIVATE,http
from tests.municipal_fixtures import ELECTION,ea20,make_dataset,make_geometry
from tests.test_frontend_deploy import FakeFTP


class MunicipalDataTests(unittest.TestCase):
    def parsed(self,raw=None,selected=None):
        return result(raw or ea20(),{'uf':'go','tse_code':'00001','ibge_code':'5200001','name':'Município sintético'},selected or ELECTION,{'captured_at':'2026-10-04T23:00:00+00:00','url':'https://resultados.tse.jus.br/oficial/fixture','sha256':'0'*64},{'1001':{},'1002':{}})

    def test_local_votes_percentages_leader_second_and_final(self):
        value=self.parsed();self.assertEqual(value['leader']['votes'],80);self.assertEqual(value['second']['votes'],20)
        self.assertEqual(value['difference_votes'],60);self.assertEqual(value['difference_percentage_points'],60)
        self.assertEqual(value['status'],'final');self.assertEqual(value['valid_votes'],100)

    def test_partial_tie_waiting_and_second_round_are_explicit(self):
        self.assertEqual(self.parsed(ea20(partial=True))['status'],'partial')
        tie=self.parsed(ea20(tie=True));self.assertEqual(tie['status'],'tie');self.assertIsNone(tie['leader'])
        self.assertEqual(self.parsed(ea20(waiting=True))['status'],'waiting')
        self.assertEqual(self.parsed(ea20(round_number=2),{**ELECTION,'round':2})['election']['round'],2)
        with self.assertRaises(ValueError):self.parsed(ea20(round_number=2))

    def test_wrong_source_scope_office_duplicate_candidates_and_denominator_fail(self):
        for edit in [{'f':'s'},{'tpabr':'uf'},{'cdabr':'00002'},{'t':'2'},{'ele':'9'},{'dv':'n'}]:
            with self.subTest(edit=edit),self.assertRaises(ValueError):self.parsed({**ea20(),**edit})
        raw=ea20();raw['carg'][0]['cd']='3'
        with self.assertRaises(ValueError):self.parsed(raw)
        raw=ea20();raw['carg'][0]['agr'][0]['par'][0]['cand'][1]['sqcand']='1001'
        with self.assertRaises(ValueError):self.parsed(raw)
        raw=ea20();raw['carg'][0]['agr'][0]['par'][0]['cand'][0]['pvapn']='90'
        with self.assertRaises(ValueError):self.parsed(raw)
        raw=ea20();raw['s']['st']='0'
        with self.assertRaises(ValueError):self.parsed(raw)

    def test_discovery_uses_configuration_not_example_codes_and_isolates_round(self):
        config={'f':'o','pl':[{'c':'ele2026','cd':'fixture','e':[{'cd':'9012','t':'1','abr':[{'cp':[{'cd':'1'}]}]},{'cd':'9013','t':'2','abr':[{'cp':[{'cd':'1'}]}]}]}]}
        self.assertEqual(election(config,1)['code'],9012);self.assertEqual(election(config,2)['code'],9013)
        with self.assertRaises(Unavailable):election({**config,'pl':[]},1)
        dataset=make_dataset();ea12={'f':'o','abr':[{'cd':uf,'mu':[{'cd':row['tse_code'],'cdi':row['ibge_code'],'nm':row['name']} for row in dataset['municipalities'] if row['uf']==uf]} for uf in UF_CODES]}
        self.assertEqual(len(inventory(ea12)),27)
        broken=copy.deepcopy(ea12);broken['abr'][0]['mu'][0]['cdi']='5200001'
        with self.assertRaises(ValueError):inventory(broken)
        broken=copy.deepcopy(ea12);broken['abr'][0]['mu']*=2
        with self.assertRaises(ValueError):inventory(broken)

    def test_cache_conditional_requests_retries_and_unavailable_circuit(self):
        class Session:
            responses=[];calls=[]
            def get(self,url,**kwargs):
                self.calls.append(kwargs)
                result=self.responses.pop(0)
                if isinstance(result,Exception):raise result
                return result
        def response(status,body=None):
            r=requests.Response();r.status_code=status;r._content=canonical(body or {'f':'o'});r.headers['ETag']='fixture-etag';return r
        with tempfile.TemporaryDirectory() as temp:
            session=Session();session.responses=[requests.Timeout(),response(200),response(304)]
            client=HTTP(temp,rate=10,session_factory=lambda:session,sleep=lambda _:None)
            url='https://resultados.tse.jus.br/oficial/fixture.json'
            self.assertEqual(client.get(url)[1],{'f':'o'});self.assertEqual(client.get(url)[1],{'f':'o'})
            self.assertEqual(session.calls[-1]['headers']['If-None-Match'],'fixture-etag');self.assertEqual(client.not_modified,1)
            session.responses=[response(404)]
            with self.assertRaises(Unavailable):client.get(url)
            with self.assertRaises(Unavailable):client.get(url)
            self.assertEqual(len(session.responses),0)

    def collection_client(self,directory,*,mismatch=False,partial=False,waiting=False,round_number=1):
        dataset=make_dataset(round_number)
        config={'f':'o','pl':[{'c':'ele2026','cd':'fixture','e':[{'cd':'9001','t':str(round_number),'abr':[{'cp':[{'cd':'1'}]}]}]}],
                'arq':[{'tp':kind,'dir':'<base>/<ambiente>/<ciclo>/<cd_eleicao>/'+('config' if kind=='cm' else 'dados/<uf>')} for kind in ['cm','ab','u']]}
        selected={**ELECTION,'round':round_number}
        url=lambda kind,uf,name:source_url(config,selected,kind,uf,name)
        inv={'f':'o','abr':[{'cd':uf,'mu':[{'cd':r['tse_code'],'cdi':r['ibge_code'],'nm':r['name']} for r in dataset['municipalities'] if r['uf']==uf]} for uf in UF_CODES]}
        go=next(r for r in dataset['municipalities'] if r['uf']=='go')
        municipal=ea20(go['tse_code'],round_number,partial=partial,waiting=waiting)
        national={**ea20('br',round_number,waiting=waiting),'tpabr':'br'}
        state={**ea20('go',round_number,partial=partial,tie=mismatch,waiting=waiting),'tpabr':'uf'}
        tracking={'f':'o','ele':'9001','t':str(round_number),'abr':[{'tpabr':'mun','cdabr':go['tse_code'],'s':municipal['s']},{'tpabr':'uf','cdabr':'go','s':state['s']}]}
        values={CONFIG:config,url('cm','br','mun-e009001-cm.json'):inv,
                url('ab','br','br-e009001-ab.json'):{'f':'o','ele':'9001','t':str(round_number),'abr':[{'tpabr':'uf','cdabr':uf} for uf in UF_CODES]},
                url('u','br','br-c0001-e009001-u.json'):national,url('ab','go','go-e009001-ab.json'):tracking,
                url('u','go',f"go{go['tse_code']}-c0001-e009001-u.json"):municipal,url('u','go','go-c0001-e009001-u.json'):state}
        class Client:
            downloads=reused=not_modified=0
            stop=threading.Event()
            def __init__(self):self.directory=Path(directory);self.calls=[]
            def get(self,path,**kwargs):
                self.calls.append(path);raw=values[path]
                return {'url':path,'sha256':digest(canonical(raw)),'captured_at':'2026-10-04T23:00:00+00:00'},copy.deepcopy(raw)
        return Client()

    def test_collection_reconciles_final_uf_and_resumes_its_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            client=self.collection_client(temp)
            first=collect(client,1,{'go'});second=collect(client,1,{'go'})
            self.assertEqual(first,second);self.assertEqual(first['coverage']['go']['reconciliation'],'equal')
            self.assertEqual(len(first['municipalities']),1);self.assertTrue((Path(temp)/'go-tracking.json').exists())

    def test_final_divergence_fails_closed_but_partial_coverage_explains_it(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,'municipal_final_uf_reconciliation_failed'):
                collect(self.collection_client(temp,mismatch=True),1,{'go'})
            self.assertEqual(parse((Path(temp)/'go-tracking.json').read_bytes()),{})
            data=collect(self.collection_client(temp,mismatch=True,partial=True),1,{'go'})
            self.assertEqual(data['coverage']['go']['reconciliation'],'partial_cdn_timestamps_differ')
            self.assertFalse(data['coverage']['go']['all_final'])

    def test_unstarted_second_round_does_not_request_municipal_files(self):
        with tempfile.TemporaryDirectory() as temp:
            client=self.collection_client(temp,round_number=2,waiting=True)
            with self.assertRaisesRegex(Unavailable,'municipal_second_round_not_started'):collect(client,2,{'go'})
            self.assertEqual(len(client.calls),4)
            self.assertFalse((Path(temp)/'go-tracking.json').exists())


class FTP(FakeFTP):
    def __init__(self):super().__init__();self.pwd='/'
    def cwd(self,path):
        self.pwd=path if path.startswith('/') else self.pwd.rstrip('/')+'/'+path
        if self.pwd not in self.dirs:raise ftplib.error_perm('550 Missing')
    def mkd(self,path):super().mkd(path if path.startswith('/') else self.pwd.rstrip('/')+'/'+path)


class MunicipalPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.data=make_dataset();make_geometry(self.data,self.root/'geometry')
        self.marker=assemble(self.data,self.root/'geometry',self.root/'package')
        self.ftp=FTP();self.transport=Transport(self.ftp,1)
        self.protected={'/public_html/data/version.json':b'round-one','/public_html/data/turnos/2/version.json':b'round-two','/public_html/estudos/index.html':b'studies','/public_html/eleicoes/index.html':b'portal'}
        self.ftp.files.update(self.protected)
        self.publisher=Publisher(self.transport,http_read=lambda path:self.ftp.files.get(SITE+'/'+path))

    def test_success_preserves_all_protected_namespaces_and_has_https_proof(self):
        result=self.publisher.publish(self.root/'package');self.assertEqual(result['status'],'published')
        self.assertEqual(self.publisher.status()['status'],'verified');self.assertFalse(self.publisher.status()['lock'])
        self.assertEqual(self.publisher.publish(self.root/'package')['status'],'unchanged')
        for path,raw in self.protected.items():self.assertEqual(self.ftp.files[path],raw)
        for path in self.protected:
            with self.assertRaises(ValueError):self.transport.writable(path)

    def test_incomplete_or_corrupt_package_cannot_activate(self):
        path=self.root/'package/turnos/1/releases'/self.marker['release_id']/'overview.json'
        original=path.read_bytes();path.write_bytes(original+b'bad')
        with self.assertRaises(ValueError):self.publisher.publish(self.root/'package')
        self.assertNotIn(self.transport.site+'/version.json',self.ftp.files)
        path.write_bytes(original)
        d=copy.deepcopy(self.data);d['coverage']['go']['pending']=1
        with self.assertRaises(ValueError):assemble(d,self.root/'geometry',self.root/'bad-package')

    def test_failure_before_activation_requires_official_recovery_and_keeps_marker(self):
        def fail(point):
            if point=='after_file':raise RuntimeError('injected_power_failure')
        self.publisher.fault=fail
        with self.assertRaises(RuntimeError):self.publisher.publish(self.root/'package')
        self.assertIsNone(self.publisher.marker());self.assertTrue(self.publisher.pending())
        with self.assertRaises(RuntimeError):self.publisher.publish(self.root/'package')
        self.publisher.fault=lambda _:None
        self.assertEqual(self.publisher.recover()['status'],'restored')
        self.assertEqual(self.publisher.publish(self.root/'package')['status'],'published')

    def test_crash_after_activation_is_verified_and_committed_by_recovery(self):
        self.publisher.fault=lambda point:(_ for _ in ()).throw(RuntimeError('injected')) if point=='after_activation' else None
        with self.assertRaises(RuntimeError):self.publisher.publish(self.root/'package')
        self.assertEqual(parse(self.publisher.marker())['release_id'],self.marker['release_id'])
        self.publisher.fault=lambda _:None
        self.assertEqual(self.publisher.recover()['status'],'published')
        self.assertFalse(self.publisher.status()['pending'])

    def test_unknown_lock_and_cross_turn_paths_are_never_bypassed(self):
        self.transport.directory(self.transport.private);self.ftp.mkd(self.transport.private+'/lock')
        with self.assertRaises(RuntimeError):self.publisher.recover()
        with self.assertRaises(ValueError):self.transport.writable(SITE+'/turnos/2/version.json')
        with self.assertRaises(ValueError):self.transport.writable(SITE+'/turnos/1/releases/'+'a'*64+'/../../version.json')

    def test_https_read_reset_retries_but_missing_and_invalid_content_fail_closed(self):
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.read.side_effect=[ConnectionResetError(104,'synthetic reset'),b'verified later by caller']
        opener=Mock();opener.open.return_value=response
        with patch('collector.src.municipal_publish.build_opener',return_value=opener),patch('collector.src.municipal_publish.time.sleep'):
            self.assertEqual(http('turnos/1/version.json'),b'verified later by caller')
            self.assertEqual(opener.open.call_count,2)
            opener.open.reset_mock();opener.open.side_effect=HTTPError('fixture',404,'missing',{},None)
            self.assertIsNone(http('turnos/2/version.json'));self.assertEqual(opener.open.call_count,1)
            opener.open.reset_mock();opener.open.side_effect=None;response.read.side_effect=None;response.read.return_value=b'x'*(16*1024*1024+1)
            with self.assertRaisesRegex(ValueError,'municipal_oversized_https_response'):http('turnos/1/version.json')
            self.assertEqual(opener.open.call_count,1)

    def test_ftp_read_reconnects_without_writes_and_permanent_reset_is_bounded(self):
        path=SITE+'/turnos/1/version.json';self.ftp.files[path]=b'synthetic payload';before=dict(self.ftp.files);events=list(self.ftp.events)
        original=self.ftp.retrbinary;calls=[]
        def read(command,callback):
            calls.append(command)
            if len(calls)==1:raise ConnectionResetError(104,'synthetic reset')
            return original(command,callback)
        self.ftp.retrbinary=read;self.ftp.close=lambda:None;self.transport.reconnect=lambda:self.ftp
        self.assertEqual(self.transport.read(path),b'synthetic payload');self.assertEqual(len(calls),2);self.assertEqual(self.ftp.files,before)
        self.assertEqual(self.ftp.events,events)
        calls.clear()
        def permanent(command,callback):calls.append(command);raise ConnectionResetError(104,'synthetic reset')
        self.ftp.retrbinary=permanent
        with self.assertRaises(ConnectionResetError):self.transport.read(path)
        self.assertEqual(len(calls),3);self.assertEqual(self.ftp.files,before)
        self.assertEqual(self.ftp.events,events)

