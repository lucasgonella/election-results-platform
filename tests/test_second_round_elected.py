"""Official-shaped synthetic outcomes; no live sources or publication."""
from copy import deepcopy

import pytest

from collector.src.election_release import canonical, parse
from collector.src.second_round_collection import build_values, discover, elected_results, write_values
from collector.src.second_round_publish import describe, save
from collector.src.second_round_runner import proof, verify_proof
from test_second_round_transactions import Source


def elected_source():
    source = Source(totalized=100)
    source.payload['tf'] = 's'
    source.payload['carg'][0]['agr'][0]['par'][0]['cand'][1].update(e='s', st='Eleito')
    return source


def test_governor_elected_summary_matches_candidate_and_aggregate():
    source = elected_source()
    values = build_values(source, discover(source))
    feed = parse(values['alerts.json'])
    assert feed['schema_version'] == 2
    assert feed['alert_count'] == 1
    winner = feed['alerts'][0]
    assert (winner['scope'], winner['office'], winner['candidate_name'], winner['kind']) == ('ac', 3, 'A', 'elected')
    assert winner['candidate_id'] == 100 and winner['result_status'] == 'Eleito'
    assert parse(values['portal.json'])['files']['alerts.json'] == feed
    assert describe(values)['status'] == 'verified_offline'


def test_leadership_without_official_election_never_declares_a_winner():
    source = Source()
    source.payload['carg'][0]['agr'][0]['par'][0]['cand'][1].update(e='n', st='')
    source.payload['md'] = 'e'
    values = build_values(source, discover(source))
    assert parse(values['alerts.json'])['alerts'] == []


def test_presidential_result_is_only_declared_for_brazil():
    source = elected_source()
    payload = parse(build_values(source, discover(source))['ac/governor.json'])
    payload['office'].update(code=1, name='Presidente')
    assert elected_results(payload) == []
    payload['scope'].update(code='br', uf=None)
    assert elected_results(payload)[0]['office'] == 1


@pytest.mark.parametrize('include_alerts', [False, True])
def test_source_proofs_preserve_legacy_and_current_winner_feeds(tmp_path, include_alerts):
    source = elected_source()
    values = build_values(source, discover(source), include_elected_alerts=include_alerts)
    package = tmp_path / 'package'
    write_values(package, values)
    save(tmp_path / 'source-proof.json', proof(values, source))
    assert verify_proof(package)['snapshot_id'] == describe(values)['snapshot_id']


def test_invented_elected_summary_cannot_pass_source_replay(tmp_path):
    source = elected_source()
    values = build_values(source, discover(source))
    feed = parse(values['alerts.json'])
    feed['alerts'][0]['candidate_name'] = 'Invented winner'
    values['alerts.json'] = canonical(feed)
    portal = parse(values['portal.json'])
    portal['files']['alerts.json'] = deepcopy(feed)
    values['portal.json'] = canonical(portal)
    package = tmp_path / 'package'
    write_values(package, values)
    save(tmp_path / 'source-proof.json', proof(values, source))
    with pytest.raises(ValueError, match='second_round_source_package_mismatch'):
        verify_proof(package)
