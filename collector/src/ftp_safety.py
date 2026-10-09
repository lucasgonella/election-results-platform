"""Fail-closed transport checks. Only FTP metadata is inspected, never secrets."""
from __future__ import annotations

import ftplib
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit


SENSITIVE_PATHS = (
    '.election-publisher', '.election-publisher/hmac.key',
    '.election-publisher/ftp-config.json', 'includes',
    'public_html/api', 'public_html/api/election-publish.php', 'public_html/api/election-ftp-control.php',
)


def validate_inbox(value):
    if (not isinstance(value, str) or not re.fullmatch(r'/?[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*', value)
            or any(p.lower() in {'public_html', 'www', 'data', 'api', 'includes'} for p in value.split('/'))):
        raise ValueError('invalid_private_inbox')
    return value


def assert_transport_isolated(ftp):
    """A successful MLST on a protected path is an unconditional veto.

    A 550 does not prove an ACL: provider confinement approval remains required.
    Unsupported commands/transient errors also fail closed. No RETR/STOR occurs.
    """
    for path in SENSITIVE_PATHS:
        for candidate in (path, '/' + path):
            try:
                ftp.sendcmd('MLST ' + candidate)
            except ftplib.error_perm as error:
                if str(error).startswith('550'):
                    continue
                raise RuntimeError('ftp_isolation_unverifiable') from None
            except (ftplib.Error, OSError):
                raise RuntimeError('ftp_isolation_unverifiable') from None
            raise RuntimeError('ftp_control_exposed')


def validate_credentials_file(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('invalid_credentials_file')
    info = path.stat()
    if os.name == 'posix' and (stat.S_IMODE(info.st_mode) & 0o077 or info.st_uid != os.geteuid()):
        raise ValueError('unprotected_credentials_file')


def validate_runner_environment(env):
    if env.get('ELECTION_FTP_CUTOVER_APPROVED') != 'true':
        raise ValueError('cutover_not_approved')
    if env.get('LOCAWEB_FTP_ISOLATION_APPROVED') != 'true':
        raise ValueError('ftp_isolation_not_approved')
    if str(env.get('LOCAWEB_FTP_PORT', '21')) != '21':
        raise ValueError('ftp_port_must_be_21')
    for name in ['LOCAWEB_FTP_HOST', 'LOCAWEB_FTP_USER', 'LOCAWEB_FTP_PASSWORD',
                 'ELECTION_HMAC_KEY_FILE', 'ELECTION_FTP_CONTROL_URL', 'LIVE_PUBLISH_STATE_DIR']:
        if not env.get(name):
            raise ValueError('missing_runner_configuration')
    validate_inbox(env.get('LOCAWEB_FTP_ELECTION_INBOX_DIR'))
    control = urlsplit(env['ELECTION_FTP_CONTROL_URL'])
    if control.scheme != 'https' or not control.hostname or control.username or control.password or control.fragment:
        raise ValueError('https_required')
    validate_credentials_file(env.get('ELECTION_FTP_CREDENTIAL_FILE', '/etc/election-results-platform/secrets/ftp.env'))
