#!/usr/bin/env python3
"""Read-only SSH authentication probe for the Locaweb election publisher."""
import os
import subprocess
import tempfile
from pathlib import Path

OUTPUT = Path("/var/lib/election-zabbix/ssh-auth.txt")
SSH_KEY = "/var/lib/election-results-platform/.ssh/locaweb_publisher"
KNOWN_HOSTS = "/var/lib/election-results-platform/.ssh/known_hosts"

command = [
    "/usr/bin/ssh",
    "-i", SSH_KEY,
    "-o", f"UserKnownHostsFile={KNOWN_HOSTS}",
    "-o", "GlobalKnownHostsFile=/dev/null",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=8",
    "-o", "ConnectionAttempts=1",
    "-o", "StrictHostKeyChecking=yes",
    "-o", "IdentitiesOnly=yes",
    "-o", "NumberOfPasswordPrompts=0",
    "afgnet1@ftp.afgnet.com.br",
    "printf SSH_AUTH_OK",
]

try:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    healthy = result.returncode == 0 and result.stdout == "SSH_AUTH_OK"
except (subprocess.TimeoutExpired, OSError):
    healthy = False

value = "1\n" if healthy else "0\n"
fd, temporary = tempfile.mkstemp(prefix=".ssh-auth-", dir=str(OUTPUT.parent))
try:
    with os.fdopen(fd, "w") as f:
        f.write(value)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(temporary, 0o640)
    os.replace(temporary, OUTPUT)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
print(f"SSH_AUTH={int(healthy)}")
