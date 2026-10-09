# CI/CD — GitHub Actions

## What is automated in this PR

- PR/push: PHP syntax check, Python unit tests, Python compilation, verified artifact.
- On main push (once enabled): prepare an isolated HTTPS release on an app01
  self-hosted runner labeled `election-app01`.
- No `git pull` or test execution needed from an interactive app01 shell after
  the runner has been registered and configured.

## One-time bootstrap (not automated yet)

1. Install a dedicated, unprivileged GitHub Actions self-hosted runner on
   app01, dedicated to this repository, with label `election-app01`.
   Do **not** register the runner as root or give unrestricted sudo.
2. Ensure runner account has PHP CLI and Python 3, and can write into
   `$HOME/election-https-staging-releases` only.
3. Define repository variable `ENABLE_HTTPS_STAGING_CD=true` only after
   validation, and create an environment named `https-staging`.
4. Enable branch protections and require successful CI before merging.
5. For Locaweb deployment a *separate* authenticated deployment channel is
   required. The existing HMAC API receives data batches, not executable PHP
   files and must not be repurposed into an arbitrary code uploader.

## Limits

This workflow stages deployment code to an isolated folder, **not** to
the active production source tree and not to Locaweb. It does not execute
`activate-sandbox.php` or modify systemd, SSH transport, live state, or
`public_html/data`. Live publication remains SSH-based.

Full hands-off production CD requires a documented deployment identity, a
narrowly scoped remote deploy endpoint or supported hosting deployment API,
staged release verification, rollback controls, locking and remote activation
tests. Avoid expiring interactive hosting-panel JWTs or plaintext FTP.
