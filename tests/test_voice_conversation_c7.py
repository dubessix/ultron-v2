"""C7 contracts for truthful one-wake voice-session UI."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SHELL = ROOT / "frontend" / "src" / "components" / "AppShell.jsx"


class TestTruthfulVoiceSessionUi(unittest.TestCase):
    def test_mic_control_follows_session_state_not_transient_recognizer_state(self):
        source = SHELL.read_text(encoding="utf-8")

        self.assertIn('voiceEnabled ? "Stop voice session" : "Start voice session"', source)
        self.assertIn("aria-pressed={voiceEnabled}", source)
        self.assertIn('onVoiceStop?.("voice_session_stopped")', source)
        self.assertNotIn('aria-label={voice.isListening ? "Stop voice listening"', source)

    def test_ui_distinguishes_every_real_voice_state(self):
        source = SHELL.read_text(encoding="utf-8")

        for text in (
            "Voice session off.",
            "Voice paused — Ultron is speaking.",
            "Voice paused — Ultron is working.",
            "Voice reconnecting…",
            "Wake phrase heard — speak your command.",
            "Say “Ultron” to start a voice command.",
            "WAKE DETECTED",
            "COMMAND CAPTURE",
        ):
            self.assertIn(text, source)
        self.assertNotIn("WAKED", source)
        self.assertNotIn("Listening for wake word...", source)

    def test_real_heard_text_and_errors_have_explicit_testable_surfaces(self):
        source = SHELL.read_text(encoding="utf-8")

        self.assertIn('data-testid="voice-status"', source)
        self.assertIn('data-testid="voice-heard-text"', source)
        self.assertIn("Heard: {voice.heardText}", source)
        self.assertIn("voiceEnabled && voice.voiceError", source)
        self.assertIn("voice.conversationActive && voice.heardText", source)
        self.assertIn("pointer-events-none absolute bottom-20 right-6", source)


if __name__ == "__main__":
    unittest.main()
