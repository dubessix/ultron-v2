"""C6 contracts for canonical voice transport, metadata and exact safety."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "frontend" / "src" / "App.jsx"


class TestCanonicalVoiceTransport(unittest.TestCase):
    def _voice_block(self) -> str:
        source = APP.read_text(encoding="utf-8")
        start = source.index("const handleVoiceCommand = async")
        end = source.index("// Dispatch REST messages", start)
        return source[start:end]

    def test_voice_uses_latest_session_and_explicit_project_once(self):
        source = APP.read_text(encoding="utf-8")
        voice = self._voice_block()

        self.assertIn("const sessionIdRef = useRef(sessionId)", source)
        self.assertIn("const voiceRequestInFlightRef = useRef(false)", source)
        self.assertIn("voiceRequestInFlightRef.current", voice)
        self.assertIn("session_id: sessionIdRef.current", voice)
        self.assertIn('project_id: "personal"', voice)
        self.assertIn('input_source: "voice"', voice)
        self.assertEqual(voice.count("fetch(`${apiUrl}/api/chat`"), 1)
        self.assertNotIn("sendViaWS", voice)
        self.assertIn("voiceRequestInFlightRef.current = false", voice)

    def test_voice_preserves_canonical_response_metadata_and_events(self):
        voice = self._voice_block()

        for contract in (
            "project_id: data.project_id",
            "intent: data.intent",
            "provider_route: data.provider_route",
            "voice_alias_suggestions: data.voice_alias_suggestions",
            "memory_provenance: data.memory_provenance",
            "events: data.events",
            "pending_confirmation: data.pending_confirmation",
            "setLogs(prev => [...prev, ...voiceLogs].slice(-80))",
            "handleCodingResponse(data)",
        ):
            self.assertIn(contract, voice)

    def test_exact_pending_token_is_forwarded_not_regenerated(self):
        voice = self._voice_block()

        self.assertIn("setPendingAction(data.pending_confirmation)", voice)
        self.assertIn("data.pending_confirmation?.confirmation_token", voice)
        self.assertNotIn("confirmation_token: Math", voice)
        self.assertNotIn("confirmation_token: crypto", voice)


if __name__ == "__main__":
    unittest.main()
