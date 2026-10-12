"""Read-only second-turn preflight. No FTP writes or state mutation.

Usage:
  TSE_ROUND=2 ELECTION_STATIC_STATE_DIR=/absolute/round1-state \
    python -m collector.src.second_round_preflight \
      --first-round-current /absolute/round1-state/current.json \
      --round-two-state /absolute/round2-state
"""
import argparse
import json
from pathlib import Path

from .election_release import parse
from .runtime import load_settings
from .static_election_runner import second_round_preflight


def inspect(*, first_round_current, round_two_state):
    path = Path(first_round_current)
    if path.is_symlink() or not path.is_file():
        raise ValueError("invalid_first_round_checkpoint_file")
    current = parse(path.read_bytes())
    return second_round_preflight(load_settings(), current, state_dir=round_two_state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-round-current", type=Path, required=True)
    parser.add_argument("--round-two-state", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(first_round_current=args.first_round_current,
                             round_two_state=args.round_two_state)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
