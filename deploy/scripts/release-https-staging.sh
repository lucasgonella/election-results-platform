#!/usr/bin/env bash
# Manage isolated HTTPS publisher releases as the unprivileged Actions runner.
# This does NOT change /opt/election-results-platform, systemd or Locaweb.
set -Eeuo pipefail
umask 077
BASE="${HTTPS_RELEASE_BASE:-$HOME/election-https-staging-releases}"
REV="${1:?usage: release-staging.sh <40-char-git-sha>}"
[[ "$REV" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid commit SHA" >&2; exit 2; }
[[ -f deploy/locaweb/election-publish.php && -f deploy/scripts/publish-live-results-https.py ]] || exit 2
mkdir -p "$BASE"
exec 9>"$BASE/.release.lock"
flock -x 9
target="$BASE/$REV"
tmp="$(mktemp -d "$BASE/.incoming-XXXXXXXX")"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/deploy/locaweb" "$tmp/deploy/scripts"
install -m 0600 deploy/locaweb/election-publish.php "$tmp/deploy/locaweb/"
install -m 0600 deploy/locaweb/activate-sandbox.php "$tmp/deploy/locaweb/"
install -m 0600 deploy/locaweb/activate-private-batch.php "$tmp/deploy/locaweb/"
install -m 0600 deploy/locaweb/build-private-snapshot.php "$tmp/deploy/locaweb/"
install -m 0600 deploy/locaweb/promote-private-snapshot.php "$tmp/deploy/locaweb/"
install -m 0700 deploy/scripts/publish-live-results-https.py "$tmp/deploy/scripts/"
python3 -m py_compile "$tmp/deploy/scripts/publish-live-results-https.py"
(
  cd "$tmp"
  sha256sum deploy/locaweb/*.php deploy/scripts/*.py > SHA256SUMS
  sha256sum -c SHA256SUMS
)
if [[ -d "$target" ]]; then
  (cd "$target" && sha256sum -c SHA256SUMS)
else
  mv "$tmp" "$target"
fi
old="$(readlink "$BASE/current" || true)"
if [[ -n "$old" && "$old" != "$REV" ]]; then
  ln -sfn "$old" "$BASE/.previous-new"
  mv -Tf "$BASE/.previous-new" "$BASE/previous"
fi
ln -sfn "$REV" "$BASE/.current-new"
mv -Tf "$BASE/.current-new" "$BASE/current"
echo "STAGING RELEASE READY: $REV"
echo "Current: $(readlink "$BASE/current") Previous: $(readlink "$BASE/previous" || true)"
echo "Production service and public site: UNCHANGED"
