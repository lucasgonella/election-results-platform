"""Real Chromium navigation with explicitly invented municipality fixtures."""
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from collector.src.election_release import canonical,digest
from collector.src.municipal_collection import result
from collector.src.municipal_release import assemble,verify
from tests.municipal_fixtures import make_dataset,make_geometry,ea20,ELECTION

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright=None
if os.environ.get('MUNICIPAL_BROWSER_REQUIRED')=='1' and not sync_playwright:raise RuntimeError('Municipal browser checks require Playwright')
ROOT=Path(__file__).resolve().parents[1]


def load_tests(loader, suite, pattern):
    """Reuse the portal's required Chromium job for its national BU panel."""
    suite.addTests(loader.loadTestsFromName('tests.test_biometry_browser'))
    return suite


class Handler(SimpleHTTPRequestHandler):
    files={}
    def do_GET(self):
        path=self.path.split('?')[0]
        if path=='/':
            raw=b'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fixture municipal</title><link rel="stylesheet" href="/eleicoes/electoral-map.css"><link rel="stylesheet" href="/eleicoes/municipal-map.css"></head><body><main><h1>Fixture sint\xc3\xa9tica municipal</h1><div id="electoral-map-root"></div></main><script>window.fixtureContext={round:1,scope:'br'};window.ElectionPortal={getContext:()=>fixtureContext,loadResult:async()=>null,selectScope:async(scope)=>{fixtureContext={...fixtureContext,scope};document.dispatchEvent(new CustomEvent('election:context',{detail:fixtureContext}));},setCandidate:()=>{},scopeName:scope=>scope};</script><script src="/eleicoes/brazil-states.js"></script><script src="/eleicoes/municipal-map.js"></script><script src="/eleicoes/electoral-map.js"></script></body></html>'''
        elif path.startswith('/municipal-2026/'):
            raw=self.files.get(path.removeprefix('/municipal-2026/'))
            if raw is None:self.send_error(404);return
        else:return super().do_GET()
        self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def log_message(self,*args):pass


@unittest.skipUnless(sync_playwright,'Dedicated municipal CI requires Chromium')
class MunicipalBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();root=Path(cls.tmp.name);cls.data=make_dataset();make_geometry(cls.data,root/'geometry');cls.marker=assemble(cls.data,root/'geometry',root/'package')
        _,values=verify(root/'package');Handler.files={**values,'turnos/1/version.json':canonical(cls.marker)}
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT/'web/public')))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start();cls.base=f'http://127.0.0.1:{cls.server.server_port}/'
        cls.playwright=sync_playwright().start();cls.browser=cls.playwright.chromium.launch()
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.playwright.stop();cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.tmp.cleanup()
    def setUp(self):
        self.context=self.browser.new_context(viewport={'width':1440,'height':1000});self.page=self.context.new_page();self.errors=[];self.page.on('pageerror',lambda e:self.errors.append(str(e)))
    def tearDown(self):self.context.close();self.assertEqual(self.errors,[])
    def open(self):
        self.page.goto(self.base+'?nivel=municipios');self.page.wait_for_function('ElectoralMap.view?.municipal.context && !ElectoralMap.view.municipal.loading')
    def go(self):
        self.page.locator('#mmap-search').fill('goiania');self.page.locator('#mmap-search-results button').click();self.page.wait_for_function("new URL(location.href).searchParams.get('municipio')!==null")

    def test_search_uf_selection_details_table_and_shared_url(self):
        self.open();self.go();self.assertIn('GOIÂNIA SINTÉTICA',self.page.locator('#mmap-detail').inner_text())
        self.assertIn('80',self.page.locator('#mmap-detail').inner_text());self.assertIn('60',self.page.locator('#mmap-detail').inner_text());self.assertEqual(self.page.locator('#mmap-uf').input_value(),'go')
        url=self.page.url;self.page.reload();self.page.wait_for_function('ElectoralMap.view?.municipal.context && !ElectoralMap.view.municipal.loading');self.assertEqual(self.page.url,url)
        self.page.locator('#mmap-table-view').click();self.assertEqual(self.page.locator('#mmap-table tbody tr').count(),1)
        self.page.locator('#mmap-map-view').click();self.page.locator('#mmap-reset').click();self.page.wait_for_function("ElectoralMap.view.municipal.uf==='' ")
        self.page.locator('.emap-level button').first.click();self.assertTrue(self.page.locator('#municipal-map-root').is_hidden())

    def test_cursor_zoom_hover_pan_click_and_keyboard_do_not_confuse_selection(self):
        self.open();self.go();self.page.evaluate("ElectoralMap.view.municipal.selected='';ElectoralMap.view.municipal.url();ElectoralMap.view.municipal.render()")
        self.page.locator('#mmap-canvas').scroll_into_view_if_needed();camera=self.page.evaluate('({...ElectoralMap.view.municipal.camera})');box=self.page.locator('#mmap-canvas').bounding_box();x,y=box['x']+box['width']*.45,box['y']+box['height']*.45
        # Native wheel events quantize CSS client coordinates; measure the actual
        # event location rather than assume our fractional automation coordinate.
        self.page.evaluate("document.getElementById('mmap-canvas').addEventListener('wheel',e=>window.fixtureWheelPoint=ElectoralMap.view.municipal.point(e),{once:true})")
        self.page.mouse.move(x,y);self.page.keyboard.down('Control');self.page.mouse.wheel(0,-80);self.page.keyboard.up('Control');self.page.wait_for_timeout(50)
        after=self.page.evaluate('({...ElectoralMap.view.municipal.camera})');point=self.page.evaluate('fixtureWheelPoint');px,py=point['x'],point['y']
        self.assertAlmostEqual((px-camera['x'])/camera['scale'],(px-after['x'])/after['scale'],places=5)
        self.assertAlmostEqual((py-camera['y'])/camera['scale'],(py-after['y'])/after['scale'],places=5)
        self.assertIsNone(self.page.evaluate("new URL(location.href).searchParams.get('municipio')"))
        self.page.mouse.move(x,y);self.page.mouse.down();self.page.mouse.move(x+40,y+40,steps=6);self.page.mouse.up();self.assertIsNone(self.page.evaluate("new URL(location.href).searchParams.get('municipio')"))
        self.page.locator('#mmap-canvas').focus();self.page.keyboard.press('ArrowRight');self.page.keyboard.press('Enter');self.page.wait_for_function("new URL(location.href).searchParams.get('municipio')!==null")

    def test_second_round_missing_never_keeps_first_round_values_or_shapes(self):
        self.open();self.go();self.page.evaluate("fixtureContext={round:2,scope:'br'};document.dispatchEvent(new CustomEvent('election:context',{detail:fixtureContext}))")
        self.page.wait_for_function("document.getElementById('mmap-status').textContent.includes('Aguardando dados municipais oficiais deste turno')")
        self.assertNotIn('80',self.page.locator('#mmap-detail').inner_text());self.assertEqual(self.page.evaluate('ElectoralMap.view.municipal.paths.size'),0)

    def test_repeated_zoom_requests_prepare_each_geometry_once(self):
        self.open()
        result=self.page.evaluate("""async()=>{
            const map=ElectoralMap.view.municipal;
            let builds=0;const prepare=map.prepareGeometry.bind(map);
            map.prepareGeometry=async(...args)=>{builds++;return prepare(...args);};
            // Rapid zoom updates may request the same detailed UF while its
            // polygons are still being prepared. They must share that work.
            await Promise.all(Array.from({length:30},()=>map.loadGeometry('go','detail')));
            return {builds,loaded:map.geometryLoaded.has('go-detail'),pending:map.geometryRequests.size};
        }""")
        self.assertEqual(result,{'builds':1,'loaded':True,'pending':0})

    def test_slow_previous_uf_cannot_replace_latest_user_choice(self):
        self.open()
        result=self.page.evaluate("""async()=>{
            const map=ElectoralMap.view.municipal,geometry=map.reader.geometry.bind(map.reader);
            map.reader.geometry=async(...args)=>{
                if(args[1]==='ac'&&args[2]==='detail')await new Promise(resolve=>setTimeout(resolve,100));
                return geometry(...args);
            };
            await Promise.all([map.setUF('ac'),map.setUF('go')]);
            return {map:map.uf,portal:fixtureContext.scope,control:document.getElementById('mmap-uf').value,url:new URL(location.href).searchParams.get('muf')};
        }""")
        self.assertEqual(result,{'map':'go','portal':'go','control':'go','url':'go'})

    def test_tied_municipality_stays_neutral_for_leader_but_has_candidate_intensity(self):
        data=make_dataset();index=next(i for i,row in enumerate(data['municipalities']) if row['uf']=='go');old=data['municipalities'][index]
        municipality={key:old[key] for key in ['uf','name','tse_code','ibge_code']}
        raw=ea20(old['tse_code'],tie=True)
        info={'url':old['source_url'],'captured_at':old['captured_at'],'sha256':digest(canonical(raw))}
        data['municipalities'][index]=result(raw,municipality,ELECTION,info,data['catalog'])
        data['states']['go']=result({**raw,'tpabr':'uf','cdabr':'go'},None,ELECTION,{**info,'scope':'go'},data['catalog'])
        directory=Path(self.tmp.name)/'tie-package';geometry=Path(self.tmp.name)/'tie-geometry'
        make_geometry(data,geometry);marker=assemble(data,geometry,directory);_,files=verify(directory)
        previous=Handler.files;Handler.files={**files,'turnos/1/version.json':canonical(marker)}
        self.addCleanup(setattr,Handler,'files',previous)
        self.open();self.go();self.assertIn('Empate',self.page.locator('#mmap-detail').inner_text())
        color='(()=>{const m=ElectoralMap.view.municipal;return m.color(m.byId.get(m.selected));})()'
        self.assertEqual(self.page.evaluate(color),'#d7dfe5')
        self.page.locator('#mmap-mode').select_option('share');self.page.locator('#mmap-candidate').select_option('10')
        self.page.wait_for_function('ElectoralMap.view.municipal.mode==="share" && ElectoralMap.view.municipal.candidate==="10"')
        self.assertNotEqual(self.page.evaluate(color),'#d7dfe5')
        self.assertIsNone(self.page.evaluate('ElectoralMap.view.municipal.byId.get(ElectoralMap.view.municipal.selected).leader'))
        self.page.locator('#mmap-mode').select_option('leader');self.assertEqual(self.page.evaluate(color),'#d7dfe5')

    def test_mobile_dark_mode_accessibility_and_bounded_table(self):
        axe=os.environ.get('MUNICIPAL_AXE_PATH')
        if os.environ.get('MUNICIPAL_BROWSER_REQUIRED')=='1' and not axe:self.fail('Required accessibility audit missing axe')
        for width in [1440,390]:
            for theme in ['light','dark']:
                self.page.set_viewport_size({'width':width,'height':900});self.open();self.page.evaluate('(t)=>document.documentElement.dataset.theme=t',theme)
                self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth>innerWidth'))
                if axe:
                    self.page.add_script_tag(path=axe);violations=self.page.evaluate("async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))")
                    self.assertEqual(violations,[])
                self.page.locator('#mmap-table-view').click();self.assertLessEqual(self.page.locator('#mmap-table tbody tr').count(),30)

