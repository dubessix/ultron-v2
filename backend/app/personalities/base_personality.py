"""
Ultron Base Personality Abstraction
Defines the strict OOP interface for all current and future system personalities.
Supports Open/Closed Principle (OCP) for adding future personalities (Mentor, Researcher, Teacher).
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

PROMPTS_DIR = Path(__file__).resolve().parent

class BasePersonality(ABC):
    def __init__(self, id_str: str, name_str: str) -> None:
        self.id = id_str
        self.name = name_str
        self._cached_prompt: Optional[str] = None

    def load_prompt_from_disk(self) -> str:
        """Loads and caches the markdown prompt file from disk."""
        if self._cached_prompt is not None:
            return self._cached_prompt
            
        file_path = PROMPTS_DIR / f"{self.id}.md"
        if not file_path.exists():
            # Fallback inline prompt if file is missing
            return f"You are {self.name}. Always reply precisely."
            
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                self._cached_prompt = f.read().strip()
                return self._cached_prompt
        except OSError:
            return f"You are {self.name}. Always reply precisely."

    @abstractmethod
    def get_system_prompt(self, formatted_history: str) -> str:
        """Assembles and returns the full contextual system prompt."""
        pass

class UltronPersonality(BasePersonality):
    def __init__(self) -> None:
        super().__init__("ultron", "Ultron")

    def get_system_prompt(self, formatted_history: str) -> str:
        base_prompt = self.load_prompt_from_disk()
        return (
            f"{base_prompt}\n\n"
            f"Active Conversational History:\n{formatted_history}"
        )

class ZoraPersonality(BasePersonality):
    def __init__(self) -> None:
        super().__init__("zora", "Zora")

    def get_system_prompt(self, formatted_history: str) -> str:
        base_prompt = self.load_prompt_from_disk()
        return (
            f"{base_prompt}\n\n"
            f"Conversational History:\n{formatted_history}"
        )
