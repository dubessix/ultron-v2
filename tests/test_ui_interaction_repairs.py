"""Regressions for owner-reported touch, personality, and coding controls."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "frontend" / "src" / "App.jsx"
SHELL = ROOT / "frontend" / "src" / "components" / "AppShell.jsx"
CONTAINER = ROOT / "frontend" / "src" / "components" / "widgets" / "WidgetContainer.jsx"
DRAG = ROOT / "frontend" / "src" / "hooks" / "useDraggable.js"
VOICE = ROOT / "frontend" / "src" / "hooks" / "useVoice.js"
ROUTER = ROOT / "backend" / "app" / "router.py"


class TestTouchDraggableWidgets(unittest.TestCase):
    def test_drag_hook_uses_unified_pointer_events_for_mouse_and_touch(self):
        source = DRAG.read_text(encoding="utf-8")
        for contract in (
            "handlePointerDown",
            "pointermove",
            "pointerup",
            "pointercancel",
            "pointerId",
            "setPointerCapture",
        ):
            self.assertIn(contract, source)

    def test_widget_header_wires_pointer_drag_and_disables_touch_scrolling(self):
        source = CONTAINER.read_text(encoding="utf-8")
        self.assertIn("onPointerDown={handlePointerDown}", source)
        self.assertIn("touch-none", source)
        self.assertIn("no-drag", source)
        self.assertIn("onDoubleClick", source)


class TestPersistedBottomControls(unittest.TestCase):
    def test_personality_has_visible_pending_state_and_changes_only_after_api(self):
        source = APP.read_text(encoding="utf-8")
        self.assertIn("personalitySaving", source)
        block = re.search(r"const togglePersonality[\s\S]+?\n  };", source)
        self.assertIsNotNone(block)
        text = block.group(0)
        self.assertLess(text.index("await api('/api/personality'"), text.index("setActivePersonality(result.personality)"))
        self.assertIn("setPersonalitySaving(true)", text)
        self.assertIn("setPersonalitySaving(false)", text)
        self.assertIn("personalitySaving={personalitySaving}", source)

    def test_coding_control_uses_shared_api_helper_and_commits_reported_state(self):
        source = APP.read_text(encoding="utf-8")
        self.assertIn("codingModeSaving", source)
        block = re.search(r"const toggleCodingMode[\s\S]+?\n  };", source)
        self.assertIsNotNone(block)
        text = block.group(0)
        self.assertIn("await api('/api/coding-mode'", text)
        self.assertIn("setCodingMode(Boolean(result.coding_mode))", text)
        self.assertNotIn("setCodingMode(next);", text.split("try", 1)[0])
        self.assertIn("codingModeSaving={codingModeSaving}", source)

    def test_buttons_disable_while_backend_persistence_is_pending(self):
        source = SHELL.read_text(encoding="utf-8")
        self.assertIn("personalitySaving", source)
        self.assertIn("codingModeSaving", source)
        self.assertIn("disabled={personalitySaving}", source)
        self.assertIn("disabled={codingModeSaving}", source)
        self.assertIn("Saving", source)
        self.assertIn("Updating", source)


class TestVoiceFailureFeedback(unittest.TestCase):
    def test_remote_desktop_microphone_failure_is_visible_and_honest(self):
        voice = VOICE.read_text(encoding="utf-8")
        shell = SHELL.read_text(encoding="utf-8")
        self.assertIn('event.error === "audio-capture"', voice)
        self.assertIn("No microphone input is available", voice)
        self.assertIn("voiceError", voice)
        self.assertIn("supported", voice)
        self.assertIn("voice.voiceError", shell)


class TestCodingModeBackend(unittest.TestCase):
    def test_endpoint_updates_the_process_shared_orchestrator(self):
        source = ROUTER.read_text(encoding="utf-8")
        block = re.search(r"async def set_coding_mode[\s\S]+?\n    except Exception", source)
        self.assertIsNotNone(block)
        text = block.group(0)
        self.assertIn("get_orchestrator()", text)
        self.assertNotIn("CognitiveOrchestrator()", text)


if __name__ == "__main__":
    unittest.main()
