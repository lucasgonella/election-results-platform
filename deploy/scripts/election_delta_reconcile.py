"""Read-only recovery classification for interrupted offline delta assemblies.

Never deletes a claim, overwrites outputs, switches public pointers or retries.
"""
import argparse
import json
from pathlib import Path

from election_release_assembler import regular_file, safe_name, sha


def inspect_claim(*, ledger, output, release_id, expected_base):
    for identity in (release_id, expected_base):
        if (not isinstance(identity, str) or len(identity) != 64
                or any(c not in "0123456789abcdef" for c in identity)):
            raise ValueError("invalid_snapshot_identity")
    ledger, output = Path(ledger), Path(output)
    if ledger.is_symlink() or not ledger.is_dir():
        raise ValueError("invalid_delivery_ledger")
    claim = ledger / release_id
    if claim.is_symlink() or not claim.is_dir():
        return {"state": "unclaimed", "release_id": release_id}
    receipt = claim / "receipt.json"
    if not receipt.exists():
        return {"state": "interrupted_requires_manual_reconciliation", "release_id": release_id}
    data = json.loads(regular_file(receipt))
    if (data != {"status": "assembled", "release_id": release_id,
                 "base_snapshot_id": expected_base}):
        raise ValueError("invalid_delivery_receipt")
    if output.name != release_id or output.is_symlink() or not output.is_dir():
        return {"state": "receipt_without_output_requires_review", "release_id": release_id}
    return {"state": "assembled_requires_external_verification", "release_id": release_id}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--expected-base", required=True)
    args = parser.parse_args()
    print(json.dumps(inspect_claim(ledger=args.ledger, output=args.output,
                                   release_id=args.release_id,
                                   expected_base=args.expected_base)))


if __name__ == "__main__":
    main()
