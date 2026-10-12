# Local assembly experiment (NOT enabled in production)

The current production publisher continues to upload and verify 140 files through FTP port 21. The opt-in script `deploy/scripts/election_release_assembler.py` is an offline proof of concept for assembling an immutable candidate release on the Locaweb host from a full previous release and a delta inbox.

## Inputs

- `--base`: previously published 140-file release, read-only
- `--inbox`: private FTP-delivered delta files
- `--manifest`: JSON with exactly `files` (map of every release path to `{sha256,size}`) and `changed` (list of paths supplied from the inbox)
- `--output`: absent destination in a controlled private working area

The assembler checks every requested byte and the complete inventory, blocks symlink traversal and path escapes, and creates an output only after checks pass. It does **not** switch `version.json`, write to `public_html`, manage FTP locks, update watermarks, or activate a release. It intentionally does not run from the live publisher.

## Required before production rollout

1. Bind the manifest to the trusted app01 checkpoint and signed delta with an authenticated delivery protocol, including replay protection.
2. Add a narrowly scoped Locaweb runner (SSH command restriction or trusted scheduled job), with fail-closed locking and strict paths. Do not expose arbitrary shell execution via FTP uploads.
3. Add transaction journal, backups, full inventory and HTTPS checks, single marker switch and end-to-end recovery integration.
4. Test wrong manifest, tampering, symlink/path traversal, FTP disconnects, timeouts, repeated deliveries, crash after marker switch and reconciliation.
5. Run isolated staging and compare duration against production baseline (~9 minutes), then deploy through CI/CD with rollback plan.

Do not change the production systemd unit or use this experiment to publish public data.

## Restricted executor (experimental)

`deploy/scripts/election_delta_executor.py` checks an HMAC-SHA256 signed envelope with exactly five fields: `schema_version`, `base_snapshot_id`, `release_id`, `plan`, and `signature`. The signature covers the first four fields using compact sorted-key UTF-8 JSON. The 32+ byte secret is provided **out of band** in an owner-only file; never upload it via FTP or commit it. The trusted launcher pins `--expected-base` to the current validated snapshot and `--output` must end with the 64-character release identifier.

This is **not yet** a live deploy endpoint. It has no listener, no SSH privileges, no marker update, no automatic transition of pending/lock/watermarks, and no authorization to modify public files. A restrictive runner must supply safe directory roots and enforce trusted current-snapshot checks, one-shot delivery IDs, filesystem confinement, and transactional promotion. Signing alone does not prevent replay against an unchanged baseline; the destination-exists guard only prevents repeating the same output path.

Until end-to-end authenticated delivery, rollback, journal reconciliation, and staging tests are complete, do not run this against production and do not enable automatic activation.

## Replay-resistant claim (experimental)

The executor now requires `--ledger`, a trusted pre-created private directory. Before any assembly, it atomically creates `<ledger>/<release_id>/`. If the claim exists, the delivery is rejected. Success writes a receipt and fsyncs it. On a crash, a claim without a receipt remains intentionally blocked; an operator must reconcile local and public state, and must **never** simply delete the claim to retry. The ledger is not yet connected to the production publisher's transaction journal. The trusted launcher must protect the ledger and establish exclusive access to it.

No public marker or production site content is changed by this executor.
