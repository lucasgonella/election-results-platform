"""Existing Goiás ETL writer: plain FTP 21, bounded reads, exact-byte verification.

Only goias-finance-data.yml invokes this writer. Preserve its established single
JSON destination. An uncertain STOR response is inspected, never blindly replayed.
The existing in-place data upload does not provide transactional activation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_BYTES = 16*1024*1024
PUBLIC = 'https://afgnet.com.br/eleicoes/goias/raio-x/data/go-2026.json'
DIRECTORY = 'public_html/eleicoes/goias/raio-x'
TRANSIENT = {6, 7, 18, 28, 52, 55, 56}


def _ftp(raw=None):
    host = os.environ['FTP_HOST']
    if not re.fullmatch('[A-Za-z0-9.-]+', host) or os.environ['FTP_DIR'] != DIRECTORY:
        raise ValueError('invalid_goias_ftp_destination')
    def token(value):
        if '\r' in value or '\n' in value:
            raise ValueError('invalid_ftp_credential_format')
        return '"'+value.replace('\\', '\\\\').replace('"', '\\"')+'"'
    with tempfile.TemporaryDirectory() as folder:
        netrc = Path(folder)/'credentials.netrc'
        with netrc.open('x') as stream:
            netrc.chmod(0o600)
            stream.write('machine '+host+' login '+token(os.environ['FTP_USER'])+
                         ' password '+token(os.environ['FTP_PASSWORD'])+'\n')
        command = ['curl', '--disable', '--silent', '--fail', '--proto', '=ftp', '--ftp-pasv',
                   '--connect-timeout', '15', '--max-time', '90' if raw is not None else '30',
                   '--max-filesize', str(MAX_BYTES), '--netrc-file', str(netrc), '--noproxy', '*']
        if raw is not None: command += ['--upload-file', '-']
        command += ['ftp://'+host+':21/'+DIRECTORY+'/data/go-2026.json']
        response = subprocess.run(command, input=raw, capture_output=True,
                                  timeout=100 if raw is not None else 40)
        if len(response.stdout) > MAX_BYTES: raise ValueError('oversized_goias_response')
        return response.returncode, response.stdout


def ftp_read():
    for attempt in range(3):
        code, raw = _ftp()
        if code == 0: return raw
        if code not in TRANSIENT or attempt == 2:
            raise RuntimeError('goias_ftp_read_failed_'+str(code))
        time.sleep(attempt+1)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('goias_redirect_refused')


def https_read():
    for attempt in range(3):
        try:
            with build_opener(NoRedirect).open(Request(PUBLIC, headers={
                    'Cache-Control': 'no-cache', 'Accept-Encoding': 'identity'}), timeout=30) as response:
                if response.status != 200 or response.geturl() != PUBLIC:
                    raise RuntimeError('invalid_goias_public_response')
                raw = response.read(MAX_BYTES+1)
                if len(raw) > MAX_BYTES: raise ValueError('oversized_goias_response')
                return raw
        except (OSError, EOFError):
            if attempt == 2: raise
            time.sleep(attempt+1)


def publish(path):
    raw = Path(path).read_bytes()
    if not 0 < len(raw) <= MAX_BYTES: raise ValueError('invalid_goias_size')
    data = json.loads(raw)
    if (data.get('scope') != 'GO' or data.get('year') != 2026
            or len(data.get('candidates', [])) <= 100 or not data.get('transfers')):
        raise ValueError('invalid_goias_dataset')
    from deploy.ssh_transport import selection
    if selection() == 'ssh':
        from deploy.ssh_finance import publish as ssh_publish
        return {**ssh_publish(raw, https_read), 'sha256':hashlib.sha256(raw).hexdigest(),
                'bytes':len(raw), 'candidates':len(data['candidates']), 'transfers':len(data['transfers']),
                'ssh_https_verified':True}
    if ftp_read() == raw and https_read() == raw:
        status, code = 'unchanged', 0
    else:
        code, _ = _ftp(raw)
        if code != 0 and code not in TRANSIENT:
            raise RuntimeError('goias_ftp_upload_failed_'+str(code))
        # A reset can occur after the complete STOR. Full FTP AND HTTPS bytes
        # establish its outcome; a partial upload remains a failure, not success.
        if ftp_read() != raw or https_read() != raw:
            raise RuntimeError('goias_publication_bytes_mismatch')
        status = 'reconciled_upload' if code else 'published'
    return {'status': status, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
            'candidates': len(data['candidates']), 'transfers': len(data['transfers']),
            'upload_returncode': code, 'ftp_https_verified': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(publish(args.file))); return 0
    except Exception as error:
        # Never print curl stderr, server responses, names or credential values.
        from deploy.frontend import error_report
        print(json.dumps({'status': 'failed', **error_report(error)})); return 1


if __name__ == '__main__':
    raise SystemExit(main())
