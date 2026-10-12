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
