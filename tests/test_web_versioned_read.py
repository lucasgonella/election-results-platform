"""Backward-compatible immutable snapshot URL selection regression checks."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "web/public/eleicoes/app.js"
COMPOSITION = ROOT / "web/public/eleicoes/composition.js"


class VersionedReadTests(unittest.TestCase):
    def test_frontend_uses_pinned_snapshot_paths_and_fallback(self):
        app = APP.read_text(encoding="utf-8")
        composition = COMPOSITION.read_text(encoding="utf-8")
        for source in (app, composition):
            self.assertIn('if (id == null) return "/data";', source)
            self.assertIn('/data/releases/', source)
            self.assertIn('^[a-f0-9]{32,64}$', source)
        self.assertIn("dataBaseForVersion(version)", app)
        self.assertIn("compositionDataBaseForVersion(version)", composition)
        self.assertIn("activeDataBase = candidateBase;", app)
        self.assertIn('compositionDataBase + "/"', composition)

    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_javascript_syntax(self):
        for path in (APP, COMPOSITION):
            subprocess.run(["node", "--check", str(path)], check=True)


if __name__ == "__main__":
    unittest.main()
