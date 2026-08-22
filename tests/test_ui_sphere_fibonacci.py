"""Regression contracts for the approved dense Fibonacci particle Core."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "frontend" / "src" / "components" / "BlobCanvas.jsx"
GEOMETRY = ROOT / "frontend" / "src" / "utils" / "sphereGeometry.js"
THEME = ROOT / "frontend" / "src" / "theme" / "personalityTheme.js"
APP = ROOT / "frontend" / "src" / "App.jsx"


class TestSphereGeometry(unittest.TestCase):
    def test_fibonacci_geometry_is_deterministic_unit_length_and_finite(self):
        script = f"""
import {{ createFibonacciSphere, rotateSpherePoint, projectSpherePoint, particleCountForViewport, mixRgb }} from {json.dumps(GEOMETRY.as_uri())};
const first = createFibonacciSphere(1300);
const second = createFibonacciSphere(1300);
const norms = first.map(p => Math.sqrt(p.x*p.x + p.y*p.y + p.z*p.z));
const rotated = rotateSpherePoint(first[37], 0.8, -0.18, 0.07);
const projected = projectSpherePoint(rotated, 260, 260, 200, 1.02);
console.log(JSON.stringify({{
  length: first.length,
  deterministic: JSON.stringify(first.slice(0, 20)) === JSON.stringify(second.slice(0, 20)),
  minNorm: Math.min(...norms),
  maxNorm: Math.max(...norms),
  projected,
  full: particleCountForViewport(1920, 1080),
  normal: particleCountForViewport(1440, 900),
  compact: particleCountForViewport(900, 500),
  mixed: mixRgb([0, 10, 20], [100, 110, 120], 0.5)
}}));
"""
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["length"], 1300)
        self.assertTrue(data["deterministic"])
        self.assertAlmostEqual(data["minNorm"], 1.0, places=6)
        self.assertAlmostEqual(data["maxNorm"], 1.0, places=6)
        self.assertTrue(all(isinstance(data["projected"][key], (int, float)) for key in ("x", "y", "z", "depth")))
        self.assertEqual((data["full"], data["normal"], data["compact"]), (1300, 1050, 700))
        self.assertEqual(data["mixed"], [50, 60, 70])

    def test_core_has_no_random_remount_or_idle_orbit_ellipse(self):
        source = CORE.read_text(encoding="utf-8")
        self.assertIn("createFibonacciSphere", source)
        self.assertIn("rotateSpherePoint", source)
        self.assertIn("projectSpherePoint", source)
        self.assertIn("sort((left, right) => left.z - right.z)", source)
        self.assertNotIn("Math.random", source)
        self.assertNotIn("ctx.ellipse", source)

    def test_all_cognitive_states_remain_distinct_and_animated(self):
        source = CORE.read_text(encoding="utf-8")
        for state in (
            "listening",
            "wake_word_detected",
            "thinking",
            "planning",
            "working",
            "speaking",
            "interrupted",
            "background",
            "sleep",
        ):
            self.assertIn(state, source)
        self.assertIn("requestAnimationFrame", source)
        self.assertIn("cancelAnimationFrame", source)
        self.assertIn("prefers-reduced-motion", source)
        self.assertIn("profile.connections", source)
        self.assertIn("profile.halo", source)


class TestSpherePersonality(unittest.TestCase):
    def test_ultron_and_zora_use_same_geometry_with_distinct_palettes(self):
        script = f"""
import {{ getPersonalityTheme }} from {json.dumps(THEME.as_uri())};
const ultron = getPersonalityTheme('ultron');
const zora = getPersonalityTheme('zora');
console.log(JSON.stringify({{
  ultronFar: ultron.coreFarRgb,
  ultronNear: ultron.coreNearRgb,
  zoraFar: zora.coreFarRgb,
  zoraNear: zora.coreNearRgb,
  ultronInner: ultron.coreInnerGlow,
  zoraInner: zora.coreInnerGlow
}}));
"""
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["ultronFar"], [12, 48, 52])
        self.assertEqual(data["ultronNear"], [80, 245, 218])
        self.assertEqual(data["zoraFar"], [58, 10, 38])
        self.assertEqual(data["zoraNear"], [255, 72, 144])
        self.assertNotEqual(data["ultronInner"], data["zoraInner"])

        source = CORE.read_text(encoding="utf-8")
        self.assertIn("getPersonalityTheme(personality)", source)
        self.assertIn("activeTheme.coreFarRgb", source)
        self.assertIn("activeTheme.coreNearRgb", source)
        self.assertNotIn("personality === 'zora'", source)

    def test_canvas_is_accessible_and_keeps_existing_laptop_bounds(self):
        source = CORE.read_text(encoding="utf-8")
        self.assertIn("isFullHdViewport ? 640 : 520", source)
        self.assertIn('role="img"', source)
        self.assertIn("dense particle core", source)
        self.assertIn("ultron-core-canvas", source)
        self.assertIn("Math.min(window.devicePixelRatio || 1, 2)", source)

    def test_notification_timer_callbacks_are_stable_during_animation_renders(self):
        source = APP.read_text(encoding="utf-8")
        self.assertIn("const addNotification = useCallback", source)
        self.assertIn("const dismissNotification = useCallback", source)
        self.assertIn("}, []);", source)


if __name__ == "__main__":
    unittest.main()
