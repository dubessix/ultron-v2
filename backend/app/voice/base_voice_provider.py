"""
Ultron Base Voice Provider Abstraction
Defines the strict base interface for all current and future speech synthesis engines.
Enables Open/Closed Principle (OCP) for adding Azure, ElevenLabs, OpenAI, or local engines.
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator

class BaseVoiceProvider(ABC):
    @abstractmethod
    async def generate_speech(
        self,
        text: str,
        voice_id: str,
        rate: str = "+0%",
        pitch: str = "+0Hz"
    ) -> AsyncGenerator[bytes, None]:
        """
        Asynchronously synthesizes text into streaming binary audio packets.
        Yields raw audio bytes (typically MP3 or WAV).
        """
        pass
