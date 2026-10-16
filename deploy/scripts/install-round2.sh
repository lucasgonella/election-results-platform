#!/usr/bin/env bash
# Install only a reviewed, CI-approved main SHA. No first-round unit writes.
set -euo pipefail
if [[ $EUID != 0 || $# != 2 || ! $2 =~ ^[a-f0-9]{40}$ ]]; then
  echo 'Usage as root: install-round2.sh SOURCE_CHECKOUT APPROVED_MAIN_SHA' >&2
  exit 2
fi
source_checkout=$1
approved_sha=$2
if [[ $(git -c safe.directory="$source_checkout" -C "$source_checkout" ls-remote origin refs/heads/main | cut -f1) != "$approved_sha" ]]; then
  echo 'Approved SHA must be the current main commit' >&2
  exit 2
fi
if systemctl is-active --quiet election-round2.service; then
  echo 'Wait for the dedicated round-two cycle to finish before updating' >&2
  exit 2
fi
getent passwd electionround2 >/dev/null || useradd --system --user-group --home-dir /var/lib/election-round2 --shell /usr/sbin/nologin electionround2
install -d -m 0755 /opt/election-round2/releases
release_dir=/opt/election-round2/releases/$approved_sha
if [[ ! -e $release_dir ]]; then
  install -d -m 0755 "$release_dir"
  git -c safe.directory="$source_checkout" -C "$source_checkout" archive "$approved_sha" | tar -x -C "$release_dir"
  chown -R root:root "$release_dir"
fi
# Independent venv; never change the venv of the first-round services.
if [[ ! -x /opt/election-round2-venv/bin/python ]]; then
  python3 -m venv /opt/election-round2-venv
fi
/opt/election-round2-venv/bin/python -m pip --quiet --no-cache-dir install -r "$release_dir/collector/requirements.txt"
install -d -o electionround2 -g electionround2 -m 0700 /var/lib/election-round2
if [[ ! -e /etc/election-results-platform/round2.env ]]; then
  install -o root -g electionround2 -m 0640 "$release_dir/deploy/env/round2.env.example" /etc/election-results-platform/round2.env
fi
ln -s "$release_dir" /opt/election-round2/current.new
mv -Tf /opt/election-round2/current.new /opt/election-round2/current
install -m 0644 "$release_dir/deploy/systemd/election-round2.service" /etc/systemd/system/election-round2.service
install -m 0644 "$release_dir/deploy/systemd/election-round2.timer" /etc/systemd/system/election-round2.timer
for kind in monitor retention; do
  install -m 0644 "$release_dir/deploy/systemd/election-round2-$kind.service" "/etc/systemd/system/election-round2-$kind.service"
  install -m 0644 "$release_dir/deploy/systemd/election-round2-$kind.timer" "/etc/systemd/system/election-round2-$kind.timer"
done
if [[ -d /etc/zabbix/zabbix_agent2.d ]]; then
  install -m 0644 "$release_dir/deploy/zabbix/election-round2.conf" /etc/zabbix/zabbix_agent2.d/election-round2.conf
  if systemctl is-active --quiet zabbix-agent2; then zabbix_agent2 -R userparameter_reload; fi
fi
systemctl daemon-reload
# Full official discovery and collection with no FTP connection/activation.
(cd "$release_dir" && runuser -u electionround2 -- env PYTHONDONTWRITEBYTECODE=1 \
  /opt/election-round2-venv/bin/python -m collector.src.second_round_runner cycle \
  --dry-run --state /var/lib/election-round2/preflight)
systemctl start election-round2.service
systemctl enable --now election-round2.timer
systemctl enable --now election-round2-monitor.timer election-round2-retention.timer
systemctl start election-round2-monitor.service
systemctl show election-round2.service -p Result -p ExecMainStatus -p User -p WorkingDirectory
systemctl is-enabled election-round2.timer
systemctl list-timers election-round2.timer --no-pager
