"""
Ultron Unit & Integration Testing Suite — Phase 12 Diagnostics
Tests non-intrusive glassmorphic notification priorities, Event-Driven UI triggers,
Structured AI Actions, and 3-panel widescreen layout integrity under constitutional compliance.
"""

import unittest
from pathlib import Path
from fastapi.testclient import TestClient

from backend.app.main import app

BASE_DIR = Path(__file__).resolve().parent.parent
COMPONENTS_DIR = BASE_DIR / "frontend" / "src" / "components"
APP_PATH = BASE_DIR / "frontend" / "src" / "App.jsx"

class TestPhase12SystemPolishArchitecture(unittest.TestCase):
    
    def test_notification_toasts_presence(self):
        """Test 1: Verify NotificationToast component and priority mappings exist."""
        toast_path = COMPONENTS_DIR / "NotificationToast.jsx"
        self.assertTrue(toast_path.exists())
        
        with open(toast_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Assert priority border levels exist (Requirement: Notification Prioritization)
            self.assertIn("priority", content)
            self.assertIn("low", content)
            self.assertIn("medium", content)
            self.assertIn("high", content)
            self.assertIn("critical", content)
            self.assertIn("border-l-rose-400", content) # Critical border
            self.assertIn("border-l-amber-400", content) # High border

    def test_event_driven_ui_triggering_and_lifecycles(self):
        """Test 2: Verify that App.jsx maps structured AI action payloads to automatic widget activation."""
        with open(APP_PATH, "r", encoding="utf-8") as f:
            content = f.read()
            # Assert that local keyword checks have been completely removed (Constitution Compliance)
            self.assertNotIn("lowerText.includes", content)
            
            # Assert that structured action metadata intercepts govern the UI
            self.assertIn("structured_action", content)
            self.assertIn("open_widget", content)
            self.assertIn("addNotification", content)

    def test_keyboard_shortcuts_fallbacks(self):
        """Test 3: Verify that keyboard event handlers are defined and mapped as fallbacks."""
        with open(APP_PATH, "r", encoding="utf-8") as f:
            content = f.read()
            # Assert window keyboard listeners are wired up
            self.assertIn("keydown", content)
            self.assertIn("addEventListener", content)
            self.assertIn("removeEventListener", content)
            self.assertIn("ctrlKey", content)
            self.assertIn("altKey", content)
            self.assertIn("Escape", content)

    def test_ui_layout_integrity_maintained(self):
        """Test 4: Verify the approved 3-panel widescreen grid layout remains untouched."""
        shell_path = COMPONENTS_DIR / "AppShell.jsx"
        
        with open(shell_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Verify no chatbot sidebars were introduced
            self.assertNotIn("sidebar", content.lower())
            self.assertNotIn("history-list", content.lower())
            
            # Verify left panel, canvas blob, and right panel remain intact
            self.assertIn("LeftPanel", content)
            self.assertIn("RightPanel", content)
            self.assertIn("BlobCanvas", content)

    def test_e2e_api_chat_structured_action_delivery(self):
        """Test 6: Verify that POST /api/chat delivers structured actions over HTTP payloads."""
        from backend.app.router import get_orchestrator
        from tests._ai_script import reply, scripted_brain, use

        client = TestClient(app)

        def script(prompt, conv):  # the AI itself picks the panel
            if any(m.get("role") == "tool" for m in conv):
                return reply("Downloads is open, Sir.")
            return reply("", [use("show_widget", {"widget_id": "file_explorer"})])

        with scripted_brain(get_orchestrator(), script):
            response = client.post(
                "/api/chat",
                json={"session_id": "test_sess_constitutional", "content": "Open downloads."}
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Assert structured action payload matches standard
        self.assertIn("structured_action", data)
        self.assertEqual(data["structured_action"]["action"], "open_widget")
        self.assertEqual(data["structured_action"]["widget_id"], "file_explorer")

if __name__ == "__main__":
    unittest.main()
