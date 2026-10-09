#!/usr/bin/env bash
set -Eeuo pipefail
REPO="$(pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export HTTPS_RELEASE_BASE="$TMP/releases"
export HOME="$TMP"
rev1="1111111111111111111111111111111111111111"
rev2="2222222222222222222222222222222222222222"
bash "$REPO/deploy/scripts/release-https-staging.sh" "$rev1"
test "$(readlink "$HTTPS_RELEASE_BASE/current")" = "$rev1"
bash "$REPO/deploy/scripts/release-https-staging.sh" "$rev2"
test "$(readlink "$HTTPS_RELEASE_BASE/previous")" = "$rev1"
bash "$REPO/deploy/scripts/rollback-https-staging.sh"
test "$(readlink "$HTTPS_RELEASE_BASE/current")" = "$rev1"
test "$(readlink "$HTTPS_RELEASE_BASE/previous")" = "$rev2"
(cd "$HTTPS_RELEASE_BASE/current" && sha256sum -c SHA256SUMS)
echo "ISOLATED CD RELEASE AND ROLLBACK TESTS: OK"
