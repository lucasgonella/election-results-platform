"""Execute the actual favorites reader in a minimal browser harness."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest


def test_favorites_pins_manifest_and_result_to_one_release():
    node=shutil.which('node')
    if not node: pytest.fail('Node required for FTP frontend contract tests')
    source=(Path(__file__).resolve().parents[1]/'web/public/eleicoes/favorites.js').read_text(encoding='utf-8')
    # Expose internal reader functions, preserving their implementation unchanged.
    source=source.replace('    init();','    window.harness = {refreshManifest, loadFavoriteData, publicationToken};')
    script=r'''
const vm = require('node:vm');
const assert = require('node:assert/strict');
const urls = [];
const id = 'a'.repeat(64);
const version = {environment:'fixture', generated_at:'same', snapshot_id:id, activation_revision:'1'};
const item = {scope:'ac', office:1, path:'ac/president.json', election_code:1, round:1, tse_idg:'1', captured_at:'same'};
const context = {window:{}, document:{}, console, localStorage:{getItem:()=>null}, fetch:async(url)=>{
  urls.push(url);
  return {ok:true,json:async()=>url.endsWith('manifest.json')?{results:[item]}:
    {candidates:[], snapshot:{tse_idg:'1', captured_at:'same'}}};
}};
vm.createContext(context);
vm.runInContext(SOURCE,context);
(async()=>{
  const harness=context.window.harness;
  await harness.refreshManifest(version);
  await harness.loadFavoriteData({scope:'ac',office:1,election_code:1,round:1,tse_candidate_seq:'missing'});
  assert.deepEqual(urls,[`/data/releases/${id}/manifest.json`,`/data/releases/${id}/ac/president.json`]);
  assert.notEqual(harness.publicationToken(version),harness.publicationToken({...version,activation_revision:'2'}));
  assert.notEqual(harness.publicationToken(version),harness.publicationToken({...version,snapshot_id:'b'.repeat(64)}));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''.replace('SOURCE',json.dumps(source))
    subprocess.run([node,'-e',script],check=True,capture_output=True,text=True)
