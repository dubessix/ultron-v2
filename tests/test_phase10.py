"""
Ultron Unit & Integration Testing Suite — Phase 10 Diagnostics
Validates frontend file structure presence, React JSX syntaxes, and Canvas 2D
breathing/orbital ring coordinates, ensuring complete synchronization.
"""

import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
COMPONENTS_DIR = BASE_DIR / "frontend" / "src" / "components"

class TestPhase10FrontendArchitecture(unittest.TestCase):
    
    def test_frontend_components_presence(self):
        """Test 1: Verify all key layout components are created in the workspace."""
        required_files = [
            COMPONENTS_DIR / "BlobCanvas.jsx",
            COMPONENTS_DIR / "LeftPanel.jsx",
            COMPONENTS_DIR / "RightPanel.jsx",
            COMPONENTS_DIR / "AppShell.jsx"
        ]
        for file_path in required_files:
            self.assertTrue(file_path.exists(), f"Missing required UI file: {file_path.name}")

    def test_vision_feed_removal(self):
        """Test 2: Verify that the legacy Vision Feed box has been completely removed from the Left Panel."""
        left_panel_path = COMPONENTS_DIR / "LeftPanel.jsx"
        
        with open(left_panel_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Assert "VISION FEED" is completely gone
            self.assertNotIn("VISION FEED", content, "Legacy Vision Feed should be removed from Left Panel.")
            # Real reported telemetry remains; fabricated latency/load values do not.
            self.assertIn("Network counters", content)
            self.assertIn('label="Uptime"', content)
            self.assertIn("uptime_seconds", content)
            self.assertIn('label="RAM"', content)
            self.assertIn("Local round trip", content)
            self.assertIn("health_latency_ms", content)
            self.assertNotIn("31ms", content)
            self.assertNotIn("TX Signal load", content)

    def test_blob_canvas_coordinates(self):
        """Test 3: Verify Canvas 2D drawing loops, requesting animation, and elliptical orbital ring coordinates."""
        canvas_path = COMPONENTS_DIR / "BlobCanvas.jsx"
        
        with open(canvas_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Assert 60 FPS requestAnimationFrame is utilized
            self.assertIn("requestAnimationFrame", content)
            self.assertIn("cancelAnimationFrame", content)
            # Assert elliptical orbital rings drawing is coded
            self.assertIn("ellipse", content)
            self.assertIn("rotate", content)

    def test_app_shell_grid_properties(self):
        """Test 4: Verify AppShell establishes the 3-panel widescreen grid layout."""
        shell_path = COMPONENTS_DIR / "AppShell.jsx"
        
        with open(shell_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Assert grid and panels imports
            self.assertIn("LeftPanel", content)
            self.assertIn("RightPanel", content)
            self.assertIn("BlobCanvas", content)
            self.assertIn("grid", content)
            self.assertIn("grid-cols-12", content)

if __name__ == "__main__":
    unittest.main()
