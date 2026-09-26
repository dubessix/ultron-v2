"""V2 Step C3: the Chrome extension itself."""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from backend.app.websocket.connection_manager import EXTENSION_ID

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "extension" / "chrome"


class TestManifest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((FOLDER / "manifest.json").read_text(encoding="utf-8"))

    def test_key_gives_the_id_the_server_trusts(self):
        der = base64.b64decode(self.manifest["key"])
        digest = hashlib.sha256(der).hexdigest()[:32]
        self.assertEqual("".join(chr(ord("a") + int(c, 16)) for c in digest), EXTENSION_ID)

    def test_small_permissions_and_files_present(self):
        self.assertEqual(self.manifest["manifest_version"], 3)
        self.assertEqual(sorted(self.manifest["permissions"]), ["alarms", "history", "scripting", "sessions", "tabs"])
        self.assertGreaterEqual(int(self.manifest["minimum_chrome_version"]), 116)
        for name in ("background.js", "icon128.png"):
            self.assertTrue((FOLDER / name).is_file(), name)
        self.assertIn("ws://127.0.0.1:8000/ws/browser", (FOLDER / "background.js").read_text(encoding="utf-8"))


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestTabRules(unittest.TestCase):
    def test_extension_logic_with_fake_chrome(self):
        done = subprocess.run(["node", str(ROOT / "tests" / "extension_logic_check.cjs")],
                              capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertIn("ALL OK", done.stdout)


if __name__ == "__main__":
    unittest.main()
