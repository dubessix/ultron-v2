"""Phase 4 regressions for the approved reference-style truthful left panel."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LEFT_PANEL = ROOT / "frontend" / "src" / "components" / "LeftPanel.jsx"
METRIC_UTIL = ROOT / "frontend" / "src" / "utils" / "metricHistory.js"


class TestReferenceStyleLeftPanel(unittest.TestCase):
    def test_left_panel_has_trend_network_and_current_detail_hierarchy(self):
        source = LEFT_PANEL.read_text(encoding="utf-8")
        self.assertIn("System overview", source)
        self.assertIn("TrendMetricCard", source)
        self.assertIn("MiniSparkline", source)
        self.assertIn("Telemetry link", source)
        self.assertIn("Local round trip", source)
        self.assertIn("TX rate", source)
        self.assertIn("RX rate", source)
        self.assertIn("DetailMetricCard", source)
        self.assertIn("CPU load", source)
        self.assertIn("RAM usage", source)
        self.assertIn("System status", source)
        self.assertIn("backendStatus", source)
        self.assertIn("formatPlatform", source)

    def test_left_panel_uses_vector_icons_and_contains_no_excluded_or_fake_ui(self):
        source = LEFT_PANEL.read_text(encoding="utf-8")
        self.assertIn("from 'lucide-react'", source)
        for icon in ("Activity", "Network", "ArrowUp", "ArrowDown", "Cpu", "MemoryStick", "Thermometer", "MonitorCog"):
            self.assertIn(icon, source)
        for forbidden in (
            "VISION FEED",
            "Camera",
            "Edge Search",
            "37.2",
            "82.2",
            "55.0",
            "31ms",
            "43%",
            "62%",
        ):
            self.assertNotIn(forbidden, source)
        self.assertNotRegex(source, r"[\U0001F000-\U0001FAFF\u2600-\u27BF]")

    def test_app_shell_passes_real_backend_state_to_left_panel(self):
        shell = (ROOT / "frontend" / "src" / "components" / "AppShell.jsx").read_text(encoding="utf-8")
        self.assertIn("<LeftPanel systemMetrics={systemMetrics} backendStatus={backendStatus} />", shell)

    def test_sparkline_points_are_derived_only_from_reported_values(self):
        script = f"""
import {{ sparklinePoints }} from {json.dumps(METRIC_UTIL.as_uri())};
const normal = sparklinePoints([0, 50, 100], 100, 32);
const flat = sparklinePoints([25, 25, 25], 100, 32);
const missing = sparklinePoints([], 100, 32);
console.log(JSON.stringify({{ normal, flat, missing }}));
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
        self.assertEqual(len(payload["normal"].split()), 3)
        self.assertEqual(len(payload["flat"].split()), 3)
        self.assertEqual(payload["missing"], "")
        for point in payload["normal"].split() + payload["flat"].split():
            self.assertRegex(point, r"^\d+(?:\.\d+)?,\d+(?:\.\d+)?$")


if __name__ == "__main__":
    unittest.main()
