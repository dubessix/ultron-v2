"""C5 contracts for bounded browser-recognition restart and error policy."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VOICE = ROOT / "frontend" / "src" / "hooks" / "useVoice.js"


class TestBoundedRecognitionRestart(unittest.TestCase):
    def test_restart_has_delay_cap_attempt_cap_and_one_timer(self):
        source = VOICE.read_text(encoding="utf-8")

        self.assertIn("const RESTART_BASE_MS = 500", source)
        self.assertIn("const RESTART_MAX_MS = 4000", source)
        self.assertIn("const RESTART_MAX_ATTEMPTS = 5", source)
        self.assertIn("restartTimerRef.current", source)
        self.assertIn("restartAttemptRef.current", source)
        self.assertIn("if (restartAttemptRef.current >= RESTART_MAX_ATTEMPTS)", source)
        self.assertIn("Math.min(", source)
        self.assertIn("scheduleRestart(recognizer)", source)
        self.assertNotIn("try { rec.start(); } catch (_e) {}\n      }\n    };", source)

    def test_manual_stop_pause_and_cleanup_cancel_restart(self):
        source = VOICE.read_text(encoding="utf-8")
        stop_block = source[source.index("const stop = useCallback") : source.index("useEffect(() => {", source.index("const stop = useCallback"))]
        pause_block = source[source.index("// Processing/TTS remains an explicit App-level pause") :]

        self.assertIn("clearRestartTimer()", stop_block)
        self.assertIn("restartAttemptRef.current = 0", stop_block)
        self.assertIn("clearRestartTimer()", pause_block)
        self.assertIn("restartAttemptRef.current = 0", pause_block)
        self.assertIn("clearRestartTimer();", source[source.rindex("useEffect(() => () =>") :])


class TestRecognitionErrorPolicy(unittest.TestCase):
    def test_fatal_and_recoverable_errors_are_distinct(self):
        source = VOICE.read_text(encoding="utf-8")

        for error_name in (
            "'not-allowed'",
            "'audio-capture'",
            "'network'",
            "'service-not-allowed'",
            "'language-not-supported'",
            "'bad-grammar'",
        ):
            self.assertIn(error_name, source)
        self.assertIn("event.error === 'aborted'", source)
        self.assertIn("event.error === 'no-speech'", source)
        self.assertIn("Browser speech recognition is reconnecting…", source)
        self.assertIn("clearRestartTimer()", source)
        self.assertIn("Voice recognition could not restart. Use Stop and Start Voice to retry.", source)


if __name__ == "__main__":
    unittest.main()
