"""Exercise theme and keyboard behavior without network or browser dependencies."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


WEB = Path(__file__).resolve().parents[1] / "web/public/eleicoes"


def run_design_script(assertions, *, stored=None, os_dark=False, storage_error=False):
    node = shutil.which("node")
    if not node:
        pytest.fail("Node is required for frontend behavior validation")
    source = (WEB / "design-system.js").read_text(encoding="utf-8")
    harness = r"""
const vm = require('node:vm'), assert = require('node:assert/strict');
const root = {attrs: new Map(), setAttribute(k,v){this.attrs.set(k,v);}, getAttribute(k){return this.attrs.get(k);}};
function control(attrs={}) {return {attrs:{...attrs},events:{},textContent:'',focused:false,
 setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return this.attrs[k];},
 addEventListener(k,fn){this.events[k]=fn;},focus(){this.focused=true;}};}
const theme = control(), navToggle = control({'aria-controls':'nav'}), navClasses = new Set();
const nav = {events:{},classList:{toggle(k){if(navClasses.has(k)){navClasses.delete(k);return false;}navClasses.add(k);return true;},remove(k){navClasses.delete(k);},contains(k){return navClasses.has(k);}},addEventListener(k,fn){this.events[k]=fn;}};
const dialog = {open:false,opens:0,events:{},showModal(){this.open=true;this.opens++;},close(){this.open=false;},
 addEventListener(k,fn){this.events[k]=fn;},getBoundingClientRect(){return {left:10,right:200,top:10,bottom:200};}};
const dialogOpen = control({'data-dialog-open':'source-dialog'}), dialogClose = control();
dialogClose.closest=()=>dialog;
const documentEvents = {}, windowEvents = {}, schemeEvents = {}, writes = [];
const scheme = {matches:OS_DARK,addEventListener(k,fn){schemeEvents[k]=fn;}};
const context = {document:{documentElement:root,readyState:'complete',
 querySelectorAll(selector){return selector==='[data-theme-toggle]'?[theme]:selector==='[data-nav-toggle]'?[navToggle]:selector==='[data-dialog-open]'?[dialogOpen]:selector==='[data-dialog-close]'?[dialogClose]:selector==='dialog'?[dialog]:[];},
 querySelector(){return null;},getElementById(id){return id==='nav'?nav:id==='source-dialog'?dialog:null;},addEventListener(k,fn){documentEvents[k]=fn;}},
 window:{matchMedia:()=>scheme,addEventListener(k,fn){windowEvents[k]=fn;}},
 localStorage:{getItem(){if(STORAGE_ERROR)throw new Error('storage denied');return STORED;},setItem(k,v){if(STORAGE_ERROR)throw new Error('storage denied');writes.push([k,v]);}},
 console,fetch(){throw new Error('Presentation must not fetch electoral data');}};
vm.createContext(context);vm.runInContext(SOURCE, context);
ASSERTIONS
"""
    harness = (harness.replace("OS_DARK", json.dumps(os_dark))
               .replace("STORAGE_ERROR", json.dumps(storage_error))
               .replace("STORED", json.dumps(stored))
               .replace("SOURCE", json.dumps(source))
               .replace("ASSERTIONS", assertions))
    subprocess.run([node, "-e", harness], check=True, capture_output=True, text=True)


def test_theme_survives_denied_browser_storage_and_respects_explicit_choice():
    run_design_script(r"""
assert.equal(root.getAttribute('data-theme'),'dark');
assert.equal(theme.attrs['aria-label'],'Ativar tema claro');
assert.equal(theme.attrs['aria-pressed'],'true');
theme.events.click();
assert.equal(root.getAttribute('data-theme'),'light');
assert.equal(theme.attrs['aria-pressed'],'false');
schemeEvents.change({matches:true});
assert.equal(root.getAttribute('data-theme'),'light');
""", os_dark=True, storage_error=True)


def test_theme_follows_system_until_user_selects_and_syncs_between_tabs():
    run_design_script(r"""
assert.equal(root.getAttribute('data-theme'),'light');
scheme.matches=true;schemeEvents.change({matches:true});
assert.equal(root.getAttribute('data-theme'),'dark');
theme.events.click();
assert.deepEqual(writes,[['election-results:theme:v1','light']]);
windowEvents.storage({key:'election-results:favorites:v1',newValue:'dark'});
assert.equal(root.getAttribute('data-theme'),'light');
windowEvents.storage({key:'election-results:theme:v1',newValue:'dark'});
assert.equal(root.getAttribute('data-theme'),'dark');
scheme.matches=false;windowEvents.storage({key:'election-results:theme:v1',newValue:null});
assert.equal(root.getAttribute('data-theme'),'light');
""", stored="invalid preference")


def test_persisted_theme_wins_over_system_preference():
    run_design_script(r"""
assert.equal(root.getAttribute('data-theme'),'light');
schemeEvents.change({matches:true});
assert.equal(root.getAttribute('data-theme'),'light');
""", stored="light", os_dark=True)


def test_mobile_navigation_escape_restores_focus_and_collapses():
    run_design_script(r"""
navToggle.events.click();
assert(navClasses.has('is-open'));
assert.equal(navToggle.attrs['aria-expanded'],'true');
documentEvents.keydown({key:'Escape'});
assert(!navClasses.has('is-open'));
assert.equal(navToggle.attrs['aria-expanded'],'false');
assert(navToggle.focused);
""")


def test_dialog_uses_native_modal_behavior_and_preserves_clicks_inside():
    run_design_script(r"""
dialogOpen.events.click();
assert(dialog.open);
dialogOpen.events.click();
assert.equal(dialog.opens,1);
dialog.events.click({target:dialog,clientX:50,clientY:50});
assert(dialog.open);
dialog.events.click({target:dialog,clientX:1,clientY:1});
assert(!dialog.open);
dialogOpen.events.click();
dialogClose.events.click();
assert(!dialog.open);
""")


def test_escape_closes_a_dialog_with_search_focus_without_a_second_keypress():
    run_design_script(r"""
dialogOpen.events.click();
let prevented=false;
dialog.events.keydown({key:'Escape',target:{value:'Goiás',type:'search'},preventDefault(){prevented=true;}});
assert(prevented);assert(!dialog.open);
""")


def test_composition_exploration_preserves_official_rendering_contract():
    html = (WEB / "composicao.html").read_text(encoding="utf-8")
    for element_id in ("composition-party-search", "composition-house-select",
                       "camera-house", "senate-house", "composition-filter-status"):
        assert f'id="{element_id}"' in html
    assert 'data-composition-view="compare" aria-pressed="true"' in html
    assert 'data-composition-view="table" aria-pressed="false"' in html
    assert "não são consultadas em tempo real" in html
    assert "não mistura dados do segundo turno" in html
    assert 'src="composition.js?v=3"' in html


def test_both_portal_entrypoints_share_theme_and_accessibility_primitives():
    for entrypoint in ("index.html", "composicao.html"):
        html = (WEB / entrypoint).read_text(encoding="utf-8")
        assert 'src="design-system.js?v=1"' in html
        assert 'href="design-system.css?v=1"' in html
        assert 'class="skip-link"' in html
        assert "data-theme-toggle" in html
        assert 'aria-controls="main-navigation"' in html
