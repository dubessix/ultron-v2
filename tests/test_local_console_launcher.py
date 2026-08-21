"""Contracts for the owner-approved local desktop icon and terminal loader flow."""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "launcher.py"
INSTALLER = ROOT / "backend" / "app" / "installer.py"
KEYS = ROOT / "backend" / "app" / "brain" / "api_key_manager.py"
ENV_EXAMPLE = ROOT / ".env.example"
README = ROOT / "README.md"
SETUP_GUIDE = ROOT / "SETUP_GUIDE.md"


class TestTerminalLoaderContract(unittest.TestCase):
    def test_launcher_has_minimal_coloured_terminal_header(self):
        source = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("TERMINAL_EMERALD", source)
        self.assertIn("TERMINAL_CYAN", source)
        self.assertIn("TERMINAL_TEAL", source)
        self.assertIn("TERMINAL_WHITE", source)
        self.assertIn("TERMINAL_DIM", source)
        self.assertIn('("ULTRON", TERMINAL_EMERALD)', source)
        self.assertIn('subtitle_left = "  Personal AI Assistant"', source)
        self.assertIn('subtitle_right = "Local Startup Console"', source)
        self.assertIn("console_segments", source)
        self.assertNotIn("ULTRON_PIXEL_GLYPHS", source)
        self.assertNotIn("██", source)
        self.assertNotIn("figlet", source.lower())

    def test_launcher_reports_five_real_steps_and_ready_url(self):
        source = LAUNCHER.read_text(encoding="utf-8")
        for text in (
            "Checking installation assets",
            "Loading private configuration",
            "Starting backend service",
            "Starting dashboard service",
            "AI Core",
            "ULTRON IS ONLINE",
            "Dashboard",
            "Keep this window open",
        ):
            self.assertIn(text, source)
        self.assertIn("self.backend_port", source)
        self.assertIn("self.frontend_port", source)

    def test_terminal_metadata_and_ai_status_are_truthful(self):
        source = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("self.version", source)
        self.assertIn("time.monotonic()", source)
        self.assertIn("LOCAL ONLY", source)
        self.assertIn("live reachability not checked at startup", source)
        self.assertNotIn("runtime 7h24m", source)
        self.assertNotIn("codename: OMEGA", source)
        self.assertNotIn("Intelligence online", source)

    def test_console_output_can_be_duplicated_to_private_log(self):
        source = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("ULTRON_LAUNCH_LOG", source)
        self.assertIn("launch_log_path", source)
        self.assertIn("launcher-ui.log", (README.read_text(encoding="utf-8") + SETUP_GUIDE.read_text(encoding="utf-8")))


class TestDesktopShortcutContract(unittest.TestCase):
    def test_installer_generates_start_stop_doctor_env_and_key_scripts(self):
        source = INSTALLER.read_text(encoding="utf-8")
        for key in ('"start"', '"stop"', '"doctor"', '"env"', '"settings"'):
            self.assertIn(key, source)
        self.assertIn("Ultron Doctor", source)
        self.assertIn("Open Ultron .env", source)

    def test_start_shortcuts_show_terminal_and_keep_logging(self):
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("ULTRON_LAUNCH_LOG", source)
        self.assertIn("WindowStyle=", source)
        self.assertIn('(\"Ultron\", paths[\"start\"], True', source)
        self.assertIn('(\"Ultron Doctor\", paths[\"doctor\"], True', source)
        self.assertIn("launcher-ui.log", source)

    def test_root_start_scripts_use_the_same_private_launch_log(self):
        windows = (ROOT / "start_ultron.bat").read_text(encoding="utf-8")
        ubuntu = (ROOT / "start_ultron.sh").read_text(encoding="utf-8")
        self.assertIn("ULTRON_LAUNCH_LOG", windows)
        self.assertIn("ULTRON_LAUNCH_LOG", ubuntu)
        self.assertIn("launcher-ui.log", windows)
        self.assertIn("launcher-ui.log", ubuntu)


class TestManualEnvKeySlots(unittest.TestCase):
    def test_each_ai_provider_supports_four_non_contiguous_slots(self):
        source = KEYS.read_text(encoding="utf-8")
        match = re.search(r"limits\s*=\s*(\{[^\n]+\})", source)
        self.assertIsNotNone(match)
        self.assertIn('"groq": 4', match.group(1))
        self.assertIn('"gemini": 4', match.group(1))
        self.assertIn('"nvidia": 4', match.group(1))

    def test_env_template_documents_all_four_slots(self):
        source = ENV_EXAMPLE.read_text(encoding="utf-8")
        for provider in ("GROQ", "GEMINI", "NVIDIA"):
            for index in range(1, 5):
                self.assertIn(f"{provider}_API_KEY_{index}=", source)

    def test_placeholder_slot_one_and_real_slots_three_four_load_only_real_keys(self):
        from backend.app.brain.api_key_manager import APIKeyManager

        env = {
            "GROQ_API_KEY_1": "your_groq_api_key_1_here",
            "GROQ_API_KEY_2": "",
            "GROQ_API_KEY_3": "real-groq-three",
            "GROQ_API_KEY_4": "real-groq-four",
        }
        with patch.dict(os.environ, env, clear=True):
            manager = APIKeyManager()
            self.assertEqual(manager.runtime_status()["groq"]["active"], 2)
            self.assertEqual(manager.get_active_key("groq"), "real-groq-three")
            self.assertEqual(manager.get_active_key("groq"), "real-groq-four")

    def test_readme_explains_placeholder_and_non_contiguous_keys(self):
        source = README.read_text(encoding="utf-8")
        self.assertIn("GROQ_API_KEY_4", source)
        self.assertIn("placeholders", source.lower())
        self.assertIn("non-contiguous", source.lower())
        self.assertIn(".env", source)


if __name__ == "__main__":
    unittest.main()
