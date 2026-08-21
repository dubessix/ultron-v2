"""Microsoft Edge-TTS streaming provider with explicit failure semantics."""

from __future__ import annotations

from typing import AsyncGenerator

from backend.app.voice.base_voice_provider import BaseVoiceProvider


class EdgeTTSProvider(BaseVoiceProvider):
    async def generate_speech(
        self,
        text: str,
        voice_id: str,
        rate: str = "+0%",
        pitch: str = "+0Hz",
    ) -> AsyncGenerator[bytes, None]:
        """Yield only audio packets returned by Edge TTS; never synthesize fake bytes."""
        if not text.strip():
            raise ValueError("Speech text is empty.")
        if not voice_id.strip():
            raise ValueError("Voice ID is empty.")

        import edge_tts

        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice_id,
                rate=rate,
                pitch=pitch,
            )
            produced_audio = False
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    produced_audio = True
                    yield chunk["data"]
            if not produced_audio:
                raise RuntimeError("Edge TTS returned no audio packets.")
        except Exception as exc:
            raise RuntimeError(f"Edge TTS unavailable: {exc}") from exc
