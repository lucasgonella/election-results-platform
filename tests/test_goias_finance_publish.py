"""Synthetic publication bytes and mocked network; no official documents."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import goias_finance_publish as p


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


def test_financial_workflow_uses_latest_main_and_single_scoped_writer():
    workflow = (Path(__file__).resolve().parents[1]/'.github/workflows/goias-finance-data.yml').read_text()
    assert 'ref: main' in workflow and '-m tools.goias_finance_publish' in workflow
    assert 'concurrency:' in workflow and 'goias-finance-etl' in workflow
    assert '--upload-file' not in workflow and 'git push origin HEAD:main' in workflow
