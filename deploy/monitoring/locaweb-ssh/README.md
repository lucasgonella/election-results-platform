# Locaweb SSH authentication monitor (app01)

This directory versions the **already installed** read-only authentication probe on app01, plus its systemd and Zabbix Agent 2 configuration. Merging this documentation/code does **not** deploy or change production. No GitHub Actions job should install these files automatically.

## Purpose

Locaweb may keep TCP/22 open while the temporary SSH login window has expired. This monitor tests an actual non-interactive SSH login and remote `printf`, rather than TCP reachability or a publication attempt. It does not modify remote files and must not replace the first- and second-round publication-health checks.

Verified live on 2026-10-17: SSH result `1`, agent query succeeds, Zabbix item `51508` supported and freshness item `51509` reported 51 seconds. Discord action `9` was verified with a synthetic trigger; this does **not** prove the SSH-expiration alert itself has fired.

## Files and production destinations

| Repository file | app01 destination |
| --- | --- |
| `check-locaweb-ssh.py` | `/opt/election-monitoring/check-locaweb-ssh.py` |
| `election-ssh-auth.service` | `/etc/systemd/system/election-ssh-auth.service` |
| `election-ssh-auth.timer` | `/etc/systemd/system/election-ssh-auth.timer` |
| `election-ssh-auth.conf` | `/etc/zabbix/zabbix_agent2.d/election-ssh-auth.conf` |
| `election-ssh-freshness.conf` | `/etc/zabbix/zabbix_agent2.d/election-ssh-freshness.conf` |

The script uses the `electioncollector` service identity, the pinned host-key file `/var/lib/election-results-platform/.ssh/known_hosts`, the existing private key `/var/lib/election-results-platform/.ssh/locaweb_publisher`, and `afgnet1@ftp.afgnet.com.br`. **Do not commit or copy the real private key, known_hosts, or any `.env`, password, token, or other live state.** Check any host/user changes against the operational service configuration.

## Installation or restoration (manual, approved maintenance only)

1. Inspect local changes and current units first. Do not reset or overwrite the app01 checkout, its release symlinks, or journal/lock/pending files. Confirm no conflicting change is in progress.
2. Provision the existing `electioncollector` user, pinned known_hosts, matching SSH key, `zabbix` user and `/var/lib/election-zabbix` directory following the normal host baseline. On 2026-10-17, the directory was `electioncollector:zabbix` mode `2750`; each probe creates `ssh-auth.txt` mode `0640`. Verify readable by `zabbix` rather than weakening key permissions.
3. Compare each repository file with its production destination before installation. Only with explicit approval, copy the Python script to the above path (root:root, mode 0755), systemd units into `/etc/systemd/system/`, and the two Agent 2 files into `/etc/zabbix/zabbix_agent2.d/`.
4. Run `systemctl daemon-reload`, enable/start `election-ssh-auth.timer`, start `election-ssh-auth.service` once, and restart `zabbix-agent2` only in an agreed maintenance window. Validate `systemctl show election-ssh-auth.service -p Result -p ExecMainStatus`, `sudo -u zabbix cat /var/lib/election-zabbix/ssh-auth.txt`, and from monitor01 `zabbix_get -s 192.168.1.14 -k election.ssh.auth` and `... -k election.ssh.auth.age`.
5. Confirm in the Zabbix UI/API that both items collect over time and all three triggers are supported and OK; do not infer success from an initial `lastvalue=0` with `lastclock=0`.

## Zabbix configuration (manually provisioned on monitor01)

- Host `app01` (`hostid=10685`, passive interface `33`), item `51508`: `election.ssh.auth`, unsigned integer, 1m. `1` = login succeeded; `0` = login failed for **any** reason (window expiry, DNS, routing, host-key rejection, key issue, timeout).
- Item `51509`: `election.ssh.auth.age`, unsigned integer, seconds, 1m; derives age of the last probe file modification.
- Trigger `25551`: `max(/app01/election.ssh.auth,#3)=0` (three consecutive failed readings).
- Trigger `25552`: `nodata(/app01/election.ssh.auth,5m)=1` (Zabbix polling stops).
- Trigger `25553`: `last(/app01/election.ssh.auth.age)>180` (probe file stops updating).
- All three triggers use `project=elections-2026` and `component=ssh-auth`. Election events route through action `9`, Discord media type `39`, Admin user `1`; general actions `7` and `8` exclude `project=elections-2026`. Check all these actual settings instead of blindly creating duplicates.

**Important:** a stale file can still contain `1`, which is why the freshness check exists. Items `51490`–`51506` and actual publisher/collection state must still be monitored: a successful SSH login does not establish a successful publish. Missing JSON transport metrics must never be translated to zero.

## Diagnostics and rollback

- Service/timer: `systemctl status election-ssh-auth.service election-ssh-auth.timer`, `journalctl -u election-ssh-auth.service --since '15 minutes ago'`.
- Agent: `zabbix_get -s 192.168.1.14 -k election.ssh.auth` and `zabbix_get -s 192.168.1.14 -k election.ssh.auth.age`.
- Network alone is insufficient: a reachable port 22 does not imply usable SSH. Do not use `StrictHostKeyChecking=no`, disable host-key checking, overwrite pinned keys or dump secret environment values.
- Expired SSH is re-enabled manually in the Locaweb panel; **no automatic FTP fallback or forced retry**. Follow `docs/election-day-ssh-operations-2026.md` for remote state reconciliation and guardrails.
- For rollback of **this probe only**, first disable the three probe-specific Zabbix triggers (`25551`, `25552`, `25553`) to avoid false pages, then stop/disable `election-ssh-auth.timer`, restore the backed-up Agent 2 configuration and service/unit versions, `systemctl daemon-reload`, and reload Agent 2 in a maintenance window. Do not stop election publication timers or delete results, credentials, locks, snapshots, or journals. Revert Git changes separately; Git merge alone is not a deployment.
