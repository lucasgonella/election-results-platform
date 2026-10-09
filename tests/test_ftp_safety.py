import ftplib
from pathlib import Path

import pytest

from collector.src.ftp_safety import assert_transport_isolated, validate_inbox, validate_runner_environment
from collector.src.ftp_delivery import freeze, upload
from test_ftp_publication import KEY, dataset


@pytest.mark.parametrize('path',['','/','public_html/data','private/../inbox','private/.hidden','inbox\r\nSTOR x','inbox\\x','includes/inbox'])
def test_reject_unsafe_destination(path):
    with pytest.raises(ValueError): validate_inbox(path)


def test_no_upload_when_control_is_accessible(tmp_path):
    delivery=freeze(dataset(tmp_path/'stage'),tmp_path/'spool',KEY,None)
    operations=[]
    class ExposedFTP:
        def connect(self,*a,**k): operations.append('connect')
        def login(self,*a): operations.append('login')
        def sendcmd(self,command): operations.append(command); return '250 protected path exists'
        def close(self): operations.append('close')
        def storbinary(self,*a): pytest.fail('must never upload')
        def mkd(self,*a): pytest.fail('must never create directory')
    with pytest.raises(RuntimeError,match='ftp_control_exposed'):
        upload(delivery,'ftp-inbox/elections/staging','fixture','user','secret',ExposedFTP)
    assert operations==['connect','login','MLST .election-publisher','close']


@pytest.mark.parametrize('code',['500 unsupported','450 transient'])
def test_unverifiable_metadata_fails_closed(code):
    class FTP:
        def sendcmd(self,command): raise ftplib.error_perm(code)
    with pytest.raises(RuntimeError,match='ftp_isolation_unverifiable'):
        assert_transport_isolated(FTP())


def test_relative_hidden_but_absolute_control_visible():
    class FTP:
        def sendcmd(self,command):
            if command.startswith('MLST /'): return '250'
            raise ftplib.error_perm('550')
    with pytest.raises(RuntimeError,match='ftp_control_exposed'): assert_transport_isolated(FTP())


def runner_env(tmp_path):
    credentials=tmp_path/'ftp.env';credentials.write_text('fixture');credentials.chmod(0o600)
    return {'ELECTION_FTP_CUTOVER_APPROVED':'true','LOCAWEB_FTP_ISOLATION_APPROVED':'true',
            'LOCAWEB_FTP_HOST':'fixture','LOCAWEB_FTP_USER':'user','LOCAWEB_FTP_PASSWORD':'secret',
            'ELECTION_HMAC_KEY_FILE':'fixture','ELECTION_FTP_CONTROL_URL':'https://fixture.invalid/control',
            'LIVE_PUBLISH_STATE_DIR':str(tmp_path/'live'),'ELECTION_FTP_CREDENTIAL_FILE':str(credentials),
            'LOCAWEB_FTP_ELECTION_INBOX_DIR':'ftp-inbox/elections/staging'}


@pytest.mark.parametrize('field,value',[('ELECTION_FTP_CUTOVER_APPROVED','false'),('LOCAWEB_FTP_ISOLATION_APPROVED','false'),('LOCAWEB_FTP_PORT','22'),('LOCAWEB_FTP_PASSWORD',''),('ELECTION_FTP_CONTROL_URL','http://fixture.invalid/control')])
def test_unapproved_runner_does_not_collect(tmp_path,monkeypatch,field,value):
    from collector.src.ftp_live_runner import run
    from collector.src import live_publisher
    env=runner_env(tmp_path);env[field]=value
    for k,v in env.items(): monkeypatch.setenv(k,v)
    monkeypatch.setattr(live_publisher,'prepare',lambda:pytest.fail('must not collect'))
    with pytest.raises(ValueError): run()
    assert not (tmp_path/'live').exists()


def test_approved_runner_configuration(tmp_path):
    validate_runner_environment(runner_env(tmp_path))
