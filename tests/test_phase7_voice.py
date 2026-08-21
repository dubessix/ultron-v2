"""
Phase 7 regression — voice interrupt / barge-in correctness.

The core "command catching / listening" concern on the backend is that a user
speaking mid-playback must be able to interrupt active TTS. VoiceSystem.speak now
registers its async task with the InterruptHandler so a barge-in actually cancels
the synthesis stream (previously nothing was registered, so barge-in was a no-op).
"""

import asyncio
import unittest
from unittest.mock import patch

from backend.app.voice.interrupt_handler import InterruptHandler
from backend.app.voice.voice_system import VoiceSystem


def _run(coro):
    return asyncio.run(coro)


class TestInterruptHandler(unittest.TestCase):

    def test_trigger_interrupt_cancels_registered_task(self):
        handler = InterruptHandler()

        async def never_end():
            await asyncio.sleep(3600)

        async def scenario():
            task = asyncio.create_task(never_end())
            handler.register_task(task)
            self.assertTrue(handler.trigger_interrupt())
            await asyncio.sleep(0.05)
            return task

        task = _run(scenario())
        self.assertTrue(task.cancelled())

    def test_trigger_interrupt_returns_false_when_none_registered(self):
        handler = InterruptHandler()
        self.assertFalse(handler.trigger_interrupt())


class TestVoiceSpeakRegistersTask(unittest.TestCase):

    def test_speak_barge_in_cancels_stream(self):
        """A user speaking (barge-in) must cancel the in-progress speech stream."""
        voice = VoiceSystem()
        events = []

        async def fake_generate(text, voice_id, rate, pitch):
            # Register the calling task, then yield forever until cancelled.
            for i in range(100000):
                yield b"\x00\x01"
                await asyncio.sleep(0.05)

        async def scenario():
            task = asyncio.create_task(self._collect_speak(voice, events))
            await asyncio.sleep(0.2)  # let speak start streaming
            # User barge-in: cancel active speech.
            voice.handle_user_barge_in()
            await asyncio.sleep(0.2)
            return task

        with patch.object(voice.provider, "generate_speech", fake_generate):
            task = _run(scenario())

        self.assertTrue(task.cancelled(), "speak task should be cancelled on barge-in")

    async def _collect_speak(self, voice, events):
        try:
            async for _chunk in voice.speak("test", personality="ultron"):
                events.append("chunk")
        except asyncio.CancelledError:
            events.append("cancelled")
            raise


if __name__ == "__main__":
    unittest.main()
