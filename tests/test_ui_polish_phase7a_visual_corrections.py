"""Phase 7A regressions for metric typography and centre-core scale."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LEFT = ROOT / "frontend" / "src" / "components" / "LeftPanel.jsx"
CORE = ROOT / "frontend" / "src" / "components" / "BlobCanvas.jsx"


class TestMetricCardTypography(unittest.TestCase):
    def test_top_metric_values_and_suffixes_cannot_wrap(self):
        source = LEFT.read_text(encoding="utf-8")
        trend = re.search(r"function TrendMetricCard[\s\S]+?\n}\n\nfunction MiniSparkline", source)
        self.assertIsNotNone(trend)
        block = trend.group(0)
        self.assertIn("whitespace-nowrap", block)
        self.assertIn("shrink-0", block)
        self.assertNotIn("break-words", block)
        self.assertIn("isUnavailable", block)

    def test_missing_sensor_does_not_claim_it_is_collecting_a_trend(self):
        source = LEFT.read_text(encoding="utf-8")
        self.assertIn("available={temperature !== null}", source)
        self.assertIn("if (!available)", source)
        self.assertIn("No sensor", source)
        self.assertIn("sparklinePoints(values, 58, 24)", source)


class TestCentreCoreScale(unittest.TestCase):
    def test_core_uses_larger_but_still_bounded_canvas_geometry(self):
        source = CORE.read_text(encoding="utf-8")
        self.assertIn("isFullHdViewport ? 640 : 520", source)
        self.assertIn("const width = canvasSize", source)
        self.assertIn("const height = canvasSize", source)
        self.assertIn("138 + Math.sin", source)
        self.assertIn("210 * presentationScale * coreScale", source)
        self.assertIn("215 * presentationScale * coreScale", source)
        self.assertIn("const displaySize", source)
        self.assertIn("max-w-full", source)


if __name__ == "__main__":
    unittest.main()
