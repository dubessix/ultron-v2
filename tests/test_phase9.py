"""
Ultron Unit & Integration Testing Suite — Phase 9 Diagnostics
Tests BaseVoiceProvider abstract strategies, config-driven personality voices,
Event Bus lifecycle events, and async barge-in task cancellations.
"""

import unittest
import asyncio
from typing import AsyncGenerator

from backend.app.voice.base_voice_provider import BaseVoiceProvider
from backend.app.voice.voice_system import VoiceSystem

# Define custom mock provider to verify Strategy pattern & OCP
class MockAlternativeVoiceProvider(BaseVoiceProvider):
    async def generate_speech(
        self,
        text: str,
        voice_id: str,
        rate: str = "+0%",
        pitch: str = "+0Hz"
    ) -> AsyncGenerator[bytes, None]:
        for i in range(2):
            yield b"MOCK_ALTERNATIVE_WAV_CHUNK"
            await asyncio.sleep(0.01)

class TestPhase9VoiceSystemArchitecture(unittest.IsolatedAsyncioTestCase):
    
    def test_voice_provider_abstraction_strategy(self):
        """Test 1: Verify dynamic custom subclassing of BaseVoiceProvider."""
        custom_provider = MockAlternativeVoiceProvider()
        self.assertIsInstance(custom_provider, BaseVoiceProvider)

    def test_config_driven_personality_voices(self):
        """Test 2: Verify Ultron and Zora retrieve distinct voice parameters from config.yaml."""
        system = VoiceSystem()
        
        # Pull configurations
        ultron_config = system._config.get("ultron", {})
        zora_config = system._config.get("zora", {})
        
        # Verify separate voices
        self.assertEqual(ultron_config.get("voice_id"), "en-US-GuyNeural")
        self.assertEqual(zora_config.get("voice_id"), "en-IN-NeerjaNeural")
        
        # Verify separate speech rates
        self.assertNotEqual(ultron_config.get("rate"), zora_config.get("rate"))

    async def test_event_bus_lifecycle_publications(self):
        """Test 3: Assert voice lifecycle dispatches correct events to the Event Bus."""
        # Use mock provider to avoid live cloud connection delays
        system = VoiceSystem(provider=MockAlternativeVoiceProvider())
        system.dispatched_events.clear()
        
        # Trigger listening
        system.start_listening()
        self.assertEqual(system.dispatched_events[-1]["type"], "listening_started")
        
        # Trigger speaking
        chunks = []
        async for chunk in system.speak("Hello Debjeet.", personality="zora"):
            chunks.append(chunk)
            
        # Verify retrieved chunk counts
        self.assertEqual(len(chunks), 2)
        
        # Verify correct event lifecycles in order
        event_types = [ev["type"] for ev in system.dispatched_events]
        self.assertIn("thinking_started", event_types)
        self.assertIn("speaking_started", event_types)
        self.assertIn("playback_finished", event_types)
        self.assertIn("idle", event_types)

    async def test_barge_in_task_cancellation(self):
        """Test 4: Verify async barge-in cancellation and 'interrupted' event fire."""
        system = VoiceSystem(provider=MockAlternativeVoiceProvider())
        system.dispatched_events.clear()

        # Define slow speech loop to allow cancellation
        async def dummy_slow_speak():
            try:
                async for _ in system.speak("Wait, let me explain.", personality="ultron"):
                    await asyncio.sleep(1.0) # Slow sleep interval
            except asyncio.CancelledError:
                pass

        # Spawn active task
        task = asyncio.create_task(dummy_slow_speak())
        system.interrupter.register_task(task)
        
        # Yield loop
        await asyncio.sleep(0.01)
        
        # Trigger user barge-in
        interrupted = system.handle_user_barge_in()
        self.assertTrue(interrupted)
        
        # Yield control back to event loop so task cancellation can process (Requirement 5)
        await asyncio.sleep(0.01)
        
        # Assert task was cancelled
        self.assertTrue(task.cancelled() or task.done())
        
        # Verify event bus logged the interruption
        event_types = [ev["type"] for ev in system.dispatched_events]
        self.assertIn("speech_detected", event_types)
        self.assertIn("interrupted", event_types)
