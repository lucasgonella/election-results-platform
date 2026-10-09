"""Offline synthetic diagnostic tests. No temporary directories or network."""
import ftplib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'ftp_probe', Path(__file__).resolve().parents[1] / 'deploy/scripts/probe-ftp-staging.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class FTP:
    def __init__(self):
        self.operations = []
        self.files = {}
        self.exists = False
    def pwd(self):
        self.operations.append('PWD')
        return '/'
    def sendcmd(self, command):
        self.operations.append(command)
        if command == 'MLST ' + probe.NAMESPACE and not self.exists:
            raise ftplib.error_perm('550 unavailable')
        return '250 metadata'
    def cwd(self, path):
        self.operations.append(('CWD', path))
    def mkd(self, path):
        if self.exists:
            raise ftplib.error_perm('550 exists')
        self.exists = True
        self.operations.append(('MKD', path))
    def storbinary(self, command, stream):
        self.operations.append(command)
        self.files[command[5:]] = stream.read()
    def retrbinary(self, command, callback, blocksize=1024):
        self.operations.append(command)
        callback(self.files[command[5:]])
    def rename(self, source, target):
        self.operations.append(('RENAME', source, target))
        self.files[target] = self.files.pop(source)
    def mlsd(self, root):
        return [(name.rsplit('/', 1)[-1], {'type': 'file'}) for name in self.files]
    def delete(self, path):
        self.operations.append(('DELE', path))
        del self.files[path]
    def rmd(self, path):
        assert not self.files
        self.operations.append(('RMD', path))


@pytest.mark.parametrize('namespace', [None, '/', probe.PARENT, probe.NAMESPACE + '/child'])
def test_writes_require_exact_namespace(namespace):
    ftp = FTP()
    with pytest.raises(ValueError, match='exact_namespace_approval_required'):
        probe.transfer(ftp, namespace)
    assert ftp.operations == []


def test_default_plan_does_not_read_credentials_or_connect(capsys, monkeypatch):
    monkeypatch.setattr(probe, 'validate_credentials_file', lambda _: pytest.fail('no credentials'))
    monkeypatch.setattr(ftplib, 'FTP', lambda: pytest.fail('no network'))
    probe.main([])
    assert json.loads(capsys.readouterr().out)['remote_writes_authorized'] is False


def test_inspect_reports_broad_access_without_reading_content():
    ftp = FTP()
    result = probe.inspect(ftp)
    assert '/.election-publisher/hmac.key' in result['control_accessible']
    assert result['production_isolation'] == 'not_guaranteed'
    assert all(command == 'PWD' or command.startswith('MLST ') for command in ftp.operations)


def test_roundtrip_rename_and_separately_approved_cleanup():
    ftp = FTP()
    result = probe.transfer(ftp, probe.NAMESPACE)
    assert result['cleanup_pending'] is True
    assert ftp.files == {probe.FINAL: probe.PAYLOAD}
    assert ftp.operations.index('RETR ' + probe.PART) < ftp.operations.index(
        ('RENAME', probe.PART, probe.FINAL)) < ftp.operations.index('RETR ' + probe.FINAL)
    before = list(ftp.operations)
    with pytest.raises(ValueError):
        probe.cleanup(ftp)
    assert ftp.operations == before
    assert probe.cleanup(ftp, probe.NAMESPACE)['status'] == 'synthetic_probe_removed'


def test_existing_namespace_cannot_be_overwritten():
    ftp = FTP()
    ftp.exists = True
    with pytest.raises(ValueError, match='probe_namespace_already_visible'):
        probe.transfer(ftp, probe.NAMESPACE)
    assert not any(isinstance(op, str) and op.startswith('STOR') for op in ftp.operations)


def test_corrupted_transfer_preserves_evidence_without_rename_or_cleanup():
    ftp = FTP()
    original = ftp.storbinary
    def corrupt(command, stream):
        original(command, stream)
        ftp.files[probe.PART] = b'corrupt'
    ftp.storbinary = corrupt
    with pytest.raises(ValueError, match='probe_checksum_mismatch'):
        probe.transfer(ftp, probe.NAMESPACE)
    assert ftp.files == {probe.PART: b'corrupt'}
    assert not any(isinstance(op, tuple) and op[0] in {'RENAME', 'DELE', 'RMD'}
                   for op in ftp.operations)


@pytest.mark.parametrize('bad', ['unlisted.env', 'probe.json'])
def test_cleanup_rejects_unlisted_or_changed_content_before_deletion(bad):
    ftp = FTP()
    ftp.files[probe.NAMESPACE + '/' + bad] = b'unexpected'
    with pytest.raises(ValueError):
        probe.cleanup(ftp, probe.NAMESPACE)
    assert not any(isinstance(op, tuple) and op[0] in {'DELE', 'RMD'} for op in ftp.operations)


def test_partial_upload_can_be_removed_after_verified_cleanup_approval():
    ftp = FTP()
    ftp.files[probe.PART] = probe.PAYLOAD
    assert probe.cleanup(ftp, probe.NAMESPACE)['status'] == 'synthetic_probe_removed'


def test_lost_rename_response_preserves_final_for_readonly_reconciliation():
    ftp = FTP()
    original = ftp.rename
    def lose_response(source, target):
        original(source, target)
        raise TimeoutError()
    ftp.rename = lose_response
    with pytest.raises(TimeoutError):
        probe.transfer(ftp, probe.NAMESPACE)
    assert ftp.files == {probe.FINAL: probe.PAYLOAD}
    probe.retrieve(ftp, probe.FINAL)
    assert not any(isinstance(op, tuple) and op[0] in {'DELE', 'RMD'} for op in ftp.operations)


def test_production_isolation_gate_is_still_unconditional():
    from collector.src.ftp_safety import assert_transport_isolated
    with pytest.raises(RuntimeError, match='ftp_control_exposed'):
        assert_transport_isolated(FTP())


@pytest.mark.parametrize('reply', ['500 unsupported', '450 transient'])
def test_unverifiable_namespace_metadata_prevents_writes(reply):
    ftp = FTP()
    def deny(command):
        raise ftplib.error_perm(reply)
    ftp.sendcmd = deny
    with pytest.raises(ValueError, match='probe_namespace_unverifiable'):
        probe.transfer(ftp, probe.NAMESPACE)
    assert ftp.operations == [('CWD', probe.PARENT)]


def test_cleanup_rejects_symlink_and_preserves_all_files():
    ftp = FTP()
    ftp.files[probe.FINAL] = probe.PAYLOAD
    ftp.mlsd = lambda root: [('probe.json', {'type': 'OS.unix=slink'})]
    with pytest.raises(ValueError, match='unexpected_probe_inventory'):
        probe.cleanup(ftp, probe.NAMESPACE)
    assert ftp.operations == []


@pytest.mark.parametrize('operation', ['transfer', 'cleanup'])
def test_cli_approval_precedes_credential_access_and_network(operation, monkeypatch):
    monkeypatch.setattr(probe, 'validate_credentials_file', lambda _: pytest.fail('no credentials'))
    monkeypatch.setattr(ftplib, 'FTP', lambda: pytest.fail('no network'))
    with pytest.raises(ValueError, match='exact_namespace_approval_required'):
        probe.main([operation])
