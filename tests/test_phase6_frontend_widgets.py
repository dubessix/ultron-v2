"""
Phase 6 regression — frontend widget API URLs.

The 7 widgets that used broken RELATIVE fetch('/api/...') URLs (404 in dev,
because the backend runs on a different port) must now use the shared apiBase
from the frontend API client. This static guard prevents regression back to
relative URLs.

These are source-level guards (deterministic, no browser/jsdom required); the
Vite build passing separately proves the JS compiles.
"""

import re
import unittest
from pathlib import Path

FRONTEND_SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"
WIDGETS_DIR = FRONTEND_SRC / "components" / "widgets"

# Widgets that previously used a broken relative '/api/tools/execute'.
PREVIOUSLY_BROKEN = [
    "TodoWidget.jsx", "CalendarWidget.jsx", "ReminderWidget.jsx",
    "CodeOptimizerWidget.jsx", "DailyBriefingWidget.jsx",
    "SecurityGuardianWidget.jsx", "SemanticCodeGraphWidget.jsx",
]


class TestWidgetApiUrlFix(unittest.TestCase):

    def test_no_widget_uses_relative_api_fetch(self):
        relative = re.compile(r"fetch\(\s*['\"]/api")
        offenders = []
        for jsx in WIDGETS_DIR.glob("*.jsx"):
            text = jsx.read_text(encoding="utf-8")
            if relative.search(text):
                offenders.append(jsx.name)
        self.assertEqual(offenders, [], f"Widgets still using relative /api URLs: {offenders}")

    def test_shared_api_client_exists_and_exports_apiBase(self):
        api_js = FRONTEND_SRC / "api.js"
        self.assertTrue(api_js.exists(), "shared frontend API client missing")
        text = api_js.read_text(encoding="utf-8")
        self.assertIn("export const apiBase", text)
        self.assertIn("VITE_API_URL", text)

    def test_previous_broken_widgets_use_shared_api_module(self):
        for name in PREVIOUSLY_BROKEN:
            path = WIDGETS_DIR / name
            self.assertTrue(path.exists(), name)
            text = path.read_text(encoding="utf-8")
            self.assertIn("../../api", text, f"{name} does not use the shared API module")
            self.assertTrue(
                "apiBase" in text or "executeTool" in text or "api(" in text,
                f"{name} imports the API module but does not use it",
            )
            self.assertNotIn("fetch('/api", text, f"{name} still has a relative /api fetch")


if __name__ == "__main__":
    unittest.main()
