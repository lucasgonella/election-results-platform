#!/usr/bin/env bash
# Dedicated infrastructure for the explicitly requested national biometry panel.
set -euo pipefail
if [[ $EUID != 0 || $# != 2 || ! $2 =~ ^[a-f0-9]{40}$ ]]; then
  echo 'Usage as root: install-biometry.sh SOURCE_CHECKOUT CI_APPROVED_MAIN_SHA' >&2
  exit 2
fi
source_checkout=$1
approved_sha=$2
if [[ $(git -c safe.directory="$source_checkout" -C "$source_checkout" ls-remote origin refs/heads/main | cut -f1) != "$approved_sha" ]]; then
  echo 'Approved SHA must be current main' >&2
  exit 2
fi
if systemctl is-active --quiet election-biometry.service; then
  echo 'Stop only the dedicated biometry service before replacing its release' >&2
  exit 2
fi
for credential in actions.key known_hosts; do
  test -f "/etc/election-results-platform/ssh/$credential"
done
getent passwd electionbiometry >/dev/null || useradd --system --user-group --home-dir /var/lib/election-biometry --shell /usr/sbin/nologin electionbiometry
release_dir=/opt/election-biometry/releases/$approved_sha
if [[ ! -e $release_dir ]]; then
  install -d -m 0755 "$release_dir"
  git -c safe.directory="$source_checkout" -C "$source_checkout" archive "$approved_sha" | tar -x -C "$release_dir"
  chown -R root:root "$release_dir"
fi
if [[ ! -x /opt/election-biometry-venv/bin/python ]]; then
  python3 -m venv /opt/election-biometry-venv
fi
/opt/election-biometry-venv/bin/python -m pip --quiet --no-cache-dir install -r "$release_dir/deploy/biometry-requirements.txt"
install -d -o electionbiometry -g electionbiometry -m 0700 /var/lib/election-biometry
ln -s "$release_dir" /opt/election-biometry/current.new
mv -Tf /opt/election-biometry/current.new /opt/election-biometry/current
install -m 0644 "$release_dir/deploy/systemd/election-biometry.service" /etc/systemd/system/election-biometry.service
systemctl daemon-reload
systemctl enable --now election-biometry.service
systemctl show election-biometry.service -p Result -p ExecMainStatus -p User -p WorkingDirectory
