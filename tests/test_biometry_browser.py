"""Real browser, invented local-only publication, production panel markup."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import threading
import unittest

from collector.src.biometry import canonical
from collector.src.biometry_publish import marker_for
from tests.biometry_fixtures import dataset

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
if os.environ.get('BIOMETRY_BROWSER_REQUIRED') == '1' and not sync_playwright:
    raise RuntimeError('Biometry browser checks require Playwright')
ROOT = Path(__file__).resolve().parents[1]


class Handler(SimpleHTTPRequestHandler):
    payload = canonical(dataset())
    marker = marker_for(payload)
    def do_GET(self):
        path=self.path.split('?')[0]
        if path=='/':
            html=(ROOT/'web/public/eleicoes/index.html').read_text()
            section=html[html.index('<section id="biometria"'):html.index('<section id="vote-history"')]
            raw=('''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Painel sintético local</title><link rel="stylesheet" href="/eleicoes/design-system.css"><link rel="stylesheet" href="/eleicoes/biometry.css"></head><body><main><h1>Fixture sintética</h1>'''+section+'''</main><script>window.fixtureContext={round:2};window.ElectionPortal={getContext:()=>fixtureContext};</script><script src="/eleicoes/biometry.js"></script></body></html>''').encode()
        elif path.startswith('/biometria-2026/'):
            raw=self.marker if path.endswith('version.json') else self.payload
        else:return super().do_GET()
        self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def log_message(self,*args):pass


@unittest.skipUnless(sync_playwright,'Dedicated biometry CI requires Chromium')
class BiometryBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT/'web/public')))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}/'
        cls.playwright=sync_playwright().start();cls.browser=cls.playwright.chromium.launch(args=['--disable-dev-shm-usage'])
    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.playwright.stop();cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def test_responsive_filters_csv_turn_isolation_and_stale_data(self):
        for width in [390,1440]:
            with self.subTest(width=width):
                context=self.browser.new_context(viewport={'width':width,'height':950},accept_downloads=True)
                self.addCleanup(context.close);page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(self.base+'?turno=2#biometria');page.wait_for_function("document.getElementById('bio-biometric').textContent==='163'")
                self.assertIn('parciais',page.locator('#bio-status').inner_text())
                self.assertIn('183 votantes',page.locator('#bio-unknown').inner_text())
                self.assertEqual(page.locator('#bio-body tr').count(),28)
                self.assertEqual(page.evaluate('document.documentElement.scrollWidth<=innerWidth'),True)
                page.locator('#bio-uf').select_option('zz')
                self.assertEqual(page.locator('#bio-biometric').inner_text(),'—')
                self.assertEqual(page.locator('#bio-without').inner_text(),'—')
                self.assertIn('não informada',page.locator('#bio-biometric-share').inner_text())
                self.assertEqual(page.locator('#bio-attendance').inner_text(),'183')
                self.assertEqual(page.locator('#bio-body td').nth(2).inner_text(),'—')
                page.locator('#bio-uf').select_option('ac');self.assertEqual(page.locator('#bio-without').inner_text(),'20')
                page.locator('#bio-search').fill('sintetica ac');self.assertEqual(page.locator('#bio-body tr').count(),1)
                with page.expect_download() as downloaded:page.locator('#bio-csv').click()
                text=Path(downloaded.value.path()).read_text(encoding='utf-8-sig');self.assertIn('163',text);self.assertIn('Identificação biográfica',text)
                page.route('**/biometria-2026/**/version.json',lambda route:route.fulfill(status=404))
                page.locator('#bio-refresh').click();page.wait_for_function("document.getElementById('bio-status').textContent.includes('últimos dados validados')")
                self.assertEqual(page.locator('#bio-biometric').inner_text(),'163')
                page.evaluate("fixtureContext.round=1;document.dispatchEvent(new CustomEvent('election:context'))")
                self.assertTrue(page.locator('#biometria').is_hidden())
                page.evaluate("fixtureContext.round=2;document.dispatchEvent(new CustomEvent('election:context'))")
                self.assertTrue(page.locator('#biometria').is_visible())
                self.assertEqual(errors,[])

    def test_light_dark_accessibility(self):
        axe=os.environ.get('BIOMETRY_AXE_PATH') or os.environ.get('MUNICIPAL_AXE_PATH')
        if not axe:self.skipTest('axe-core provided by dedicated CI')
        context=self.browser.new_context();self.addCleanup(context.close);page=context.new_page()
        page.goto(self.base);page.wait_for_function("document.getElementById('bio-biometric').textContent==='163'")
        page.add_script_tag(path=axe)
        for theme in ['light','dark']:
            page.evaluate("theme=>document.documentElement.dataset.theme=theme",theme)
            result=page.evaluate("async()=>{const r=await axe.run(document.getElementById('biometria'));return r.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}));}")
            self.assertEqual(result,[])
