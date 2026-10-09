#!/usr/bin/env bash
# Roll back the isolated CD release pointer only. Never modify production.
set -Eeuo pipefail
BASE="${HTTPS_RELEASE_BASE:-$HOME/election-https-staging-releases}"
mkdir -p "$BASE"
exec 9>"$BASE/.release.lock"
flock -x 9
previous="$(readlink "$BASE/previous" || true)"
current="$(readlink "$BASE/current" || true)"
[[ "$previous" =~ ^[0-9a-f]{40}$ && -d "$BASE/$previous" ]] || {
  echo "No verified previous release" >&2
  exit 2
}
(cd "$BASE/$previous" && sha256sum -c SHA256SUMS)
ln -sfn "$previous" "$BASE/.current-rollback"
mv -Tf "$BASE/.current-rollback" "$BASE/current"
if [[ "$current" =~ ^[0-9a-f]{40}$ && -d "$BASE/$current" ]]; then
  ln -sfn "$current" "$BASE/.previous-rollback"
  mv -Tf "$BASE/.previous-rollback" "$BASE/previous"
fi
echo "Staging rollback: $current -> $previous"
echo "Production service and public site: UNCHANGED"
