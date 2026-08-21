"""
Ultron Central Voice Coordinator
Manages conversational voice lifecycles, publishes events to the Event Bus,
loads dynamic config parameters, and coordinates speech generations.
"""

import yaml
import asyncio
from typing import Dict, Any, Optional, AsyncGenerator, List

from backend.app.voice.base_voice_provider import BaseVoiceProvider
from backend.app.voice.interrupt_handler import InterruptHandler
from backend.app.install_paths import CONFIG_PATH

def _get_default_provider() -> BaseVoiceProvider:
    """Lazily construct the default TTS provider.

    edge_tts (and its dependencies) is only imported/loaded on first voice use,
    so it is NOT pulled into memory at backend boot time — keeping startup light
    on 8GB / dual-core hosts while preserving all voice functionality.
    """
    from backend.app.voice.edge_tts_provider import EdgeTTSProvider
    return EdgeTTSProvider()

class VoiceSystem:
    def __init__(self, provider: Optional[BaseVoiceProvider] = None) -> None:
        # Lazy default provider: only load edge_tts when actually needed.
        self.provider = provider if provider is not None else _get_default_provider()
        self.interrupter = InterruptHandler()
        
        # Local event tracking array (Event Bus Integration - Requirement 2)
        self.dispatched_events: List[Dict[str, Any]] = []
        
        # Load voice settings from config.yaml
        self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Loads voice settings dynamically from config.yaml."""
        if not CONFIG_PATH.exists():
            return {}
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                return config.get("voice", {})
        except Exception:
            return {}

    def _dispatch_voice_event(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """Publishes standardized voice lifecycle events to the Event Bus (Requirement 1, 2)."""
        event = {
            "type": event_type,
            "payload": payload or {}
        }
        self.dispatched_events.append(event)
        print(f"[EVENT_BUS] Voice Lifecycle: {event_type} -> {payload or {}}")

    async def speak(self, text: str, personality: str = "ultron") -> AsyncGenerator[bytes, None]:
        """
        Synthesizes speech asynchronously based on active personality configs.
        Publishes 'speaking_started' and 'playback_finished' events.
        """
        # Clean the text so TTS reads naturally (no ellipses, emoji, markdown, bullets).
        from backend.app.utils.text_cleaner import clean_for_speech
        text = clean_for_speech(text)

        # 1. Fetch personality configuration from config.yaml (Requirement 3, 4)
        pers_config = self._config.get(personality.lower(), {})
        voice_id = pers_config.get("voice_id", "en-US-GuyNeural")
        rate = pers_config.get("rate", "+10%")
        pitch = pers_config.get("pitch", "+0Hz")

        self._dispatch_voice_event("thinking_started")
        self._dispatch_voice_event("speaking_started", {
            "personality": personality,
            "voice_id": voice_id,
            "rate": rate,
            "pitch": pitch
        })

        try:
            # Generate speech packets via abstract provider (Requirement 5).
            # Register the CURRENT async task with the interrupter so a barge-in
            # (user starts speaking) can actually cancel this synthesis stream.
            generator = self.provider.generate_speech(
                text=text,
                voice_id=voice_id,
                rate=rate,
                pitch=pitch
            )
            current_task = asyncio.current_task()
            if current_task is not None:
                self.interrupter.register_task(current_task)

            try:
                async for chunk in generator:
                    yield chunk
            finally:
                self.interrupter.register_task(None)
                
            self._dispatch_voice_event("playback_finished")
            self._dispatch_voice_event("idle")
            
        except asyncio.CancelledError:
            self._dispatch_voice_event("interrupted")
            self._dispatch_voice_event("idle")
            raise
        except Exception as e:
            print(f"[VOICE_SYSTEM] Speech provider unavailable: {e}")
            self._dispatch_voice_event("idle")
            raise

    def handle_user_barge_in(self) -> bool:
        """Triggered when client mic registers voice, cancelling active speech task."""
        self._dispatch_voice_event("speech_detected")
        interrupted = self.interrupter.trigger_interrupt()
        if interrupted:
            self._dispatch_voice_event("interrupted")
            self._dispatch_voice_event("idle")
        return interrupted

    def start_listening(self) -> None:
        """Triggered when client mic is activated."""
        self._dispatch_voice_event("listening_started")
