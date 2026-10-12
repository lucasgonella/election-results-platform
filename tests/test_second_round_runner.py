from pathlib import Path
from types import SimpleNamespace
import pytest

from collector.src.second_round_collection import AwaitingData, CachedClient, RateLimited
from collector.src.second_round_publish import load, save
from collector.src.second_round_runner import cycle, proof, verify_proof
from test_second_round_transactions import Source, package


def test_real_pipeline_waiting_has_no_public_connection_in_dry_run(tmp_path):
    state=tmp_path/'state'
    result=cycle(state,dry_run=True,client=Source(totalized=0),connector=lambda:pytest.fail('FTP in dry-run'))
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


def test_rate_limit_is_not_retried_in_same_cycle(tmp_path):
    state=tmp_path/'state'
    class Limited:
        def fetch_json(self,url):raise RateLimited(300)
    assert cycle(state,dry_run=True,client=Limited())['status']=='rate_limited'
    assert cycle(state,dry_run=True,client=Limited())['status']=='backoff'


def test_pending_recovery_precedes_new_source_requests(tmp_path,monkeypatch):
    sequence=[]
    class Pub:
        def __init__(self,*args):pass
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
