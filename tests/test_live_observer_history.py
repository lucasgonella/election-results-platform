"""Contracts for official signals and factual history; isolated files only."""
from datetime import datetime, timedelta, timezone

import pytest

from hardening_fixtures import FullSource
from collector.src.election_release import parse
from collector.src.second_round_collection import build_values, discover, write_values
from collector.src.second_round_publish import describe, load, save
from collector.src.second_round_runner import cycle, proof
from collector.src.second_round_vote_history import build_history
from collector.src.second_round_watch import CONFIG, watch_urls


def recorded(state, generation, *, published=True):
    source = FullSource(generation=generation, totalized=50)
    values = build_values(source, discover(source))
    sid = describe(values)['snapshot_id']
    package = state / 'cycles' / sid[:32] / 'package'
    write_values(package, values)
    save(package.parent / 'source-proof.json', proof(values, source))
    if published:
        stamp = (datetime(2026, 10, 25, 20, tzinfo=timezone.utc) + timedelta(minutes=generation)).isoformat()
        receipt = {'status': 'published', 'round': 2, 'snapshot_id': sid, 'verified_at': stamp}
        save(state / 'receipts' / (sid + '.json'), receipt)
        save(state / 'checkpoint.json', receipt)
    return sid, values


def test_observer_selects_only_pinned_official_second_round_indexes(tmp_path):
    recorded(tmp_path, 1)
    urls = watch_urls(tmp_path)
    assert CONFIG in urls and len(urls) == 3
    assert all('/dados/br/' in url and url.endswith('-ab.json') for url in urls if url != CONFIG)
    assert all(url.startswith('https://resultados.tse.jus.br/oficial/') for url in urls)


@pytest.mark.parametrize('status', ['failed', 'rate_limited', 'official_data_temporarily_unavailable'])
def test_source_event_never_bypasses_error_backoff(tmp_path, status):
    import time
    save(tmp_path / 'health.json', {'status': status, 'retry_after_epoch': time.time() + 600})
    result = cycle(tmp_path, source_changed=True,
                   connector=lambda: pytest.fail('must respect error backoff'))
    assert result['status'] == 'backoff'


def test_history_uses_only_verified_completed_publications_and_preserves_cache(tmp_path):
    first, values = recorded(tmp_path, 1)
    second, _ = recorded(tmp_path, 2)
    unpublished, _ = recorded(tmp_path, 3, published=False)
    result = build_history(tmp_path)
    assert [point['snapshot_id'] for point in result['points']] == [first, second]
    assert unpublished not in str(result)
    expected = {str(row['tse_candidate_seq']): row['votes']
                for row in parse(values['br/president.json'])['candidates']}
    assert result['points'][0]['votes'] == expected
    assert result['round'] == 2 and result['scope'] == 'br' and result['office'] == 1
    assert build_history(tmp_path) == result == load(tmp_path / 'vote-history.json')
