"""Bounded static frontend publication. FTP transfers; HTTPS only verifies.

This intentionally does not use or weaken the election-data trust boundary.
No PHP, JSON data, credentials, server-side executor or directory deletion.
Independent HTML entrypoints use individual renames, not a site-wide transaction.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ftplib
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import socket
import shutil
import subprocess
import tempfile
import time
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
SUFFIXES = {'.html', '.css', '.js', '.svg', '.png', '.ico', '.jpg', '.jpeg', '.webp', '.woff', '.woff2'}
MAX_BYTES = 16 * 1024 * 1024
PRIVATE = '/frontend-deploy'
PACK_FORMAT = 1
CONTROL_RETRIES = 0
CONTROL_OPERATIONS = {'connect', 'login', 'pwd', 'metadata', 'stor', 'retr', 'rename'}


def control_failure(error, operation):
    """Attach a fixed operation label, never paths, replies or credentials."""
    if operation in CONTROL_OPERATIONS and not getattr(error, 'frontend_operation', None):
        error.frontend_operation = operation
    return error


class PassiveFTP(ftplib.FTP):
    """Prefer EPSV, as curl does; PASV only for IPv4 servers lacking EPSV."""
    def makepasv(self):
        try:
            return ftplib.parse229(self.sendcmd('EPSV'), self.sock.getpeername())
        except ftplib.error_perm as error:
            if self.af != socket.AF_INET or not str(error).startswith(('500', '502', '522')):
                raise
            return super().makepasv()


def error_report(error):
    """Only controlled codes, numeric errno and types; no server messages/credentials."""
    result = {'error_type': type(error).__name__}
    transport_code = getattr(error, 'transport_error_code', None)
    if isinstance(transport_code, str) and re.fullmatch('[a-z_]{1,80}', transport_code):
        result.update(transport='ssh_rsync', error_code=transport_code)
        op = getattr(error, 'transport_operation', None)
        if op in {'hello','metadata','read','mkdir','reserve','hash','cached','cache','commit','rename','unlink','rmdir','chunk','reserve_batch','cache_batch','promote'}:
            result['transport_operation'] = op
        number = getattr(error, 'remote_errno', None)
        if isinstance(number, int): result['remote_errno'] = number
        kind = getattr(error, 'remote_error_type', None)
        if isinstance(kind, str) and re.fullmatch('[A-Za-z]{1,40}',kind): result['remote_error_type'] = kind
        attempts = getattr(error, 'connection_attempts', None)
        if type(attempts) is int and 1 <= attempts <= 3: result['connection_attempts'] = attempts
    operation = getattr(error, 'frontend_operation', None)
    if isinstance(operation, str) and operation in CONTROL_OPERATIONS:
        result['ftp_operation'] = operation
    if type(error) in {ValueError, RuntimeError} and re.fullmatch('[a-z][a-z0-9_]{0,100}', str(error)):
        result['error_code'] = str(error)
    if isinstance(error, OSError) and isinstance(error.errno, int):
        result['errno'] = error.errno
    if isinstance(error, ftplib.Error) and re.match(r'^\d{3}', str(error)):
        result['ftp_code'] = str(error)[:3]
    if isinstance(error, ExceptionGroup):
        result['causes'] = [error_report(cause) for cause in error.exceptions]
    return result


def curl_transfer(path, raw=None):
    """Native passive FTP data channel, matching the existing financial writer.

    Credentials stay in a 0600 netrc, never argv/URLs or subprocess output.
    No implicit curlrc, TLS, upload retry, directory creation or redirects.
    """
    checker = Transport(None)
    checker.allowed(path)
    if raw is not None:
        if not path.endswith('.upload'):
            raise ValueError('native_upload_requires_temporary')
        checker.writable(path.removesuffix('.upload'))
    executable = shutil.which('curl')
    host = os.environ['LOCAWEB_FTP_HOST']
    if not executable or not re.fullmatch('[A-Za-z0-9.-]+', host):
        raise RuntimeError('native_ftp_unavailable')
    def netrc_token(value):
        if '\r' in value or '\n' in value:
            raise ValueError('invalid_ftp_credential_format')
        return '"'+value.replace('\\', '\\\\').replace('"', '\\"')+'"'
    with tempfile.TemporaryDirectory() as directory:
        netrc = Path(directory)/'credentials.netrc'
        with netrc.open('x', encoding='utf-8') as stream:
            os.chmod(netrc, 0o600)
            stream.write('machine '+host+' login '+netrc_token(os.environ['LOCAWEB_FTP_USER'])+
                         ' password '+netrc_token(os.environ['LOCAWEB_FTP_PASSWORD'])+'\n')
        command = [executable, '--disable', '--fail', '--silent', '--show-error', '--proto', '=ftp',
                   '--ftp-pasv', '--max-time', '90', '--connect-timeout', '20', '--max-filesize', str(MAX_BYTES),
                   '--netrc-file', str(netrc), '--noproxy', '*']
        if raw is not None:
            command += ['--upload-file', '-']
        command += ['ftp://'+host+':21/'+quote(path.lstrip('/'), safe='/')]
        response = subprocess.run(command, input=raw, capture_output=True, timeout=100)
        if response.returncode:
            raise RuntimeError('native_ftp_error_'+str(response.returncode))
        if len(response.stdout) > MAX_BYTES:
            raise RuntimeError('oversized_ftp_file')
        return response.stdout


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)+'\n').encode()


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate_json_key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def revision(value):
    if not re.fullmatch('[a-f0-9]{40}', value):
        raise ValueError('invalid_commit')
    return value


def static_path(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or path.as_posix() != name or '\\' in name
            or any(not re.fullmatch('[A-Za-z0-9_-][A-Za-z0-9_.-]*', p) or p.startswith('.')
                   or p in {'data', 'goias', 'node_modules', 'frontend-releases'} for p in path.parts)
            or path.suffix.lower() not in SUFFIXES):
        raise ValueError('unsafe_static_path')
    return name


def target(component):
    configs = json.loads((ROOT/'deploy/frontend-targets.json').read_text())
    if component not in {'portal', 'raio-x'}:
        raise ValueError('invalid_component')
    result = configs[component]
    expected = '/public_html/eleicoes' + ('/goias/raio-x' if component == 'raio-x' else '')
    if result['ftp_root'] != expected or result['url'] != 'https://afgnet.com.br'+expected.removeprefix('/public_html')+'/':
        raise ValueError('invalid_fixed_destination')
    if component == 'raio-x' and os.environ.get('LOCAWEB_FTP_GOIAS_DIR', expected.lstrip('/')).strip('/') != expected.strip('/'):
        raise ValueError('goias_destination_mismatch')
    if result['entrypoints'] != (['composicao.html', 'index.html'] if component == 'portal' else ['index.html']):
        raise ValueError('invalid_entrypoints')
    return result


class HTMLCheck(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.doctype = False
        self.tags = set()
        self.inline_js = []
        self.inline_css = []
        self.capture = None

    def handle_decl(self, decl):
        self.doctype |= decl.lower() == 'doctype html'

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)
        keys = [key for key, _ in attrs]
        if len(keys) != len(set(keys)):
            raise ValueError('duplicate_html_attribute')
        if tag == 'base':
            raise ValueError('base_tag_not_supported')
        if tag in {'script', 'style'} and not dict(attrs).get('src'):
            self.capture = tag
        for key, value in attrs:
            if key in {'src', 'href'} and value and value.lower().startswith(('javascript:', 'file:')):
                raise ValueError('unsafe_html_reference')

    def handle_endtag(self, tag):
        if tag == self.capture:
            self.capture = None

    def handle_data(self, data):
        if self.capture == 'script':
            self.inline_js.append(data)
        elif self.capture == 'style':
            self.inline_css.append(data)


def check_css(text):
    # tinycss2 is installed by frontend CI and deploy. It parses real CSS tokens.
    import tinycss2
    def walk(tokens):
        for token in tokens:
            if token.type == 'error':
                raise ValueError('invalid_css')
            for attr in ('content', 'arguments', 'prelude'):
                nested = getattr(token, attr, None)
                if nested is not None:
                    walk(nested)
    walk(tinycss2.parse_stylesheet(text, skip_comments=True, skip_whitespace=True))


def check_js(text):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder)/'check.js'
        path.write_text(text, encoding='utf-8')
        subprocess.run(['node', '--check', str(path)], check=True, capture_output=True)


def build(component, commit, output, *, root=ROOT, validate=True):
    commit = revision(commit)
    cfg = target(component)
    source = root/cfg['source']
    files = {}
    for path in sorted(source.rglob('*')):
        parts = path.relative_to(source).parts
        if any(p in {'data', 'goias', 'node_modules', 'frontend-releases'} or p.startswith('.') for p in parts):
            continue
        if path.is_symlink():
            raise ValueError('symlink_in_source')
        if not path.is_file() or path.suffix.lower() not in SUFFIXES:
            continue
        name = static_path(path.relative_to(source).as_posix())
        raw = path.read_bytes()
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError('invalid_file_size')
        files[name] = raw
    if not set(cfg['entrypoints']).issubset(files):
        raise ValueError('missing_entrypoint')
    source_sha256 = digest(encode({'format': PACK_FORMAT, 'component': component,
                                  'files': {name: digest(raw) for name, raw in files.items()}}))
    base = urlsplit(cfg['url']).path
    for name, raw in list(files.items()):
        suffix = PurePosixPath(name).suffix.lower()
        if suffix == '.html':
            text = raw.decode('utf-8')
            parser = HTMLCheck()
            parser.feed(text)
            parser.close()
            if not parser.doctype or not {'html', 'head', 'body'}.issubset(parser.tags):
                raise ValueError('invalid_html_document')
            if validate:
                check_js('\n'.join(parser.inline_js))
                for css in parser.inline_css:
                    check_css(css)
            def replace(match):
                attribute, quote, url = match.groups()
                normalized = urljoin(name, url)
                local = normalized.split('?', 1)[0].split('#', 1)[0]
                if local in files:
                    url = base+'frontend-releases/'+commit+'/'+normalized
                elif url and not url.startswith(('/', '#', '//')) and not urlsplit(url).scheme:
                    url = urljoin(base+name, url)
                return attribute+'='+quote+url+quote
            text = re.sub(r'(src|href)=([\"\'])([^\"\']*)\2', replace, text)
            # Relative inline fetches (notably Raio-X data) remain rooted in the
            # stable component namespace when immutable HTML is opened directly.
            text = text.replace('"./data/', '"'+base+'data/').replace("'./data/", "'"+base+'data/')
            files[name] = text.encode('utf-8')
        elif suffix == '.js' and validate:
            check_js(raw.decode('utf-8'))
        elif suffix == '.css' and validate:
            check_css(raw.decode('utf-8'))
    manifest = {'schema': 1, 'component': component, 'commit': commit, 'source_sha256': source_sha256,
                'files': {name: {'size': len(raw), 'sha256': digest(raw)} for name, raw in files.items()}}
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        path = output/'files'/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    (output/'artifact.json').write_bytes(encode(manifest))
    return manifest


def validate_package(directory, component):
    if directory.is_symlink() or any(p.is_symlink() for p in directory.rglob('*')):
        raise ValueError('unsafe_package')
    raw = (directory/'artifact.json').read_bytes()
    manifest = decode(raw)
    validate_manifest(manifest, component)
    expected = {'artifact.json'}
    for name, entry in manifest['files'].items():
        value = (directory/'files'/name).read_bytes()
        verify_bytes(value, entry)
        expected.add('files/'+name)
    if {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()} != expected:
        raise ValueError('unexpected_package_file')
    return manifest


def validate_manifest(manifest, component):
    if manifest.get('schema') != 1 or manifest.get('component') != component:
        raise ValueError('invalid_manifest')
    revision(manifest['commit'])
    if 'source_sha256' in manifest and not re.fullmatch('[a-f0-9]{64}', manifest['source_sha256']):
        raise ValueError('invalid_source_hash')
    if not isinstance(manifest.get('files'), dict) or not 1 <= len(manifest['files']) <= 500:
        raise ValueError('invalid_inventory')
    for name, entry in manifest['files'].items():
        static_path(name)
        if not re.fullmatch('[a-f0-9]{64}', entry['sha256']) or not isinstance(entry['size'], int) or not 0 < entry['size'] <= MAX_BYTES:
            raise ValueError('invalid_inventory')
    if not set(target(component)['entrypoints']).issubset(manifest['files']):
        raise ValueError('missing_entrypoint')


def verify_bytes(value, entry):
    if len(value) != entry['size'] or digest(value) != entry['sha256']:
        raise RuntimeError('checksum_mismatch')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('redirect_refused')


def http_read(url):
    if not url.startswith('https://afgnet.com.br/eleicoes/'):
        raise ValueError('invalid_public_url')
    with build_opener(NoRedirect).open(Request(url, headers={'Cache-Control': 'no-cache', 'Accept-Encoding': 'identity'}), timeout=30) as response:
        if response.status != 200 or response.geturl() != url:
            raise RuntimeError('unexpected_http_response')
        raw = response.read(MAX_BYTES+1)
        if len(raw) > MAX_BYTES:
            raise RuntimeError('oversized_response')
        return raw


class Transport:
    """Plain passive FTP, fixed paths only, read-after-write SHA verification."""
    def __init__(self, ftp, *, reconnect=None, transfer=None):
        self.ftp = ftp
        self.reconnect = reconnect
        self.reconciled_transfers = 0
        self.transfer = transfer

    def data_transfer(self, path, raw=None):
        # One connection at a time; a long native transfer cannot poison an
        # idle Python control socket. Reopen before integrity checks/activation.
        self.ftp.close()
        try:
            result = self.transfer(self.allowed(path), raw)
        except Exception as original:
            control_failure(original, 'stor' if raw is not None else 'retr')
            try:
                self.ftp = self.reconnect()
            except Exception as reconnect_error:
                raise ExceptionGroup('native_transfer_reconnect_failed', [original, reconnect_error]) from None
            raise
        else:
            self.ftp = self.reconnect()
            return result

    def allowed(self, path):
        if any(c in path for c in ['\r', '\n', '\\']) or '..' in PurePosixPath(path).parts:
            raise ValueError('unsafe_remote_path')
        if not path.startswith(PRIVATE+'/') and not any(path.startswith(target(c)['ftp_root']+'/') for c in ['portal', 'raio-x']):
            raise ValueError('unsafe_remote_path')
        return path

    def metadata(self, path):
        self.allowed(path)
        try:
            reply = self.ftp.sendcmd('MLST '+path)
        except ftplib.error_perm as error:
            if str(error).startswith('550'):
                return None
            control_failure(error, 'metadata')
            raise
        except Exception as error:
            control_failure(error, 'metadata')
            raise
        rows = [line.strip().split(' ', 1)[0] for line in reply.splitlines() if 'type=' in line.lower()]
        if len(rows) != 1:
            raise RuntimeError('ambiguous_metadata')
        facts = dict(field.lower().split('=', 1) for field in rows[0].split(';') if '=' in field)
        if facts.get('type') not in {'file', 'dir'}:
            raise RuntimeError('symlink_or_unknown_type')
        return facts

    def writable(self, path):
        self.allowed(path)
        for component in ['raio-x', 'portal']:
            cfg = target(component)
            if path in {cfg['ftp_root']+'/'+name for name in cfg['entrypoints']}:
                return path
            prefix = cfg['ftp_root']+'/frontend-releases/'
            if path.startswith(prefix):
                version, separator, name = path[len(prefix):].partition('/')
                revision(version)
                if not separator:
                    raise ValueError('invalid_asset_destination')
                static_path(name)
                return path
            prefix = PRIVATE+'/'+component+'/'
            if path.startswith(prefix):
                relative = path[len(prefix):]
                if relative in {'current.json', 'pending.json'} or re.fullmatch('versions/[a-f0-9]{40}\\.json', relative):
                    return path
                match = re.fullmatch('transactions/([a-z0-9-]{1,90})/(journal\\.json|before/(.+))', relative)
                if match and (match.group(2) == 'journal.json' or match.group(3) in cfg['entrypoints']):
                    return path
                raise ValueError('invalid_private_destination')
        raise ValueError('protected_destination')

    def read(self, path, *, optional=False):
        meta = self.metadata(path)
        if meta is None and optional:
            return None
        if meta is None or meta['type'] != 'file':
            raise RuntimeError('missing_regular_file')
        if self.transfer:
            if int(meta.get('size', str(MAX_BYTES+1))) > MAX_BYTES:
                raise RuntimeError('oversized_ftp_file')
            return self.data_transfer(path)
        out = bytearray()
        def receive(chunk):
            out.extend(chunk)
            if len(out) > MAX_BYTES:
                raise RuntimeError('oversized_ftp_file')
        self.ftp.retrbinary('RETR '+self.allowed(path), receive)
        return bytes(out)

    def directory(self, path):
        self.allowed(path+'/')
        meta = self.metadata(path+'/')
        if meta is not None:
            if meta['type'] != 'dir':
                raise RuntimeError('not_directory')
            return
        parent = str(PurePosixPath(path).parent)
        if parent not in {'/', '/public_html', '/public_html/eleicoes', '/public_html/eleicoes/goias', '/public_html/eleicoes/goias/raio-x'}:
            self.directory(parent)
        self.ftp.mkd(path)
        if self.metadata(path+'/')['type'] != 'dir':
            raise RuntimeError('directory_not_created')

    def put(self, path, raw, *, replace=False):
        self.writable(path)
        old = self.read(path, optional=True)
        if old is not None and not replace:
            if old != raw:
                raise RuntimeError('immutable_collision')
            return
        # An interrupted process may leave a versioned asset temporary behind.
        # A new attempt never adopts, overwrites or deletes that unknown file.
        # Final paths remain immutable; only this call's fresh temporary can be
        # reconciled after a lost response. Stable entrypoints/private metadata
        # retain their existing collision gate and journal recovery protocol.
        temporary = path+'.upload'
        if '/frontend-releases/' in path:
            asset = PurePosixPath(path)
            temporary = str(asset.with_name(asset.stem+'.'+secrets.token_hex(16)+asset.suffix))+'.upload'
        if self.metadata(temporary) is not None:
            raise RuntimeError('temporary_collision')
        self.directory(str(PurePosixPath(path).parent))
        try:
            if self.transfer:
                self.data_transfer(temporary, raw)
            else:
                self.ftp.storbinary('STOR '+temporary, io.BytesIO(raw))
            if self.read(temporary) != raw:
                raise RuntimeError('transfer_integrity_error')
            self._rename(temporary, path)
            if self.read(path) != raw:
                raise RuntimeError('rename_integrity_error')
        except Exception as original:
            # A lost FTP completion response does not imply a partial upload.
            # Reconnect once, verify actual bytes, and never replay STOR blindly.
            if self.reconnect and (isinstance(original, (OSError, EOFError)) or
                                   isinstance(original, RuntimeError) and str(original).startswith('native_ftp_error_')):
                # An FTP RNTO timeout may have committed the rename. Probe
                # destination on a fresh control channel before trying RNTO
                # again. Retry only bounded transport failures; never repeat STOR.
                for attempt in range(3):
                    try:
                        self.ftp.close()
                        self.ftp = self.reconnect()
                        current = self.read(path, optional=True)
                        if current == raw:
                            self.reconciled_transfers += 1
                            return
                        pending = self.read(temporary, optional=True)
                        if pending != raw:
                            raise RuntimeError('transfer_not_reconciled' if pending is None else 'transfer_integrity_error')
                        if current != old:
                            raise RuntimeError('external_writer_detected')
                        self._rename(temporary, path)
                        if self.read(path) != raw:
                            raise RuntimeError('rename_integrity_error')
                        self.reconciled_transfers += 1
                        return
                    except (OSError, EOFError) as reconciliation_error:
                        if attempt == 2:
                            original = ExceptionGroup('transfer_reconciliation_failed', [original, reconciliation_error])
                    except Exception as reconciliation_error:
                        original = ExceptionGroup('transfer_reconciliation_failed', [original, reconciliation_error])
                        break
            # Remove only the temporary file created here, never a collision.
            try:
                if self.metadata(temporary) is not None:
                    self.ftp.delete(temporary)
            except Exception as cleanup_error:
                raise ExceptionGroup('upload_cleanup_failed', [original, cleanup_error]) from None
            raise original

    def _rename(self, temporary, destination):
        self.allowed(temporary)
        self.writable(destination)
        parent = str(PurePosixPath(destination).parent)
        if str(PurePosixPath(temporary).parent) != parent:
            raise ValueError('cross_directory_rename_forbidden')
        try:
            # Keep RNFR/RNTO below the hosting's long absolute-path failure.
            # Full guarded paths still identify the files; only the wire command
            # is relative to a verified directory. No retry/replay is added here.
            self.ftp.cwd('/')
            for component in PurePosixPath(parent).parts[1:]: self.ftp.cwd(component)
            if self.ftp.pwd().rstrip('/') != parent.rstrip('/'):
                raise RuntimeError('ftp_rename_directory_mismatch')
            result = self.ftp.rename(PurePosixPath(temporary).name, PurePosixPath(destination).name)
            self.ftp.cwd('/')
            return result
        except Exception as error:
            control_failure(error, 'rename')
            raise

    @contextmanager
    def lock(self, component):
        for other in ['portal', 'raio-x']:
            if self.metadata(PRIVATE+'/'+other+'/lock/') is not None:
                raise RuntimeError('frontend_requires_recovery')
        base = PRIVATE+'/'+component
        self.directory(base)
        # Exclusive MKD, rather than flock on the NFS client. No stale lock
        # stealing. An interrupted client leaves the lock for explicit recovery.
        lock = base+'/lock'
        self.ftp.mkd(lock)
        completed = False
        try:
            yield
            completed = True
        finally:
            if completed:
                self.ftp.rmd(lock)


def state_path(component):
    return PRIVATE+'/'+component+'/current.json'


def verify_public(manifest, *, http=http_read, live=False):
    cfg = target(manifest['component'])
    urls = []
    for name, entry in manifest['files'].items():
        url = cfg['url']+'frontend-releases/'+manifest['commit']+'/'+name
        verify_bytes(http(url), entry)
        urls.append(url)
    if live:
        for name in cfg['entrypoints']:
            url = cfg['url']+name
            verify_bytes(http(url), manifest['files'][name])
            urls.append(url)
        # Verify DirectoryIndex as well, not just the explicit index.html.
        verify_bytes(http(cfg['url']), manifest['files']['index.html'])
        urls.append(cfg['url'])
    return urls


def restore(transport, journal, *, http=http_read):
    component = journal['component']
    cfg = target(component)
    if not re.fullmatch('[a-z0-9-]{1,90}', journal['transaction']):
        raise RuntimeError('invalid_backup_transaction')
    if set(journal['before']) != set(cfg['entrypoints']):
        raise RuntimeError('invalid_backup_inventory')
    for name, entry in journal['before'].items():
        backup = PRIVATE+'/'+component+'/transactions/'+journal['transaction']+'/before/'+name
        raw = transport.read(backup)
        verify_bytes(raw, entry)
        transport.put(cfg['ftp_root']+'/'+name, raw, replace=True)
        verify_bytes(http(cfg['url']+name), entry)
    verify_bytes(http(cfg['url']), journal['before']['index.html'])
    prior = journal['previous_state']
    transport.put(state_path(component), encode(prior), replace=True)


def activate(transport, manifest, contents, transaction, *, http=http_read, skip_unchanged=True):
    """Prepare/verify assets, backup every entrypoint, journal, replace, verify.

    All original entrypoints stay in place until every immutable asset is public.
    Failure compensates root entrypoints, retaining journal/lock if recovery fails.
    """
    component = manifest['component']
    cfg = target(component)
    if not re.fullmatch('[a-z0-9-]{1,90}', transaction):
        raise ValueError('invalid_transaction')
    validate_manifest(manifest, component)
    private = PRIVATE+'/'+component
    previous_raw = transport.read(state_path(component), optional=True)
    previous = decode(previous_raw) if previous_raw else {'schema': 1, 'commit': None, 'manifest': None}
    if previous.get('commit') == manifest['commit']:
        if previous.get('manifest') != manifest:
            raise RuntimeError('immutable_version_conflict')
        return {'status': 'unchanged', 'component': component, 'commit': manifest['commit'],
                'files': [], 'urls': verify_public(manifest, http=http, live=True)}
    prior_manifest = previous.get('manifest')
    if skip_unchanged and manifest.get('source_sha256') and prior_manifest and prior_manifest.get('source_sha256') == manifest['source_sha256']:
        validate_manifest(prior_manifest, component)
        if previous.get('commit') != prior_manifest['commit']:
            raise RuntimeError('current_version_mismatch')
        return {'status': 'unchanged', 'component': component, 'commit': prior_manifest['commit'],
                'requested_commit': manifest['commit'], 'reason': 'identical_component_source',
                'files': [], 'urls': verify_public(prior_manifest, http=http, live=True)}
    before = {}
    for name in cfg['entrypoints']:
        raw = transport.read(cfg['ftp_root']+'/'+name)
        if http(cfg['url']+name) != raw:
            raise RuntimeError('baseline_http_ftp_mismatch')
        before[name] = {'size': len(raw), 'sha256': digest(raw)}
        transport.put(private+'/transactions/'+transaction+'/before/'+name, raw)
    journal = {'schema': 1, 'component': component, 'transaction': transaction, 'before': before,
               'previous_state': previous, 'manifest': manifest, 'status': 'prepared'}
    journal_path = private+'/transactions/'+transaction+'/journal.json'
    transport.put(journal_path, encode(journal))
    # Resume/rollback never trusts path strings from a uploaded plan.
    transport.put(private+'/pending.json', encode(journal), replace=True)
    try:
        for name, entry in manifest['files'].items():
            raw = contents[name]
            verify_bytes(raw, entry)
            transport.put(cfg['ftp_root']+'/frontend-releases/'+manifest['commit']+'/'+name, raw)
        verify_public(manifest, http=http)
        for name in cfg['entrypoints']:
            if digest(transport.read(cfg['ftp_root']+'/'+name)) != before[name]['sha256']:
                raise RuntimeError('external_writer_detected')
            transport.put(cfg['ftp_root']+'/'+name, contents[name], replace=True)
        urls = verify_public(manifest, http=http, live=True)
        current = {'schema': 1, 'commit': manifest['commit'], 'manifest': manifest,
                   'previous_commit': previous.get('commit'), 'transaction': transaction,
                   'bootstrap_transaction': previous.get('bootstrap_transaction', transaction)}
        transport.put(private+'/versions/'+manifest['commit']+'.json', encode(manifest))
        transport.put(state_path(component), encode(current), replace=True)
        journal['status'] = 'published'
        transport.put(journal_path, encode(journal), replace=True)
        transport.put(private+'/pending.json', encode({'status': 'complete'}), replace=True)
    except Exception as original:
        try:
            restore(transport, journal, http=http)
            transport.put(private+'/pending.json', encode({'status': 'restored'}), replace=True)
        except Exception as recovery_error:
            raise ExceptionGroup('activation_recovery_failed', [original, recovery_error]) from None
        raise
    return {'status': 'published', 'component': component, 'commit': manifest['commit'],
            'files': list(manifest['files']), 'urls': urls, 'transaction': transaction,
            'activation': 'individual_entrypoint_renames', 'multinode_guarantee': False}


def recover(transport, component, *, http=http_read):
    """Explicit manual recovery: requires abandoned lock and verified pending."""
    lock = PRIVATE+'/'+component+'/lock'
    if transport.metadata(lock+'/') is None:
        raise RuntimeError('no_abandoned_lock')
    journal = decode(transport.read(PRIVATE+'/'+component+'/pending.json'))
    if journal.get('status') == 'prepared':
        if not re.fullmatch('[a-z0-9-]{1,90}', journal['transaction']) or journal.get('component') != component:
            raise RuntimeError('invalid_pending_journal')
        restore(transport, journal, http=http)
        transport.put(PRIVATE+'/'+component+'/pending.json', encode({'status': 'restored'}), replace=True)
    elif journal.get('status') not in {'complete', 'restored'}:
        raise RuntimeError('unknown_recovery_state')
    transport.ftp.rmd(lock)
    return {'status': 'recovered', 'component': component}


def rollback(transport, component, version, transaction, *, http=http_read):
    current = decode(transport.read(state_path(component)))
    selected = current.get('previous_commit') if version == 'previous' else revision(version)
    if selected is None:
        bootstrap = current['bootstrap_transaction']
        if not re.fullmatch('[a-z0-9-]{1,90}', bootstrap):
            raise RuntimeError('invalid_bootstrap_transaction')
        original = decode(transport.read(PRIVATE+'/'+component+'/transactions/'+bootstrap+'/journal.json'))
        if not re.fullmatch('[a-z0-9-]{1,90}', transaction):
            raise ValueError('invalid_transaction')
        cfg = target(component)
        before = {}
        for name in cfg['entrypoints']:
            raw = transport.read(cfg['ftp_root']+'/'+name)
            if http(cfg['url']+name) != raw:
                raise RuntimeError('baseline_http_ftp_mismatch')
            before[name] = {'size': len(raw), 'sha256': digest(raw)}
            transport.put(PRIVATE+'/'+component+'/transactions/'+transaction+'/before/'+name, raw)
        journal = {'schema': 1, 'component': component, 'transaction': transaction,
                   'before': before, 'previous_state': current, 'status': 'prepared'}
        path = PRIVATE+'/'+component+'/transactions/'+transaction+'/journal.json'
        transport.put(path, encode(journal))
        transport.put(PRIVATE+'/'+component+'/pending.json', encode(journal), replace=True)
        try:
            restore(transport, original, http=http)
            journal['status'] = 'restored_bootstrap'
            transport.put(path, encode(journal), replace=True)
            transport.put(PRIVATE+'/'+component+'/pending.json', encode({'status':'complete'}), replace=True)
        except Exception as original:
            try:
                restore(transport, journal, http=http)
                transport.put(PRIVATE+'/'+component+'/pending.json', encode({'status':'restored'}), replace=True)
            except Exception as recovery_error:
                raise ExceptionGroup('rollback_recovery_failed', [original, recovery_error]) from None
            raise
        return {'status': 'restored_bootstrap', 'component': component, 'commit': None}
    manifest = decode(transport.read(PRIVATE+'/'+component+'/versions/'+selected+'.json'))
    validate_manifest(manifest, component)
    if manifest['commit'] != selected:
        raise RuntimeError('version_mismatch')
    cfg = target(component)
    contents = {name: transport.read(cfg['ftp_root']+'/frontend-releases/'+selected+'/'+name) for name in manifest['files']}
    return activate(transport, manifest, contents, transaction, http=http, skip_unchanged=False)


def status(transport, component, *, http=http_read):
    """Read-only status; never creates a directory or takes a remote lock."""
    current = decode(transport.read(state_path(component)))
    manifest = current.get('manifest')
    if not manifest:
        raise RuntimeError('no_published_version')
    validate_manifest(manifest, component)
    if current.get('commit') != manifest['commit']:
        raise RuntimeError('current_version_mismatch')
    pending_raw = transport.read(PRIVATE+'/'+component+'/pending.json', optional=True)
    pending = decode(pending_raw) if pending_raw else {}
    return {'status': 'verified', 'component': component, 'commit': manifest['commit'],
            'files': list(manifest['files']), 'previous_commit': current.get('previous_commit'),
            'pending': pending.get('status'),
            'lock_present': transport.metadata(PRIVATE+'/'+component+'/lock/') is not None,
            'urls': verify_public(manifest, http=http, live=True)}


def connect():
    global CONTROL_RETRIES
    if os.environ.get('LOCAWEB_FTP_PORT', '21') != '21':
        raise ValueError('ftp_port_must_be_21')
    # A native STOR/RETR can succeed while the next control handshake fails.
    # Retry only establishing that connection; never replay a data transfer.
    for attempt in range(3):
        ftp = PassiveFTP()
        operation = 'connect'
        try:
            ftp.connect(os.environ['LOCAWEB_FTP_HOST'], 21, timeout=20)
            operation = 'login'
            ftp.login(os.environ['LOCAWEB_FTP_USER'], os.environ['LOCAWEB_FTP_PASSWORD'])
            ftp.set_pasv(True)
            operation = 'pwd'
            if ftp.pwd() != '/':
                raise RuntimeError('ftp_home_mismatch')
            return ftp
        except Exception as error:
            control_failure(error, operation)
            try:
                ftp.close()
            except OSError:
                pass
            transient = isinstance(error, (ConnectionError, TimeoutError, EOFError, ftplib.error_temp))
            if not transient or attempt == 2:
                raise
            CONTROL_RETRIES += 1
            time.sleep((5, 15)[attempt])


def publication_transport(component='portal'):
    from .ssh_transport import selection, transport
    if selection() == 'ssh':
        return transport(Transport, component)
    return Transport(connect(), reconnect=connect, transfer=curl_transfer)


def execute(args):
    if args.action == 'build':
        result = build(args.component, args.commit, args.directory)
    elif args.action == 'verify':
        manifest = validate_package(args.directory, args.component)
        result = {'status': 'verified', 'commit': manifest['commit'], 'urls': verify_public(manifest, live=True)}
    else:
        manifest = validate_package(args.directory, args.component) if args.action == 'deploy' else None
        transport = publication_transport(args.component)
        try:
            if args.action == 'recover':
                result = recover(transport, args.component)
            elif args.action == 'status':
                result = status(transport, args.component)
            else:
                with transport.lock(args.component):
                    if args.action == 'deploy':
                        contents = {name: (args.directory/'files'/name).read_bytes() for name in manifest['files']}
                        result = activate(transport, manifest, contents, args.transaction)
                    else:
                        result = rollback(transport, args.component, args.version, args.transaction)
            result['ftp_reconciliations'] = transport.reconciled_transfers
            result['ftp_control_retries'] = CONTROL_RETRIES
            if hasattr(transport.ftp, 'metrics'):
                result['transport_metrics'] = transport.ftp.metrics
        finally:
            transport.ftp.close()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['build', 'deploy', 'verify', 'status', 'rollback', 'recover'])
    parser.add_argument('--component', choices=['portal', 'raio-x'], required=True)
    parser.add_argument('--commit')
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--version', default='previous')
    parser.add_argument('--transaction', default='run-'+str(time.time_ns()))
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    try:
        result = execute(args)
    except Exception as error:
        result = {'status': 'failed', 'component': args.component, 'operation': args.action, **error_report(error)}
        if args.report:
            args.report.write_bytes(encode(result))
        print(json.dumps(result))
        raise SystemExit(1)
    if args.report:
        args.report.write_bytes(encode(result))
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # FTP errors and credential-bearing URLs must never enter logs.
        print(json.dumps({'status': 'failed', **error_report(error)}))
        raise SystemExit(1)
