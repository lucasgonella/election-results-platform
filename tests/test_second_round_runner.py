from pathlib import Path
from types import SimpleNamespace
import pytest

from collector.src.second_round_collection import AwaitingData, CachedClient, RateLimited
from collector.src.second_round_publish import load, save
from collector.src.second_round_runner import cycle, proof, verify_proof
from test_second_round_transactions import Source, package


def test_real_pipeline_waiting_has_no_public_connection_in_dry_run(tmp_path):
    state=tmp_path/'state'
    client=Source(totalized=0)
    client.payload['carg'][0]['agr']=[]
    result=cycle(state,dry_run=True,client=client,connector=lambda:pytest.fail('FTP in dry-run'))
    assert result['status']=='awaiting_official_round_two_data'
    assert load(state/'health.json')['failures']==0
    assert not (state/'checkpoint.json').exists()
    assert cycle(state,dry_run=True,client=None)['status']=='backoff'


def test_complete_dry_run_proof_and_no_activation(tmp_path):
    state=tmp_path/'state'
    result=cycle(state,dry_run=True,client=Source())
    root=next((state/'cycles').glob('*/package'))
    assert verify_proof(root)['snapshot_id']==result['snapshot_id']
    assert not (state/'checkpoint.json').exists()
    (root/'ac/governor.json').write_text('{}')
    with pytest.raises(ValueError,match='source_package'):verify_proof(root)


def test_network_failure_has_bounded_backoff(tmp_path):
    state=tmp_path/'state'
    class Bad:
        def fetch_json(self,url):raise TimeoutError('no connection')
    with pytest.raises(TimeoutError):cycle(state,dry_run=True,client=Bad())
    result=load(state/'health.json')
    assert result['status']=='failed' and result['failures']==1
    assert result['error_type']=='TimeoutError'


def test_new_ftp_failure_does_not_inherit_ssh_diagnostics(tmp_path,monkeypatch):
    monkeypatch.setenv('PUBLICATION_TRANSPORT','ftp')
    state=tmp_path/'state'
    save(state/'health.json',{'status':'failed','failures':2,'transport':'ssh_rsync',
        'error_code':'ssh_operation_outcome_unknown','failure_code':'ssh_operation_outcome_unknown',
        'transport_operation':'hello','remote_errno':22,'connection_attempts':3})
    def broken():raise TimeoutError()
    with pytest.raises(TimeoutError):cycle(state,connector=broken)
    health=load(state/'health.json')
    assert health['error_type']=='TimeoutError' and health['transport']=='ftp'
    assert health['failures']==3
    assert not {'error_code','failure_code','transport_operation','remote_errno','connection_attempts'} & health.keys()
    assert load(state/'metrics-history.json')[-1]==health


def test_supervised_retry_verifies_complete_remote_state_before_source(tmp_path,monkeypatch):
    state=tmp_path/'state';sequence=[]
    save(state/'health.json',{'status':'failed','retry_after_epoch':10**12,'failures':4,
        'failed_cycles_total':4,'error_code':'old_error','failure_code':'old_error'})
    class Pub:
        def __init__(self,*args,**kwargs):pass
        def recover(self):sequence.append('recover')
        def status(self):
            sequence.append('verified status')
            return {'status':'verified','pending':False,'remote_lock':False,
                    'checkpoint_matches':True,'snapshot_id':'a'*64}
    monkeypatch.setattr('collector.src.second_round_runner.Publisher',Pub)
    class Requests:
        records={}
        def fetch_json(self,url):sequence.append('source');raise AwaitingData()
    t=SimpleNamespace(ftp=SimpleNamespace(close=lambda:sequence.append('close')))
    result=cycle(state,client=Requests(),connector=lambda:t,retry_after_reconcile=True)
    assert sequence==['recover','verified status','source','close']
    assert result['metrics']['supervised_retry']['prior_retry_after_epoch']==10**12
    assert result['failed_cycles_total']==4
    assert not {'error_code','failure_code'} & result.keys()


@pytest.mark.parametrize('change',[{'status':'unknown'},{'pending':True},
    {'remote_lock':True},{'checkpoint_matches':False}])
def test_supervised_retry_fails_closed_without_verified_quiescent_publication(tmp_path,monkeypatch,change):
    state=tmp_path/'state'
    save(state/'health.json',{'status':'failed','failures':2,'retry_after_epoch':10**12})
    class Pub:
        def __init__(self,*args,**kwargs):pass
        def recover(self):pass
        def status(self):return {'status':'verified','pending':False,'remote_lock':False,
            'checkpoint_matches':True,'snapshot_id':'a'*64,**change}
    monkeypatch.setattr('collector.src.second_round_runner.Publisher',Pub)
    class Requests:
        records={}
        def fetch_json(self,url):pytest.fail('source before verified reconciliation')
    t=SimpleNamespace(ftp=SimpleNamespace(close=lambda:None))
    with pytest.raises(RuntimeError,match='supervised_retry_requires_verified'):
        cycle(state,client=Requests(),connector=lambda:t,retry_after_reconcile=True)
    result=load(state/'health.json')
    assert result['status']=='failed' and result['failures']==3
    assert 'supervised_retry' not in result['metrics']


@pytest.mark.parametrize('status,dry_run',[('rate_limited',False),('unchanged',False),
    ('awaiting_official_round_two_data',False),('failed',True)])
def test_supervised_retry_cannot_override_source_rate_limit_cadence_or_dry_run(tmp_path,status,dry_run):
    state=tmp_path/'state';before={'status':status,'retry_after_epoch':10**12}
    save(state/'health.json',before)
    with pytest.raises(ValueError,match='supervised_retry_requires_failed_live_cycle'):
        cycle(state,dry_run=dry_run,retry_after_reconcile=True,
              connector=lambda:pytest.fail('connection before retry authorization'))
    assert load(state/'health.json')==before


def test_rate_limit_is_not_retried_in_same_cycle(tmp_path):
    state=tmp_path/'state'
    class Limited:
        def fetch_json(self,url):raise RateLimited(300)
    assert cycle(state,dry_run=True,client=Limited())['status']=='rate_limited'
    assert cycle(state,dry_run=True,client=Limited())['status']=='backoff'


def test_pending_recovery_precedes_new_source_requests(tmp_path,monkeypatch):
    sequence=[]
    class Pub:
        def __init__(self,*args,**kwargs):pass
        def recover(self):sequence.append('recover')
    monkeypatch.setattr('collector.src.second_round_runner.Publisher',Pub)
    class SourceRequest:
        records={}
        def fetch_json(self,url):
            sequence.append('source')
            raise AwaitingData()
    transport=SimpleNamespace(ftp=SimpleNamespace(close=lambda:None))
    cycle(tmp_path/'state',client=SourceRequest(),connector=lambda:transport)
    assert sequence==['recover','source']


def test_cycle_keeps_transport_metrics_in_health_and_history(tmp_path,monkeypatch):
    from collector.src import second_round_publish as pub
    from test_second_round_transactions import FTP
    ftp=FTP();ftp.dirs.update({'/public_html/data','/public_html/data/turnos',pub.SITE})
    # The transport owns this live counter dictionary; the publisher must attach
    # it to the runner's collector metrics instead of a discarded temporary dict.
    ftp.metrics={'transport':'ssh_rsync','ssh_failures':0,'files_sent':0}
    t=pub.Transport(ftp)
    def publisher(transport,state,*,metrics):
        return pub.Publisher(transport,state,metrics=metrics,http=lambda name:ftp.files.get(pub.SITE+'/'+name))
    monkeypatch.setattr('collector.src.second_round_runner.Publisher',publisher)
    result=cycle(tmp_path/'state',client=Source(),connector=lambda:t)
    assert result['status']=='published'
    assert result['metrics']['transport'] is ftp.metrics
    assert load(tmp_path/'state/health.json')['metrics']['transport']['transport']=='ssh_rsync'
    assert load(tmp_path/'state/metrics-history.json')[-1]['metrics']['transport']['ssh_failures']==0


def test_cache_etag_is_dedicated_and_304_reuses_exact_payload(tmp_path):
    client=CachedClient(tmp_path/'cache2')
    payload=Source().config
    calls=[]
    def fetch(url,**kw):
        calls.append(kw)
        return SimpleNamespace(status_code=200 if len(calls)==1 else 304,
            headers={'ETag':'official-etag'}, content=__import__('json').dumps(payload).encode(),
            raise_for_status=lambda:None)
    client.session.get=fetch
    url='https://resultados.tse.jus.br/oficial/comum/config/ele-c.json'
    first=client.fetch_json(url)
    second=client.fetch_json(url)
    assert first.payload==second.payload
    assert calls[1]['headers']=={'If-None-Match':'official-etag'}
    assert calls[0]['allow_redirects'] is False


@pytest.mark.parametrize('url',['https://resultados-sim.tse.jus.br/oficial/a.json',
 'http://resultados.tse.jus.br/oficial/a.json','https://resultados.tse.jus.br/simulado/a.json'])
def test_source_host_and_environment_cannot_change(tmp_path,url):
    with pytest.raises(ValueError,match='non_official'):CachedClient(tmp_path/'cache').fetch_json(url)


def test_round2_service_isolated_and_existing_units_untouched():
    root=Path(__file__).resolve().parents[1]
    service=(root/'deploy/systemd/election-round2.service').read_text()
    assert 'User=electionround2' in service
    assert 'StateDirectory=election-round2' in service
    assert 'LoadCredential=ftp.env:' in service
    assert 'ProtectSystem=strict' in service and 'CPUQuota=25%' in service
    env=(root/'deploy/env/round2.env.example').read_text()
    assert 'TSE_ROUND=2' in env
    assert 'collector.env' not in service


def test_complete_official_roster_dry_run_has_proof_without_activation(tmp_path):
    state=tmp_path/'roster-state'
    result=cycle(state,dry_run=True,client=Source(totalized=0))
    root=next((state/'cycles').glob('*/package'))
    assert result['status']=='verified_dry_run'
    assert result['publication_phase']=='candidate_roster'
    assert verify_proof(root)['snapshot_id']==result['snapshot_id']
    assert result['retry_after_epoch']>__import__('time').time()
    assert not (state/'checkpoint.json').exists()
