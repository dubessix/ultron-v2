"""Phase 5 regressions for consistent Ultron/Zora identity visuals."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "src"
COMPONENTS = FRONTEND / "components"
THEME = FRONTEND / "theme" / "personalityTheme.js"


class TestPersonalityThemeContract(unittest.TestCase):
    def test_theme_tokens_define_ultron_emerald_and_zora_pink(self):
        script = f"""
import {{ getPersonalityTheme }} from {json.dumps(THEME.as_uri())};
console.log(JSON.stringify({{
  ultron: getPersonalityTheme('ultron'),
  zora: getPersonalityTheme('zora'),
  fallback: getPersonalityTheme('unknown')
}}));
"""
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["ultron"]["name"], "ULTRON")
        self.assertEqual(payload["ultron"]["primary"], "#10B981")
        self.assertEqual(payload["zora"]["name"], "ZORA")
        self.assertEqual(payload["zora"]["primary"], "#EC4899")
        self.assertEqual(payload["fallback"], payload["ultron"])

    def test_top_identity_and_core_use_shared_personality_tokens(self):
        shell = (COMPONENTS / "AppShell.jsx").read_text(encoding="utf-8")
        core = (COMPONENTS / "BlobCanvas.jsx").read_text(encoding="utf-8")
        self.assertIn("getPersonalityTheme", shell)
        self.assertIn("theme.name", shell)
        self.assertIn("Personal Desktop Assistant", shell)
        self.assertNotIn("IRIS", shell)
        self.assertIn("getPersonalityTheme", core)
        self.assertIn("theme.coreParticle", core)
        self.assertIn("theme.coreGlow", core)
        self.assertIn("theme.coreOrbit", core)

    def test_zora_chat_widget_and_rail_accents_are_pink_not_purple(self):
        right = (COMPONENTS / "RightPanel.jsx").read_text(encoding="utf-8")
        widget = (COMPONENTS / "widgets" / "WidgetContainer.jsx").read_text(encoding="utf-8")
        rail = (COMPONENTS / "WidgetRail.jsx").read_text(encoding="utf-8")
        self.assertIn("getPersonalityTheme", right)
        self.assertIn("messageTheme", right)
        self.assertNotIn("bg-purple", right)
        self.assertNotIn("text-purple", right)
        self.assertIn("getPersonalityTheme", widget)
        self.assertNotIn("border-l-purple", widget)
        self.assertNotIn("192,132,252", widget)
        self.assertIn("text-pink-400", rail)
        self.assertNotIn("text-purple", rail)

    def test_personality_visual_switch_still_follows_successful_backend_save(self):
        app = (FRONTEND / "App.jsx").read_text(encoding="utf-8")
        request = app.index("await api('/api/personality'")
        state_change = app.index("setActivePersonality(result.personality)")
        self.assertLess(request, state_change)
        self.assertNotIn("setActivePersonality(nextPers)", app[request:state_change])


if __name__ == "__main__":
    unittest.main()
