"""Tests for optional preassembled-release path; no real FTP or HTTP."""
import pytest
from collector.src.election_release import canonical, digest, targets
from collector.src.static_election_publish import activate, descriptor
from test_static_election_publish import release as fixture_release


def _prepare(transport, after):
    sid = digest(canonical(descriptor(after)))
    remote = transport.site + "/releases/" + sid
    transport.ftp.dirs.add(remote)
    for name, raw in after.items():
        transport.ftp.files[remote + "/" + name] = raw
    return sid, remote


def test_preassembled_release_uses_existing_transaction_and_skips_full_stage(fixture_release):
    transport, before, after, old, http = fixture_release
    sid, remote = _prepare(transport, after)
    with transport.lock():
        receipt = activate(transport, after,
                           reviews={n:digest(after[n]) for n in targets() if n.startswith("am/")},
                           http=http, preassembled=True)
    assert receipt["status"] == "published"
    assert receipt["snapshot_id"] == sid
    assert not any(event == ("rename_directory", remote) for event in transport.ftp.events)
    staging = transport.private + "/staging/" + sid + "/files/"
    assert not any(name.startswith(staging) for name in transport.ftp.files)


def test_missing_preassembled_release_never_switches_marker(fixture_release):
    transport, before, after, old, http = fixture_release
    with pytest.raises(ValueError, match="preassembled_release_missing"):
        with transport.lock():
            activate(transport, after,
                     reviews={n:digest(after[n]) for n in targets() if n.startswith("am/")},
                     http=http, preassembled=True)
    assert transport.ftp.files[transport.site + "/version.json"] == old


def test_tampered_preassembled_release_never_switches_marker(fixture_release):
    transport, before, after, old, http = fixture_release
    sid, remote = _prepare(transport, after)
    transport.ftp.files[remote + "/alerts.json"] = b"tampered"
    with pytest.raises(Exception):
        with transport.lock():
            activate(transport, after,
                     reviews={n:digest(after[n]) for n in targets() if n.startswith("am/")},
                     http=http, preassembled=True)
    assert transport.ftp.files[transport.site + "/version.json"] == old
