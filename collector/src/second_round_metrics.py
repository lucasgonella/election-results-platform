"""Bounded operational measurements; timestamps never stand in for official data."""
from contextlib import contextmanager
from datetime import datetime, timezone
import os
import shutil
import time


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def measure(metrics, phase):
    started, stamp = time.monotonic(), now()
    try:
        yield
    finally:
        item = metrics.setdefault(phase, {'started_at': stamp, 'duration_seconds': 0, 'calls': 0})
        item.update(finished_at=now(), calls=item['calls'] + 1,
                    duration_seconds=round(item['duration_seconds'] + time.monotonic() - started, 6))


def policy(values, previous, fingerprint):
    """Use official sections and source changes, never the wall clock, for phase."""
    from .election_release import parse
    rows = [parse(raw) for name, raw in values.items() if '/' in name]
    sections = [r['snapshot']['sections'] for r in rows]
    changed = fingerprint != previous.get('source_fingerprint')
    stable = 0 if changed else previous.get('stable_cycles', 0) + 1
    if not any(s['totalized'] > 0 for s in sections):
        state, delay = 'official_data_available', 120
    elif all(s['total'] > 0 and s['totalized'] == s['total'] for s in sections):
        state, delay = 'counting_finished', min(600, 60 * 2 ** min(stable, 4))
    elif stable >= 3:
        state, delay = 'counting_stable', min(120, 10 * 2 ** min(stable - 2, 4))
    else:
        state, delay = 'counting_in_progress', 10
    return {'election_state': state, 'poll_after_seconds': delay, 'stable_cycles': stable,
            'source_fingerprint': fingerprint,
            'last_official_change_at': (now() if changed and previous.get('source_fingerprint')
                                        else previous.get('last_official_change_at'))}


def storage(state):
    """A low-space guard never deletes recovery evidence to satisfy a limit."""
    from .second_round_publish import load, save
    old = load(state / 'storage.json') or {}
    epoch = time.time()
    allocated, count = old.get('cycle_bytes', 0), old.get('cycle_count', 0)
    if epoch - old.get('sampled_epoch', 0) >= 300:
        previous_bytes, previous_epoch = allocated, old.get('sampled_epoch', 0)
        allocated = count = 0
        for root in ('cycles', 'work'):
            path = state / root
            if not path.exists(): continue
            if path.is_symlink(): raise ValueError('unsafe_round2_storage_root')
            for item in path.iterdir():
                count += root == 'cycles'
                for f in [item, *item.rglob('*')]:
                    if f.is_symlink(): raise ValueError('unsafe_round2_storage_symlink')
                    allocated += f.stat().st_blocks * 512
        old['sampled_epoch'] = epoch
        old['growth_bytes_per_hour'] = (max(0, allocated - previous_bytes) * 3600 / (epoch - previous_epoch)
                                        if previous_epoch else 0)
    disk = shutil.disk_usage(state)
    minimum = int(os.environ.get('ELECTION_ROUND2_MIN_FREE_BYTES', str(1024 ** 3)))
    maximum = int(os.environ.get('ELECTION_ROUND2_MAX_CYCLE_BYTES', str(1024 ** 3)))
    growth_limit = int(os.environ.get('ELECTION_ROUND2_GROWTH_BYTES_PER_HOUR', str(256 * 1024 ** 2)))
    result = {'checked_at': now(), 'sampled_epoch': old['sampled_epoch'],
              'free_bytes': disk.free, 'cycle_bytes': allocated, 'cycle_count': count,
              'min_free_bytes': minimum, 'max_cycle_bytes': maximum,
              'growth_bytes_per_hour': old.get('growth_bytes_per_hour', 0),
              'alert': disk.free < minimum * 1.5 or allocated > maximum * .8
                       or old.get('growth_bytes_per_hour', 0) > growth_limit}
    save(state / 'storage.json', result)
    if disk.free < minimum or allocated >= maximum:
        raise RuntimeError('round2_storage_limit')
    return result


def history(state, result):
    from .second_round_publish import load, save
    path = state / 'metrics-history.json'
    rows = load(path) or []
    rows.append({key: value for key, value in result.items() if key not in {'error_message'}})
    save(path, rows[-500:])


def summarize(rows):
    import math
    import statistics
    columns = {'cycle_seconds': [r['cycle_seconds'] for r in rows if 'cycle_seconds' in r]}
    for row in rows:
        for key, value in row.get('metrics', {}).items():
            if isinstance(value, dict) and 'duration_seconds' in value:
                columns.setdefault(key, []).append(value['duration_seconds'])
    result = {}
    for key, values in columns.items():
        if not values: continue
        values.sort()
        item = {'samples': len(values), 'p50_seconds': statistics.median(values), 'max_seconds': max(values)}
        for percentile, minimum in [(95, 20), (99, 100)]:
            if len(values) >= minimum:
                item['p' + str(percentile) + '_seconds'] = values[math.ceil(len(values) * percentile / 100) - 1]
        result[key] = item
    return result


if __name__ == '__main__':
    import argparse
    import json
    from pathlib import Path
    from .second_round_publish import load
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state', type=Path, default=Path('/var/lib/election-round2'))
    args = p.parse_args()
    print(json.dumps(summarize(load(args.state / 'metrics-history.json') or []), sort_keys=True))
