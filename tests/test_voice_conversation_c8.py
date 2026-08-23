"""C8 release contracts for the complete low-load voice conversation phase."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent


class TestFinalVoiceReleaseContract(unittest.TestCase):
    def test_runtime_keeps_browser_stt_and_only_approved_wake_phrases(self):
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()

        self.assertEqual(config["voice"]["wake_words"], ["hey ultron", "ultron"])
        for unapproved_runtime in ("openwakeword", "faster-whisper", "whispercpp", "vosk"):
            self.assertNotIn(unapproved_runtime, requirements)

    def test_voice_test_tools_are_dev_only_and_all_functional_suites_run(self):
        package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
        script = package["scripts"]["test:voice"]

        self.assertIn("useVoice.test.jsx", script)
        self.assertIn("App.voice.test.jsx", script)
        self.assertIn("AppShell.voice.test.jsx", script)
        for dependency in ("vitest", "jsdom", "@testing-library/react"):
            self.assertIn(dependency, package["devDependencies"])
            self.assertNotIn(dependency, package["dependencies"])

    def test_windows_and_ubuntu_cloud_enforce_voice_suite(self):
        workflow = (ROOT / ".github" / "workflows" / "ultron-cloud-test.yml").read_text(encoding="utf-8")

        self.assertIn("npm --prefix frontend run test:voice", workflow)
        self.assertIn("Voice conversation suite", workflow)
        self.assertIn("FRONTEND_VOICE", workflow)
        self.assertIn("steps.frontend_voice.outcome", workflow)

    def test_owner_docs_describe_one_wake_and_hardware_boundary(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        manual = (ROOT / "docs" / "ultron_daily_operating_manual.md").read_text(encoding="utf-8")
        testing = (ROOT / "docs" / "testing_strategy.md").read_text(encoding="utf-8")
        combined = "\n".join((readme, manual, testing))

        self.assertIn("says `Ultron` or `Hey Ultron` once", readme)
        self.assertIn("until pressing Stop Voice", readme)
        self.assertIn("Voice conversation active", manual)
        self.assertIn("controlled `SpeechRecognition`", testing)
        self.assertIn("not acoustic or audible proof", testing)
        self.assertIn("owner-laptop acceptance", combined)


if __name__ == "__main__":
    unittest.main()
