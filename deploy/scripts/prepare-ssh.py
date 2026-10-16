"""Materialize only a dedicated Actions SSH identity in the runner's temp dir."""
import os
from pathlib import Path
import subprocess


FINGERPRINT = 'SHA256:bahZf80pWXz9IHeBZcj5bspwnZnLfDFAaKJR7Vd+qM8'


def prepare():
    selected = os.environ.get('PUBLICATION_TRANSPORT', 'ftp')
    if selected == 'ftp': return
    if selected != 'ssh': raise ValueError('invalid_publication_transport')
    private = os.environ.get('LOCAWEB_SSH_PRIVATE_KEY', '')
    known = os.environ.get('LOCAWEB_SSH_KNOWN_HOSTS', '')
    if not private or not known: raise ValueError('dedicated_actions_ssh_secrets_required')
    root = Path(os.environ['RUNNER_TEMP']) / 'locaweb-ssh'
    root.mkdir(mode=0o700)
    for name, raw in [('identity', private), ('known_hosts', known)]:
        with (root/name).open('x') as stream:
            os.chmod(root/name, 0o600)
            stream.write(raw.rstrip() + '\n')
    result = subprocess.run(['ssh-keygen', '-lf', str(root/'known_hosts')], capture_output=True, timeout=10)
    if result.returncode or FINGERPRINT not in result.stdout.decode():
        raise ValueError('ssh_host_fingerprint_mismatch')
    result = subprocess.run(['ssh-keygen', '-y', '-P', '', '-f', str(root/'identity')], capture_output=True, timeout=10)
    if result.returncode: raise ValueError('ssh_private_key_unusable')
    with open(os.environ['GITHUB_ENV'], 'a') as stream:
        for key, name in [('LOCAWEB_SSH_IDENTITY_FILE', 'identity'), ('LOCAWEB_SSH_KNOWN_HOSTS_FILE', 'known_hosts')]:
            stream.write(key + '=' + str(root/name) + '\n')


if __name__ == '__main__':
    try: prepare()
    except Exception as error:
        # No key data, ssh-keygen output or environment in logs.
        print(str(error) if type(error) is ValueError else 'ssh_setup_failed')
        raise SystemExit(1)
