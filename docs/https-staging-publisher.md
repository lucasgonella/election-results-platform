# HTTPS staging publisher (experimental; no production activation)

This is a **staging-only proof of integration**, not a production publisher.
The existing `run-live-publisher.sh`, SSH transport, systemd timer, and
`collector.src.live_publisher.commit()` remain unchanged.

## Deploy receiver for manual testing

1. Back up the current experimental `public_html/api/election-publish.php`.
2. Copy `deploy/locaweb/election-publish.php` to that location **only during an
   approved test window**. Review any other use of this experimental endpoint.
3. Keep the hex-encoded 32-byte HMAC secret at
   `$HOME/.election-publisher/hmac.key`, outside the document root, mode 0600.
4. Ensure `$HOME/.election-publisher` is mode 0700 and writable by PHP Web.
5. Restrict public access to the API to the app01 source egress IP where possible.
6. Validate a signed health request before staging a batch.

The receiver supports `health`, `begin`, `upload` and `inspect`.
It NEVER performs activation or writes to `public_html/data`.
Each signed request requires `X-Timestamp`, `X-Nonce`, `X-Signature`
over timestamp + newline + nonce + newline + exact JSON request bytes.
Replay nonces older than 180 seconds are cleaned after authenticated requests.

## Client dry-run (safe with active timer)

```bash
python3 deploy/scripts/publish-live-results-https.py \
  --stage /path/to/independent/test-stage
```

`--send` sends an already prepared staging directory; it does not execute
`prepare()`, `commit()`, or touch the current live stage:

```bash
python3 deploy/scripts/publish-live-results-https.py \
  --stage /path/to/independent/test-stage --send
```

The stage must include exactly 137 manifest entries, a matching generation
timestamp in manifest, alerts and version, and at least one changed result.
All files must be JSON and individually smaller than 700 KB.

**Do not point the client at the active**
`/var/lib/election-results-platform/live/stage` while the systemd timer is
running. `prepare()` deletes and regenerates that directory.

## Work remaining before production use

- Automatic lifecycle management and storage quota for old batches.
- Integration tests on a synthetic full 137-entry manifest and HTTP retries.
- Idempotent activation with transaction/rollback semantics and crash recovery.
- Prevent concurrent SSH and HTTPS writers to public JSON.
- Version monotonicity and frontend consistency strategy.
- Only then integrate transport selection into systemd and gate `commit()`
  on verified remote activation.

Never commit `hmac.key`, SSH private keys, `collector.env`, nonces,
staging contents, or publication data.
