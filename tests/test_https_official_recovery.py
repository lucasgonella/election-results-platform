"""Real PHP validation of complete releases assembled from synthetic deltas."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from ftp_recovery_fixtures import bundle, change

ROOT=Path(__file__).resolve().parents[1]


class OfficialRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.api=self.root/'public/api';self.api.mkdir(parents=True)
        for name in ['publish-official-snapshot.php','ftp-publication.php']:
            shutil.copyfile(ROOT/'deploy/locaweb'/name,self.api/name)
        self.private=self.root/'.election-publisher';self.private.mkdir()
        (self.private/'ENABLE_OFFICIAL_PUBLICATION').touch()
        self.sid='a'*64;self.batch='b'*32
        self.site=self.root/'public/data';self.baseline=self.site/'releases'/self.sid
        self.baseline.parent.mkdir(parents=True);bundle(self.baseline,1)
        self.delta=self.private/'batches'/self.batch/'files';self.delta.parent.mkdir(parents=True)
        bundle(self.delta,2,{'rj/governor.json'})
        for directory in (self.baseline,self.delta):
            for path in directory.rglob('*.json'):change(path,lambda value:value.__setitem__('environment','oficial'))
        old=json.loads((self.baseline/'version.json').read_bytes())|{'snapshot_id':self.sid}
        (self.site/'version.json').write_text(json.dumps(old))
        self.marker=(self.site/'version.json').read_bytes()
        (self.delta.parent/'batch.json').write_text(json.dumps({'paths':['rj/governor.json','manifest.json','version.json','alerts.json']}))

    def call(self):
        script='require $argv[1];try {echo json_encode(publishOfficialSnapshot($argv[2],$argv[3]));}catch(Throwable $e){echo json_encode(["error"=>$e->getMessage()]);}'
        result=subprocess.run(['php','-r',script,str(self.api/'publish-official-snapshot.php'),str(self.private),self.batch],capture_output=True,text=True,check=True)
        return json.loads(result.stdout)

    def test_delta_carries_136_baseline_targets_and_checksums(self):
        result=self.call();self.assertEqual(result['status'],'published')
        selected=self.site/'releases'/result['snapshot_id']
        self.assertEqual(len(list(selected.glob('*/*.json'))),137)
        for path in self.baseline.glob('*/*.json'):
            relative=path.relative_to(self.baseline)
            source=self.delta/relative if relative.as_posix()=='rj/governor.json' else path
            self.assertEqual(hashlib.sha256((selected/relative).read_bytes()).digest(),hashlib.sha256(source.read_bytes()).digest())
        self.assertEqual(json.loads((self.site/'version.json').read_bytes())['snapshot_id'],result['snapshot_id'])

    def test_missing_delta_preserves_selection(self):
        (self.delta/'rj/governor.json').unlink()
        self.assertEqual(self.call()['error'],'invalid_release')
        self.assertEqual((self.site/'version.json').read_bytes(),self.marker)

    def test_manifest_identity_mismatch_preserves_selection(self):
        change(self.delta/'manifest.json',lambda value:next(row for row in value['results'] if row['path']=='rj/governor.json').__setitem__('tse_idg',999))
        self.assertEqual(self.call()['error'],'invalid_result')
        self.assertEqual((self.site/'version.json').read_bytes(),self.marker)

    def test_totalization_reopening_stays_blocked(self):
        change(self.delta/'rj/governor.json',lambda value:value['snapshot'].__setitem__('totalization_final',False))
        self.assertEqual(self.call()['error'],'totalization_reopened_requires_review')
        self.assertEqual((self.site/'version.json').read_bytes(),self.marker)

    def test_wrong_target_set_preserves_selection(self):
        change(self.delta/'manifest.json',lambda value:value['results'][0].__setitem__('path','ac/arbitrary.json'))
        self.assertEqual(self.call()['error'],'invalid_release')
        self.assertEqual((self.site/'version.json').read_bytes(),self.marker)


if __name__=='__main__':unittest.main()
