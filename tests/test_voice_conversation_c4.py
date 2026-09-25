"""C4 contracts for half-duplex browser recognition and real TTS completion."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VOICE = ROOT / "frontend" / "src" / "hooks" / "useVoice.js"
APP = ROOT / "frontend" / "src" / "App.jsx"
SHELL = ROOT / "frontend" / "src" / "components" / "AppShell.jsx"


class TestRecognitionPauseContract(unittest.TestCase):
    def test_processing_and_tts_pause_reaches_the_live_recognizer(self):
        app = APP.read_text(encoding="utf-8")
        shell = SHELL.read_text(encoding="utf-8")
        voice = VOICE.read_text(encoding="utf-8")

        self.assertIn("voicePaused={isProcessing || isSpeaking}", app)
        self.assertIn("onVoiceStop={stopSpeaking}", app)
        self.assertIn("paused: Boolean(voicePaused)", shell)
        self.assertIn('onVoiceStop?.("voice_session_stopped")', shell)
        self.assertIn("paused = false", voice)
        self.assertIn("pausedRef.current || !enabledRef.current", voice)

    def test_pause_aborts_buffered_audio_and_returns_option_a_to_wake_only(self):
        voice = VOICE.read_text(encoding="utf-8")
        pause_block = voice[voice.index("// Processing/TTS remains an explicit App-level pause") :]

        self.assertIn("recognizer.abort()", pause_block)
        self.assertIn("resetTurn(false)", pause_block)
        self.assertIn("clearRestartTimer()", pause_block)
        self.assertIn("restartAttemptRef.current = 0", pause_block)
        self.assertIn("if (!fatalRef.current && !recognizerRunningRef.current)", pause_block)
        self.assertIn("recognizer.start()", pause_block)


class TestRealPlaybackLifecycleContract(unittest.TestCase):
    def test_speaking_state_uses_real_audio_completion_not_fixed_timer(self):
        app = APP.read_text(encoding="utf-8")

        self.assertIn("const [isSpeaking, setIsSpeaking] = useState(false)", app)
        self.assertIn('audio.onended = () => controller.finish("ended")', app)
        self.assertIn("audio.onerror = () =>", app)
        self.assertIn("URL.revokeObjectURL(url)", app)
        self.assertIn("await speakResponse(spoken, activePersonality", app)
        self.assertNotIn("audio.play().catch(() => {})", app)
        self.assertNotIn("}, 1200);", app)

    def test_playback_failure_and_intentional_stop_settle_the_same_controller(self):
        app = APP.read_text(encoding="utf-8")

        self.assertIn('stopSpeaking("replaced")', app)
        self.assertIn("current.finish(reason)", app)
        self.assertIn("Promise.resolve(playResult).catch", app)
        self.assertIn('controller.finish("error"', app)
        self.assertIn('stopSpeaking("unmounted")', app)


if __name__ == "__main__":
    unittest.main()
