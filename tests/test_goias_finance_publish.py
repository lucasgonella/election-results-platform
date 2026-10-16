"""Synthetic publication bytes and mocked network; no official documents."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import goias_finance_publish as p
from deploy import finance_preflight


@pytest.fixture
def dataset(tmp_path):
    path = tmp_path/'go.json'
    path.write_text(json.dumps({'scope': 'GO', 'year': 2026, 'candidates': [{}]*101,
                               'transfers': [{'id': 'synthetic', 'value': 42}]}))
    return path, path.read_bytes()


def test_existing_verified_dataset_never_uploaded(dataset, monkeypatch):
    path, raw = dataset
    monkeypatch.setattr(p, 'ftp_read', lambda: raw)
    monkeypatch.setattr(p, 'https_read', lambda: raw)
    monkeypatch.setattr(p, '_ftp', lambda *a: pytest.fail('must not upload'))
    assert p.publish(path)['status'] == 'unchanged'


def test_nullable_values_and_additive_coverage_preserve_publication_bytes(tmp_path, monkeypatch):
    def candidate(i):
        value = [None, 0, 42][i % 3]
        coverage = {'status': 'missing' if value is None else 'known',
                    'known_records': 0 if value is None else 1, 'missing_records': 0,
                    'zero_declarations': [], 'known_subtotal': value}
        return {'id': 'synthetic:'+str(i), 'name': 'Exemplo', 'office': 'deputado federal',
                'revenue': value, 'expenses': value,
                'financial_coverage': {'revenue': coverage, 'expenses': coverage}}
    data = {'scope': 'GO', 'year': 2026, 'financial_schema': 1,
            'candidates': [candidate(i) for i in range(101)],
            'transfers': [{'id': 'receipt:'+str(i), 'amount': value} for i, value in enumerate([None, 0, 42])]}
    data['candidates'][0]['financial_coverage']['revenue'] = {
        'status': 'partial', 'known_records': 1, 'missing_records': 1,
        'known_subtotal': 12.5, 'zero_declarations': []}
    path = tmp_path / 'nullable.json'
    path.write_text(json.dumps(data))
    raw = path.read_bytes()
    reads = iter([b'previous', raw])
    uploads = []
    monkeypatch.setattr(p, 'ftp_read', lambda: next(reads))
    monkeypatch.setattr(p, 'https_read', lambda: raw)
    monkeypatch.setattr(p, '_ftp', lambda content: (uploads.append(content) or 0, b''))
    monkeypatch.setenv('FINANCE_PREFLIGHT_PROTOCOL', '1')
    proofs = []
    monkeypatch.setattr(finance_preflight, 'verify_live_reader', lambda: proofs.append('verified'))
    result = p.publish(path)
    assert result['status'] == 'published' and result['ftp_https_verified']
    assert proofs == ['verified']
    assert uploads == [raw] and json.loads(uploads[0]) == data


@pytest.mark.parametrize('protocol', [None, '', '0', '2'])
def test_legacy_workflow_cannot_publish_new_schema(dataset, monkeypatch, protocol):
    path, raw = dataset
    path.write_text(json.dumps({**json.loads(raw), 'financial_schema': 1}))
    monkeypatch.delenv('FINANCE_PREFLIGHT_PROTOCOL', raising=False)
    if protocol is not None:
        monkeypatch.setenv('FINANCE_PREFLIGHT_PROTOCOL', protocol)
    monkeypatch.setattr(finance_preflight, 'verify_live_reader', lambda: pytest.fail('legacy definition'))
    monkeypatch.setattr(p, 'ftp_read', lambda: pytest.fail('must not access transport'))
    with pytest.raises(RuntimeError, match='financial_preflight_protocol_required'):
        p.publish(path)


@pytest.mark.parametrize('schema', [None, True, '1', 0, 2])
def test_unsupported_schema_cannot_bypass_guard(dataset, monkeypatch, schema):
    path, raw = dataset
    path.write_text(json.dumps({**json.loads(raw), 'financial_schema': schema}))
    monkeypatch.setenv('FINANCE_PREFLIGHT_PROTOCOL', '1')
    monkeypatch.setattr(finance_preflight, 'verify_live_reader', lambda: pytest.fail('invalid schema'))
    with pytest.raises(ValueError, match='unsupported_financial_schema'):
        p.publish(path)


@pytest.mark.parametrize('transport', ['ftp', 'ssh'])
def test_protocol_marker_alone_cannot_authorize_upload(dataset, monkeypatch, transport):
    path, raw = dataset
    path.write_text(json.dumps({**json.loads(raw), 'financial_schema': 1}))
    monkeypatch.setenv('FINANCE_PREFLIGHT_PROTOCOL', '1')
    monkeypatch.setenv('PUBLICATION_TRANSPORT', transport)
    def blocked():
        raise RuntimeError('compatible_finance_reader_not_published')
    monkeypatch.setattr(finance_preflight, 'verify_live_reader', blocked)
    monkeypatch.setattr(p, 'ftp_read', lambda: pytest.fail('must not access transport'))
    with pytest.raises(RuntimeError, match='compatible_finance_reader_not_published'):
        p.publish(path)


def test_empty_financial_dataset_remains_blocked_before_transport(dataset, monkeypatch):
    path, raw = dataset
    data = json.loads(raw)
    data['transfers'] = []
    path.write_text(json.dumps(data))
    monkeypatch.setattr(p, 'ftp_read', lambda: pytest.fail('gate must run before transport'))
    with pytest.raises(ValueError, match='invalid_goias_dataset'):
        p.publish(path)


@pytest.mark.parametrize('code', [0, 18, 28, 56])
def test_lost_upload_response_resolved_by_complete_ftp_and_https_bytes(dataset, monkeypatch, code):
    path, raw = dataset
    reads = iter([b'previous', raw])
    uploads = []
    monkeypatch.setattr(p, 'ftp_read', lambda: next(reads))
    monkeypatch.setattr(p, 'https_read', lambda: raw)
    monkeypatch.setattr(p, '_ftp', lambda data: (uploads.append(data) or code, b''))
    result = p.publish(path)
    assert result['status'] == ('published' if code == 0 else 'reconciled_upload')
    assert result['ftp_https_verified'] and uploads == [raw]
    assert result['upload_returncode'] == code


@pytest.mark.parametrize('bad_side', ['ftp', 'https'])
def test_partial_or_different_remote_bytes_fail_without_upload_replay(dataset, monkeypatch, bad_side):
    path, raw = dataset
    reads = iter([b'old', b'partial' if bad_side == 'ftp' else raw])
    calls = []
    monkeypatch.setattr(p, 'ftp_read', lambda: next(reads))
    monkeypatch.setattr(p, 'https_read', lambda: b'different' if bad_side == 'https' else raw)
    monkeypatch.setattr(p, '_ftp', lambda data: (calls.append(data) or 56, b''))
    with pytest.raises(RuntimeError, match='publication_bytes_mismatch'):
        p.publish(path)
    assert calls == [raw]


def test_permanent_upload_error_not_adopted(dataset, monkeypatch):
    path, _ = dataset
    monkeypatch.setattr(p, 'ftp_read', lambda: b'old')
    monkeypatch.setattr(p, '_ftp', lambda *args: (67, b''))
    with pytest.raises(RuntimeError, match='upload_failed_67'): p.publish(path)


@pytest.mark.parametrize('codes,expected_calls', [([56, 0], 2), ([28, 28, 28], 3), ([67], 1)])
def test_only_reads_have_bounded_transient_retries(monkeypatch, codes, expected_calls):
    codes = iter(codes)
    calls = []
    def get(raw=None):
        assert raw is None
        calls.append('read')
        return next(codes), b'exact bytes'
    monkeypatch.setattr(p, '_ftp', get)
    monkeypatch.setattr(p.time, 'sleep', lambda *a: None)
    if expected_calls == 2: assert p.ftp_read() == b'exact bytes'
    else:
        with pytest.raises(RuntimeError): p.ftp_read()
    assert len(calls) == expected_calls


def test_native_transport_plain_passive_bounded_and_credentials_not_in_argv(monkeypatch):
    for key, value in {'FTP_HOST': 'ftp.example.test', 'FTP_DIR': p.DIRECTORY,
                       'FTP_USER': 'private-user', 'FTP_PASSWORD': 'private-password'}.items():
        monkeypatch.setenv(key, value)
    def run(args, **kwargs):
        assert args[1] == '--disable' and '--ftp-pasv' in args
        assert args[args.index('--proto')+1] == '=ftp'
        assert ':21/' in args[-1]
        assert not any('private-user' in x or 'private-password' in x for x in args)
        assert '--retry' not in args and '--ftp-create-dirs' not in args
        netrc = Path(args[args.index('--netrc-file')+1])
        assert netrc.stat().st_mode & 0o777 == 0o600
        return SimpleNamespace(returncode=0, stdout=b'verified')
    monkeypatch.setattr(p.subprocess, 'run', run)
    assert p._ftp() == (0, b'verified')
    monkeypatch.setenv('FTP_DIR', 'public_html/estudos')
    with pytest.raises(ValueError, match='invalid_goias_ftp_destination'): p._ftp(b'bytes')


def test_financial_workflow_pins_main_code_and_single_scoped_writer():
    workflow = (Path(__file__).resolve().parents[1]/'.github/workflows/goias-finance-data.yml').read_text()
    assert "if: github.ref == 'refs/heads/main'" in workflow
    assert 'ref: ${{ github.sha }}' in workflow and '-m tools.goias_finance_publish' in workflow
    assert 'concurrency:' in workflow and 'goias-finance-etl' in workflow
    assert '--upload-file' not in workflow and 'git push origin HEAD:main' in workflow
