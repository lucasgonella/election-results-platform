"""Only synthetic FTP sessions; interrupted reads never replay writes."""
import ftplib

import pytest

from collector.src.second_round_publish import SITE, Transport
from test_second_round_transactions import FTP


class Interrupted(FTP):
    def __init__(self, error, *, metadata=False):
        super().__init__()
        self.error = error
        self.break_metadata = metadata
        self.closed = False
        self.calls = 0
        self.files[SITE+'/version.json'] = b'complete'

    def sendcmd(self, command):
        if self.break_metadata:
            self.calls += 1
            raise self.error
        return super().sendcmd(command)

    def retrbinary(self, command, callback, **kwargs):
        self.calls += 1
        callback(b'partial')
        raise self.error

    def close(self):
        self.closed = True


@pytest.mark.parametrize('error', [TimeoutError(), ConnectionResetError(), EOFError(), ftplib.error_temp('421 closed')])
def test_partial_retr_restarts_on_fresh_session_without_partial_bytes(monkeypatch, error):
    monkeypatch.setattr('time.sleep', lambda _: None)
    first = Interrupted(error)
    second = FTP()
    second.files[SITE+'/version.json'] = b'complete'
    t = Transport(first, reconnect=lambda: second)
    assert t.read(SITE+'/version.json') == b'complete'
    assert first.closed
    assert first.calls == 1
    assert first.events == second.events == []


@pytest.mark.parametrize('metadata', [False, True])
def test_read_has_one_three_attempt_budget(monkeypatch, metadata):
    monkeypatch.setattr('time.sleep', lambda _: None)
    sessions = [Interrupted(TimeoutError(), metadata=metadata) for _ in range(3)]
    remaining = iter(sessions[1:])
    t = Transport(sessions[0], reconnect=lambda: next(remaining))
    with pytest.raises(TimeoutError):
        t.read(SITE+'/version.json')
    assert sum(x.calls for x in sessions) == 3
    assert not t._reading
    assert all(not x.events for x in sessions)


@pytest.mark.parametrize('error', [ftplib.error_perm('530 denied'), ftplib.error_temp('450 busy'), ValueError('invalid_bytes')])
def test_permanent_validation_or_non_session_errors_are_not_retried(error):
    first = Interrupted(error)
    t = Transport(first, reconnect=lambda: pytest.fail('must not reconnect'))
    with pytest.raises(type(error)):
        t.read(SITE+'/version.json')
    assert first.calls == 1
    assert not t._reading


def test_missing_optional_and_outside_namespace_never_retried():
    ftp = FTP()
    t = Transport(ftp, reconnect=lambda: pytest.fail('must not reconnect'))
    assert t.read(SITE+'/version.json', optional=True) is None
    with pytest.raises(ValueError, match='outside_second_round_namespace'):
        t.read('/public_html/data/version.json')
    assert ftp.events == []
