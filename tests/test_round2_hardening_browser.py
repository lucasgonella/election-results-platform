"""Real Chromium: immutable cache, turn isolation, failed activation reads and freshness."""
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import threading
import unittest
from urllib.parse import urlsplit

from collector.src.election_release import canonical
from collector.src.second_round_collection import build_values, discover
from collector.src.second_round_publish import describe, marker_for
from hardening_fixtures import FullSource

ROOT = Path(__file__).resolve().parents[1]
HAS_BROWSER = importlib.util.find_spec('playwright') is not None


@unittest.skipUnless(HAS_BROWSER, 'Playwright required in hardening CI')
class HardeningBrowserTests(unittest.TestCase):
    def test_landing_urls_keep_controls_readers_and_favorites_in_the_selected_round(self):
        """All fixtures stay on loopback; no official source or public writes."""
        from contextlib import ExitStack
        from hashlib import sha256
        import mimetypes
        from playwright.sync_api import sync_playwright

        files, requests = {}, []
        selected_files = {'br/president.json', 'ac/president.json', 'ac/governor.json'}
        for round_number in (1, 2):
            source = FullSource(totalized=0 if round_number == 2 else 50)
            values = build_values(source, discover(source))
            objects = {name: json.loads(raw) for name, raw in values.items()
                       if name in selected_files | {'version.json', 'manifest.json', 'alerts.json'}}
            manifest = objects['manifest.json']
            manifest['results'] = [row for row in manifest['results'] if row['path'] in selected_files]
            manifest['result_count'] = len(manifest['results'])
            manifest['candidate_count'] = sum(row['candidate_count'] for row in manifest['results'])
            if round_number == 1:
                objects['version.json']['round'] = 1
                for row in manifest['results']:
                    row['round'] = 1
                    row['election_code'] = 6257 if row['office'] == 1 else 6259
                    objects[row['path']]['election'].update(round=1, code=row['election_code'])
            else:
                objects['portal.json'] = {'schema_version': 1, 'environment': 'oficial',
                                         'round': 2, 'files': dict(objects)}
            values = {name: canonical(value) for name, value in objects.items()}
            if round_number == 2:
                verified = describe(values)
                sid, marker = verified['snapshot_id'], marker_for(verified)
            else:
                descriptor = {'schema_version': 1, 'environment': 'oficial', 'round': 1,
                              'generated_at': objects['version.json']['generated_at'],
                              'files': {name: {'sha256': sha256(raw).hexdigest(), 'size': len(raw)}
                                        for name, raw in sorted(values.items())}}
                sid = sha256(canonical(descriptor)).hexdigest()
                marker = canonical({key: value for key, value in descriptor.items() if key != 'files'}
                                   | {'snapshot_id': sid})
            base = '/data/turnos/2' if round_number == 2 else '/data'
            files[base + '/version.json'] = marker
            files.update({base + '/releases/' + sid + '/' + name: raw for name, raw in values.items()})
            if round_number == 2:
                stamp = datetime.now(timezone.utc).isoformat()
                files[base + '/status.json'] = canonical({
                    'schema_version': 1, 'environment': 'oficial', 'round': 2,
                    'checked_at': stamp, 'last_source_success_at': stamp,
                    'source_stale_after_seconds': 600, 'snapshot_id': sid,
                    'election_state': 'official_data_available', 'state': 'awaiting_results'})

        class State:
            second_available = True

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                path = urlsplit(self.path).path
                requests.append(path)
                code, kind, body = 200, 'application/json', files.get(path)
                if not State.second_available and path.startswith('/data/turnos/2/'):
                    body = None
                if path.startswith('/eleicoes/'):
                    asset = (ROOT / 'web/public/eleicoes' / (path.removeprefix('/eleicoes/') or 'index.html')).resolve()
                    if asset.is_relative_to(ROOT / 'web/public/eleicoes') and asset.is_file():
                        body, kind = asset.read_bytes(), mimetypes.guess_type(asset.name)[0] or 'application/octet-stream'
                if body is None: code, body = 404, b''
                self.send_response(code)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                origin = 'http://127.0.0.1:' + str(server.server_port)
                for width in (1440, 390):
                    for query, round_number in [('', 2), ('?turno=1', 1), ('?turno=2', 2)]:
                        with self.subTest(width=width, query=query), ExitStack() as cleanup:
                            context = browser.new_context(viewport={'width': width, 'height': 900})
                            cleanup.callback(context.close)
                            context.route('**/*', lambda route: route.continue_()
                                          if route.request.url.startswith(origin + '/') else route.abort())
                            page = context.new_page()
                            errors, start = [], len(requests)
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            response = page.goto(origin + '/eleicoes/' + query)
                            self.assertIsNone(response.request.redirected_from)
                            page.wait_for_function('window.ElectionPortal?.getContext()?.result?.candidates?.length > 0')
                            self.assertEqual(page.evaluate('ElectionPortal.getContext().round'), round_number)
                            self.assertEqual(page.evaluate('ElectionPortal.getContext().result.election.round'), round_number)
                            self.assertEqual(page.locator('#round-' + ('second' if round_number == 2 else 'first')).get_attribute('aria-current'), 'page')
                            self.assertEqual(page.locator('#live-pipeline-status').is_visible(), round_number == 2)
                            if round_number == 2:
                                self.assertIn('Aguardando apuração', page.locator('#sections-summary').inner_text())
                            page.locator('#results .favorite-toggle').first.click()
                            saved = page.evaluate("localStorage.getItem('election-results:favorites:v1')")
                            self.assertEqual(len(json.loads(saved)), 1)
                            page.locator('#favorites-open').click()
                            page.locator('#favorites-list .favorite-card').wait_for()
                            page.locator('#favorites-close').click()
                            candidate = page.evaluate('ElectionPortal.getContext().result.candidates[0]')
                            page.locator('#search').fill(candidate['name'])
                            page.wait_for_function('(id) => ElectionPortal.getCandidates().length === 1 && String(ElectionPortal.getCandidates()[0].tse_candidate_seq) === String(id)',
                                                   arg=candidate['tse_candidate_seq'])
                            page.locator('#search').fill('')
                            page.select_option('#scope-select', 'ac')
                            page.wait_for_function('ElectionPortal.getContext().scope === "ac" && ElectionPortal.getContext().status === "ready"')
                            self.assertTrue(page.evaluate('ElectionPortal.selectScope("ac", 3)'))
                            self.assertEqual(page.locator('#scope-select').input_value(), 'ac')
                            self.assertEqual(page.evaluate('ElectionPortal.getContext().result.office.code'), 3)
                            self.assertEqual(page.evaluate('ElectoralMap.view.context.round'), round_number)
                            self.assertEqual(page.evaluate('ElectionPortal.getContext().result.election.round'), round_number)
                            data_paths = [path for path in requests[start:] if path.startswith('/data/')]
                            self.assertTrue(data_paths)
                            self.assertTrue(all(path.startswith('/data/turnos/2/') == (round_number == 2)
                                                for path in data_paths), data_paths)
                            if query == '' and width == 1440:
                                page.locator('[data-dialog-open="compare-dialog"]').click()
                                page.locator('#round-comparison .comparison-column').nth(1).wait_for()
                                self.assertIn('1º turno', page.locator('#round-comparison').inner_text())
                                self.assertIn('2º turno', page.locator('#round-comparison').inner_text())
                                self.assertEqual(page.evaluate('ElectionPortal.getContext().round'), 2)
                                page.locator('[aria-label="Fechar comparação"]').click()
                            page.reload()
                            page.wait_for_function('window.ElectionPortal?.getContext()?.status === "ready"')
                            self.assertEqual(page.evaluate("localStorage.getItem('election-results:favorites:v1')"), saved)
                            self.assertFalse(errors, errors)
                State.second_available = False
                context = browser.new_context()
                context.route('**/*', lambda route: route.continue_()
                              if route.request.url.startswith(origin + '/') else route.abort())
                start = len(requests)
                page = context.new_page()
                page.goto(origin + '/eleicoes/')
                page.wait_for_function('document.body.classList.contains("round-two-unavailable")')
                self.assertTrue(page.locator('#round-unavailable').is_visible())
                self.assertEqual(page.locator('#round-second').get_attribute('aria-current'), 'page')
                self.assertTrue(all(path.startswith('/data/turnos/2/') for path in requests[start:]
                                    if path.startswith('/data/')))
                self.assertIsNone(page.evaluate('ElectionPortal.getContext().result'))
                browser.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_corrupt_immutable_native_http_cache_is_reloaded(self):
        from playwright.sync_api import sync_playwright
        source = FullSource(totalized=0)
        values = build_values(source, discover(source))
        verified = describe(values); sid = verified['snapshot_id']
        bundle_path = '/data/turnos/2/releases/' + sid + '/portal.json'
        hits = []
        class State:
            corrupt = True
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                path = urlsplit(self.path).path; hits.append(path)
                if path == '/': body, kind = b'<script src="/live-data.js"></script>', 'text/html'
                elif path == '/live-data.js': body, kind = (ROOT / 'web/public/eleicoes/live-data.js').read_bytes(), 'text/javascript'
                elif path == '/data/turnos/2/version.json': body, kind = marker_for(verified), 'application/json'
                elif path == bundle_path: body, kind = (b'{}' if State.corrupt else values['portal.json']), 'application/json'
                else: self.send_error(404); return
                self.send_response(200); self.send_header('Content-Type', kind)
                if path == bundle_path: self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(); page = browser.new_page()
                # No request routing: Chromium's native HTTP cache must be enabled.
                page.goto('http://127.0.0.1:' + str(server.server_port))
                page.evaluate("LiveData.fetch('/data/turnos/2/version.json')")
                error = page.evaluate("""async base => {try {await LiveData.fetch(base + '/manifest.json'); return null;} catch (e) {return e.message;}}""",
                                      '/data/turnos/2/releases/' + sid)
                self.assertEqual(error, 'portal_bundle_integrity_error')
                State.corrupt = False
                count = page.evaluate("""async base => (await (await LiveData.fetch(base + '/manifest.json')).json()).results.length""",
                                      '/data/turnos/2/releases/' + sid)
                self.assertEqual(count, 35)
                self.assertEqual(hits.count(bundle_path), 2)
                browser.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_shared_tabs_atomic_release_retry_and_honest_status(self):
        from playwright.sync_api import sync_playwright
        rows, files, status = [], {}, {}
        class State:
            marker = None
            corrupt = None
        def activate(generation, totalized):
            source = FullSource(generation=generation, totalized=totalized)
            values = build_values(source, discover(source)); verified = describe(values)
            sid = verified['snapshot_id']
            files.update({'/data/turnos/2/releases/' + sid + '/' + name: raw for name, raw in values.items()})
            State.marker = marker_for(verified)
            stamp = datetime.now(timezone.utc).isoformat()
            status.update(schema_version=1, environment='oficial', round=2, checked_at=stamp,
                last_source_success_at=stamp, last_publication_at=stamp, last_official_change_at=stamp,
                source_stale_after_seconds=180, snapshot_id=sid,
                election_state='official_data_available' if totalized == 0 else 'counting_in_progress',
                state='awaiting_results' if totalized == 0 else 'current')
            return sid
        initial = activate(1, 0)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                path = urlsplit(self.path).path; rows.append(path)
                code, kind = 200, 'application/json'
                if path == '/data/turnos/2/version.json': body = State.marker
                elif path == '/data/turnos/2/status.json': body = canonical(status)
                elif path in files: body = b'{}' if path == State.corrupt else files[path]
                elif path.startswith('/eleicoes/'):
                    relative = path[len('/eleicoes/'):] or 'index.html'
                    file = (ROOT / 'web/public/eleicoes' / relative).resolve()
                    if file.is_relative_to(ROOT / 'web/public/eleicoes') and file.is_file():
                        import mimetypes
                        body = file.read_bytes(); kind = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
                    else: code, body = 404, b''
                else: code, body = 404, b''
                self.send_response(code); self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        errors = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                context = browser.new_context()
                origin = 'http://127.0.0.1:' + str(server.server_port)
                context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin) else route.abort())
                pages = []
                for _ in range(2):
                    page = context.new_page(); page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(origin + '/eleicoes/' + ('?turno=2' if pages else ''))
                    page.wait_for_function('window.ElectionPortal?.getContext()?.result?.candidates?.length > 0')
                    pages.append(page)
                page = pages[0]
                self.assertEqual(sum(path.endswith('/portal.json') for path in rows), 1)
                self.assertFalse(any(path.endswith('/president.json') or path.endswith('/governor.json') for path in rows))
                self.assertEqual(page.evaluate('ElectionPortal.getContext().round'), 2)
                self.assertIn('Aguardando apuração', page.locator('#sections-summary').inner_text())
                page.wait_for_load_state('networkidle')
                page_requests = []
                page.on('request', lambda request: page_requests.append(request.url))
                before = len(page_requests)
                page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});refreshIfChanged()")
                page.wait_for_timeout(300)
                self.assertEqual(len(page_requests), before)
                page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>false})")
                page.evaluate("window.competingReader = setInterval(() => { if (!document.hidden) LiveData.fetch('/data/turnos/2/version.json').catch(() => {}); }, 1000)")
                changed = activate(2, 50)
                State.corrupt = '/data/turnos/2/releases/' + changed + '/portal.json'
                # The interval and the minimum polling age have independent
                # phases. Wait for actual rejection by periodic polling, not
                # a guessed first tick; keep the old complete context meanwhile.
                with page.expect_console_message(lambda message: message.type == 'error'
                        and 'Refresh failed:' in message.text
                        and 'portal_bundle_integrity_error' in message.text, timeout=20000):
                    page.evaluate("LiveData.setState('counting_in_progress')")
                self.assertEqual(page.evaluate('ElectionPortal.getContext().version.snapshot_id'), initial)
                self.assertIn(State.corrupt, rows)
                State.corrupt = None
                page.wait_for_function('(id)=>ElectionPortal.getContext().version.snapshot_id===id', arg=changed, timeout=25000)
                self.assertEqual(page.evaluate('ElectionPortal.getContext().result.election.round'), 2)
                self.assertTrue(page.evaluate('ElectionPortal.getContext().result.snapshot.sections.totalized > 0'))
                status['last_source_success_at'] = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
                page.evaluate('ElectionLiveStatus.refresh()')
                page.wait_for_function("document.getElementById('live-status-label').textContent.includes('atrasada')", timeout=20000)
                self.assertIn('atrasada', page.locator('#live-status-label').inner_text())
                self.assertFalse(any(path == '/data/version.json' for path in rows))
                self.assertFalse(errors, errors)
                browser.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
