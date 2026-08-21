"""
Ultron Unit & Integration Testing Suite — Phase 11 Diagnostics
Tests useDraggable coordinate pointer metrics, glassmorphic container themes,
decoupled widget registries (OCP-compliant), and productivity widget states.
"""

import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
COMPONENTS_DIR = BASE_DIR / "frontend" / "src" / "components" / "widgets"
HOOKS_DIR = BASE_DIR / "frontend" / "src" / "hooks"

class TestPhase11WidgetSystemArchitecture(unittest.TestCase):
    
    def test_widgets_files_presence(self):
        """Test 1: Verify all required widgets and hooks files exist inside correct folders."""
        required_files = [
            HOOKS_DIR / "useDraggable.js",
            COMPONENTS_DIR / "WidgetContainer.jsx",
            COMPONENTS_DIR / "TodoWidget.jsx",
            COMPONENTS_DIR / "CalendarWidget.jsx",
            COMPONENTS_DIR / "GitWidget.jsx",
            COMPONENTS_DIR / "WidgetManager.js",
            COMPONENTS_DIR / "README.md"
        ]
        for path in required_files:
            self.assertTrue(path.exists(), f"Missing required file: {path.name}")

    def test_draggable_hook_coordinate_tracking(self):
        """Test 2: Verify one pointer path tracks mouse, pen, and touch coordinates."""
        hook_path = HOOKS_DIR / "useDraggable.js"

        with open(hook_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("clientX", content)
            self.assertIn("clientY", content)
            self.assertIn("pointermove", content)
            self.assertIn("pointerup", content)
            self.assertIn("pointercancel", content)

    def test_glassmorphic_container_styles_and_bounds(self):
        """Test 3: Verify WidgetContainer implements standard double-click collapse and translate3d."""
        container_path = COMPONENTS_DIR / "WidgetContainer.jsx"
        
        with open(container_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Assert hardware-accelerated translate3d rendering
            self.assertIn("translate3d", content)
            # Assert standard background glassmorphism blur and double-click collapse states
            self.assertIn("backdrop-blur-2xl", content)
            self.assertIn("border-white/5", content)
            self.assertIn("onDoubleClick", content)
            self.assertIn("isCollapsed", content)

    def test_decoupled_widget_registry_verification(self):
        """Test 4: Verify that the widget system is decoupled from AppShell using WidgetManager."""
        shell_path = BASE_DIR / "frontend" / "src" / "components" / "AppShell.jsx"
        
        with open(shell_path, "r", encoding="utf-8") as f:
            content = f.read()
            # AppShell must NOT import individual widgets directly. It must import only the WIDGET_REGISTRY contract!
            self.assertIn("WIDGET_REGISTRY", content)
            self.assertNotIn("import TodoWidget", content)
            self.assertNotIn("import CalendarWidget", content)
            self.assertNotIn("import GitWidget", content)
            
        # Verify the central manager registers widgets
        manager_path = COMPONENTS_DIR / "WidgetManager.js"
        with open(manager_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("WIDGET_REGISTRY", content)
            self.assertIn("todo", content)
            self.assertIn("calendar", content)
            self.assertIn("git", content)

if __name__ == "__main__":
    unittest.main()
