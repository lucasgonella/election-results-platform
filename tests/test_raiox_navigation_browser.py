"""Real Chromium acceptance tests; only invented financial records are served."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import unittest

from tests.raiox_navigation_fixtures import navigation_fixture

ROOT = Path(__file__).resolve().parents[1]
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
if os.environ.get('RAIOX_BROWSER_REQUIRED') == '1' and sync_playwright is None:
    raise RuntimeError('Required real-browser checks need Playwright; skipping is forbidden in Raio-X CI')


class FixtureHandler(SimpleHTTPRequestHandler):
    fixture = navigation_fixture()

    def do_GET(self):
        if self.path.split('?')[0] == '/eleicoes/goias/raio-x/data/go-2026.json':
            body = json.dumps(self.fixture).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

    def log_message(self, *args):
        pass


@unittest.skipUnless(sync_playwright, 'Dedicated Raio-X CI runs required Chromium checks')
class RaioxBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(FixtureHandler, directory=str(ROOT / 'web/public')))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}/eleicoes/goias/raio-x/'
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        FixtureHandler.fixture = navigation_fixture()
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1000})
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [], 'Browser runtime errors')

    def open(self, query=''):
        self.page.goto(self.base + query)
        self.page.wait_for_selector('#metrics[aria-busy="false"]')
        self.assertNotIn('Não foi possível', self.page.locator('#notice').inner_text())

    def selected(self):
        return self.page.evaluate("new URL(location.href).searchParams.get('selected')")

    def select_search(self, entity, query):
        self.page.locator('#search').fill(query)
        self.page.wait_for_timeout(200)
        self.page.locator(f'#candidate-list [data-candidate="{entity}"]').click()
        self.page.wait_for_timeout(100)
        self.assertEqual(self.selected(), entity)

    def click_node(self, entity):
        node = self.page.locator(f'.graph-node[data-node="{entity}"]')
        node.scroll_into_view_if_needed()
        point = node.evaluate('(node)=>{const m=node.getScreenCTM();return {x:m.e,y:m.f}}')
        self.page.mouse.click(point['x'], point['y'])
        self.page.wait_for_timeout(100)
        self.assertEqual(self.selected(), entity)

    def snapshot(self):
        nodes = sorted(self.page.locator('.graph-node').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.node)'))
        edges = sorted(self.page.locator('.graph-edge').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.edge)'))
        evidence = self.page.locator('#detail-content .record-list .record').evaluate_all('(rows)=>rows.map(r=>({text:r.innerText,href:r.querySelector("a")?.href})).sort((a,b)=>a.text.localeCompare(b.text))')
        self.page.locator('#table-view-button').click()
        records = self.page.locator('#transfer-table tr').evaluate_all('(rows)=>rows.map(r=>({id:r.querySelector("[data-record]")?.dataset.record,text:r.innerText})).sort((a,b)=>a.id.localeCompare(b.id))')
        self.page.locator('#graph-view-button').click()
        return dict(nodes=nodes, edges=edges, records=records, evidence=evidence)

    def test_p0_charles_izaura_click_search_url_and_multiple_hops_are_identical(self):
        self.open()
        self.assertIsNone(self.selected())
        self.select_search('person:charles', 'CHARLES BENTO')
        previous_camera = self.page.locator('#graph-viewport').get_attribute('transform')
        self.assertEqual(self.page.locator('.graph-node[data-node="person:bia"]').count(), 0)
        self.click_node('person:izaura')
        self.assertEqual(self.page.locator('#detail-title').inner_text(), 'IZAURA CRISTINA PERES')
        signature = self.snapshot()
        self.assertEqual(signature['nodes'], ['person:bia', 'person:charles', 'person:davi', 'person:izaura'])
        self.assertEqual(len(signature['records']), 4)
        self.assertEqual(len({record['id'] for record in signature['records']}), 4)
        self.assertIn('4 registros diretos', self.page.locator('#detail-content').inner_text())
        self.page.locator('#navigation-back').click()
        self.page.wait_for_function("new URL(location.href).searchParams.get('selected')==='person:charles'")
        self.assertEqual(self.page.locator('#graph-viewport').get_attribute('transform'), previous_camera)
        self.page.locator('#navigation-forward').click()
        self.page.wait_for_function("new URL(location.href).searchParams.get('selected')==='person:izaura'")
        self.assertEqual(self.snapshot(), signature)
        for target in ['person:bia', 'person:paulo', 'person:bia', 'person:izaura']:
            self.click_node(target)
        self.assertEqual(self.snapshot(), signature)
        history_length = self.page.evaluate('history.length')
        self.select_search('person:izaura', 'PERES IZAURA')
        self.assertEqual(self.page.evaluate('history.length'), history_length)
        self.assertEqual(self.snapshot(), signature)
        self.open('?selected=person%3Aizaura&q=CHARLES+BENTO')
        self.assertEqual(self.snapshot(), signature)
        self.page.go_back()
        self.page.wait_for_function("new URL(location.href).searchParams.get('selected')==='person:izaura'")
        self.assertEqual(self.snapshot(), signature)

    def test_initial_general_url_alias_invalid_and_reset(self):
        self.open()
        self.assertEqual(self.page.locator('#graph-title').inner_text(), 'Visão geral')
        self.assertEqual(self.page.locator('#detail-title').inner_text(), 'Visão geral')
        self.assertEqual(self.page.locator('.graph-node.is-selected').count(), 0)
        self.open('?selected=registration%3Acharles')
        self.assertEqual(self.selected(), 'person:charles')
        self.open('?selected=unavailable&min=100')
        self.assertIsNone(self.selected())
        self.assertIn('visão geral', self.page.locator('#toast').inner_text())
        self.assertEqual(self.page.locator('#min-value').input_value(), '100')
        self.select_search('person:charles', 'Charles')
        self.page.locator('#clear-selection').click()
        self.assertIsNone(self.selected())
        self.assertEqual(self.page.locator('#min-value').input_value(), '100')
        self.select_search('person:charles', 'Charles')
        self.page.locator('#reset-filters').click()
        self.assertIsNone(self.selected())
        self.assertEqual(self.page.locator('#min-value').input_value(), '')
        self.assertEqual(self.page.locator('#search').input_value(), '')

    def test_filters_do_not_inherit_search_or_silently_hide_direct_records(self):
        self.open('?selected=person%3Acharles&office=deputado+estadual')
        self.assertEqual(self.selected(), 'person:charles')
        self.assertIn('ocultos pelos filtros explícitos', self.page.locator('#connection-coverage').inner_text())
        self.page.locator('#office').select_option('')
        self.page.wait_for_timeout(200)
        self.click_node('person:izaura')
        self.page.locator('#office').select_option('deputado estadual')
        self.page.wait_for_timeout(200)
        filtered = self.snapshot()
        self.assertEqual(len(filtered['records']), 2)
        self.assertIn('2 ocultos', self.page.locator('#connection-coverage').inner_text())
        self.select_search('person:izaura', 'Izaura')
        self.assertEqual(self.snapshot(), filtered)
        self.open('?selected=person%3Aizaura&office=deputado+estadual&q=Charles')
        self.assertEqual(self.snapshot(), filtered)
        self.open('?selected=person%3Abia&direction=incoming')
        self.click_node('person:izaura')
        self.assertIn('direction=incoming', self.page.url)
        self.assertIn('0 nos filtros', self.page.locator('#connection-coverage').inner_text())
        self.select_search('person:izaura', 'Izaura')
        self.assertIn('0 nos filtros', self.page.locator('#connection-coverage').inner_text())
        self.open('?selected=person%3Aizaura&direction=incoming')
        self.assertIn('0 nos filtros', self.page.locator('#connection-coverage').inner_text())

    def test_hover_zoom_and_pan_never_select_and_zoom_preserves_cursor_point(self):
        self.open()
        node = self.page.locator('.graph-node[data-node="person:izaura"]')
        node.scroll_into_view_if_needed()
        anchor = node.evaluate('(node)=>{const m=node.getScreenCTM();return {x:m.e,y:m.f}}')
        anchor = {key: round(value) for key, value in anchor.items()}
        self.page.mouse.move(anchor['x'], anchor['y'])
        self.assertTrue(self.page.locator('#graph-tooltip').is_visible())
        self.assertIsNone(self.selected())
        self.assertEqual(self.page.locator('#detail-title').inner_text(), 'Visão geral')
        def world():
            return self.page.locator('#graph-viewport').evaluate('(g,p)=>{const v=new DOMPoint(p.x,p.y).matrixTransform(g.getScreenCTM().inverse());return {x:v.x,y:v.y}}', anchor)
        before = world()
        self.page.keyboard.down('Control')
        self.page.mouse.wheel(0, -220)
        self.page.keyboard.up('Control')
        self.page.wait_for_timeout(80)
        after = world()
        # Browser SVG matrices/wheel coordinates have finite precision. Bound
        # the screen error below 0.1px; pure algebra has a separate 1e-8 check.
        unit = self.page.locator('#graph-viewport').evaluate('(g)=>g.getScreenCTM().a')
        self.assertLess(abs(before['x'] - after['x']) * unit, .1)
        self.assertLess(abs(before['y'] - after['y']) * unit, .1)
        self.assertIsNone(self.selected())
        anchor = node.evaluate('(node)=>{const m=node.getScreenCTM();return {x:m.e,y:m.f}}')
        old = self.page.locator('#graph-viewport').get_attribute('transform')
        self.page.mouse.move(anchor['x'], anchor['y'])
        self.page.mouse.down()
        self.page.mouse.move(anchor['x'] + 80, anchor['y'] + 30, steps=10)
        self.page.mouse.move(anchor['x'], anchor['y'], steps=10)
        self.page.mouse.up()
        self.assertIsNone(self.selected())
        self.page.wait_for_timeout(380)
        self.click_node('person:izaura')
        camera = self.page.locator('#graph-viewport').get_attribute('transform')
        self.page.locator('#graph').dispatch_event('click', {'clientX': 1, 'clientY': 1, 'detail': 1})
        self.assertIsNone(self.selected())
        self.assertEqual(self.page.locator('#graph-viewport').get_attribute('transform'), camera)

    def test_search_keyboard_homonyms_and_private_document_guards(self):
        self.open()
        self.page.locator('#search').fill('Izaura Peres')
        self.page.wait_for_timeout(200)
        self.assertEqual(self.page.locator('#candidate-list button').count(), 2)
        self.page.locator('#search').press('ArrowDown')
        self.assertTrue(self.page.locator('#candidate-list button').first.evaluate('(n)=>n===document.activeElement'))
        self.page.locator('#candidate-list button').first.press('ArrowDown')
        self.page.locator('#candidate-list button').nth(1).press('Enter')
        self.assertIn(self.selected(), ['person:izaura', 'person:homonym'])
        for selector in ['#search', '#financier', '#recipient', '#path-search']:
            if selector in ['#financier', '#recipient']:
                self.page.locator('.advanced-filters').evaluate('(n)=>n.open=true')
            if selector == '#path-search':
                self.page.locator('#path-explorer').evaluate('(n)=>n.open=true')
            self.page.locator(selector).fill('000.000.000-00')
            self.page.wait_for_timeout(220)
            self.assertEqual(self.page.locator(selector).input_value(), '')
            self.assertNotIn('000', self.page.url)
        self.open('?q=00000000000&cpf=00000000000&selected=00000000000')
        self.assertNotIn('00000000000', self.page.url)
        self.assertIsNone(self.selected())
        self.assertEqual(self.page.locator('[id*="cpf"],input[name="cpf"]').count(), 0)

    def test_large_source_search_outside_render_limit_and_incremental_tables(self):
        FixtureHandler.fixture = navigation_fixture(extra_donors=1200)
        self.open()
        self.assertLessEqual(self.page.locator('.graph-node').count(), 70)
        self.assertIn('fora do desenho', self.page.locator('#graph-summary').inner_text())
        self.select_search('person:extra:1199', 'DOADOR SINTETICO 1199')
        self.assertEqual(self.page.locator('.graph-node').count(), 2)
        self.click_node('person:davi')
        self.assertLessEqual(self.page.locator('.graph-node').count(), 70)
        self.page.locator('#table-view-button').click()
        self.assertEqual(self.page.locator('#transfer-table [data-record]').count(), 30)
        self.assertIn('1.201', self.page.locator('#table-page').inner_text())
        self.page.locator('#table-next').click()
        self.assertTrue(self.page.locator('#table-page').inner_text().startswith('31'))
        self.assertLess(self.page.evaluate('performance.now()'), 15000)

    def test_empty_contract_error_retry_and_isolated_identity(self):
        FixtureHandler.fixture = {**navigation_fixture(), 'scope': 'SP'}
        self.page.goto(self.base)
        self.page.wait_for_selector('#metrics[aria-busy="false"]')
        self.assertIn('Não foi possível validar', self.page.locator('#notice').inner_text())
        self.assertEqual(self.page.locator('.graph-node').count(), 0)
        FixtureHandler.fixture = {**navigation_fixture(), 'transfers': []}
        self.page.locator('#retry-load').click()
        self.page.wait_for_function("document.querySelector('#notice').textContent.includes('ainda não foram publicadas')")
        self.assertIsNone(self.selected())
        self.assertIn('Aguardando relações', self.page.locator('#graph-empty').inner_text())
        self.select_search('person:izaura', 'Izaura')
        self.assertEqual(self.page.locator('.graph-node').count(), 1)
        self.assertIn('0 registros diretos', self.page.locator('#connection-coverage').inner_text())
        self.page.locator('#overview-button').click()
        self.assertIsNone(self.selected())

    def test_node_contours_never_cover_role_colors_with_default_black_fill(self):
        fixture = navigation_fixture()
        fixture['entities'][0]['roles'].append('campaign_financier')
        fixture['entities'].append(dict(id='organization:fixture', name='Organização sintética',
                                        kind='organization', roles=['organization'],
                                        candidate_ids=[], aliases=[]))
        fixture['transfers'].append({**fixture['transfers'][0], 'id':'transaction:organization',
                                     'from_id':'organization:fixture', 'from_role':'organization',
                                     'from_name':'Organização sintética', 'amount':150})
        FixtureHandler.fixture = fixture
        self.open('?selected=person%3Acharles')
        for width in [1440, 390]:
            for theme in ['light', 'dark']:
                with self.subTest(width=width, theme=theme):
                    self.page.set_viewport_size({'width':width, 'height':900})
                    self.page.evaluate('(t)=>document.documentElement.dataset.theme=t', theme)
                    # resize redraws the SVG; inspect after the browser has
                    # delivered resize and painted, rather than a detached node.
                    self.page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                    # Measure painted SVG styles: an outline must be transparent,
                    # even when more specific role rules assign a circle's fill.
                    fills = self.page.locator('.graph-node .node-outline').evaluate_all('(ns)=>ns.map(n=>getComputedStyle(n).fill)')
                    self.assertTrue(fills)
                    self.assertEqual(set(fills), {'none'})
                    self.assertEqual(self.page.locator('.graph-node rect').count(), 0)
                    for kind, token in [('organization','--organization-blue'), ('candidate-campaign','--teal'), ('donor','--gold')]:
                        colors = self.page.evaluate('([kind,token])=>{const n=document.querySelector(`.graph-node[data-kind="${kind}"] > circle:not([class])`);const probe=document.createElement("span");probe.style.color=getComputedStyle(document.documentElement).getPropertyValue(token);document.body.appendChild(probe);const result={actual:getComputedStyle(n).fill,expected:getComputedStyle(probe).color};probe.remove();return result}', [kind, token])
                        self.assertEqual(colors['actual'], colors['expected'])
                        self.assertNotEqual(colors['actual'], 'rgb(0, 0, 0)')
        self.assertEqual(self.selected(), 'person:charles')
        self.assertEqual(self.page.locator('#transfer-table [data-record]').count(), 3)

    def test_touch_pinch_and_mobile_accessibility_in_both_themes(self):
        axe = os.environ.get('RAIOX_AXE_PATH')
        if os.environ.get('RAIOX_BROWSER_REQUIRED') == '1' and not axe:
            self.fail('Required accessibility audit needs RAIOX_AXE_PATH')
        for width, height in [(1440, 1000), (390, 844)]:
            for theme in ['light', 'dark']:
                with self.subTest(width=width, theme=theme):
                    self.page.set_viewport_size({'width': width, 'height': height})
                    self.open('?selected=person%3Aizaura')
                    self.page.evaluate('(t)=>document.documentElement.dataset.theme=t', theme)
                    self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth>innerWidth'))
                    if axe:
                        self.page.add_script_tag(path=axe)
                        violations = self.page.evaluate("async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))")
                        self.assertEqual(violations, [])
                    if width == 390:
                        self.page.locator('#graph').scroll_into_view_if_needed()
                        box = self.page.locator('#graph').bounding_box()
                        cx, cy = box['x'] + box['width']/2, box['y'] + box['height']/2
                        session = self.context.new_cdp_session(self.page)
                        old = self.page.locator('#graph-viewport').get_attribute('transform')
                        def touch(kind, offset):
                            session.send('Input.dispatchTouchEvent', {'type': kind, 'touchPoints': [] if kind == 'touchEnd' else [{'x':cx-offset,'y':cy,'id':1}, {'x':cx+offset,'y':cy,'id':2}]})
                        touch('touchStart', 30)
                        touch('touchMove', 55)
                        touch('touchEnd', 0)
                        self.page.wait_for_timeout(80)
                        self.assertNotEqual(self.page.locator('#graph-viewport').get_attribute('transform'), old)
                        self.assertEqual(self.selected(), 'person:izaura')
                        session.detach()
                    shots = os.environ.get('RAIOX_SCREENSHOT_DIR')
                    if shots:
                        Path(shots).mkdir(parents=True, exist_ok=True)
                        self.page.screenshot(path=str(Path(shots) / f'raiox-{width}-{theme}.png'), full_page=True)


if __name__ == '__main__':
    unittest.main()
