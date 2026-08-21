"""
Ultron Cache Policy Abstraction
Defines the strict base interface and the V1 heuristic keyword-based cache policy.
Enables seamless V2+ semantic intent upgrades without router modifications.
"""

from abc import ABC, abstractmethod

class BaseCachePolicy(ABC):
    @abstractmethod
    def should_bypass_cache(self, system_prompt: str, user_prompt: str) -> bool:
        """
        Evaluates the request payload to determine if caching should be bypassed.
        Returns True if the request MUST skip the cache.
        """
        pass

class HeuristicKeywordCachePolicy(BaseCachePolicy):
    def __init__(self) -> None:
        # Predefined stateful/dynamic keywords
        self._banned_phrases = [
            "todo", "task", "goal", "reminder", "calendar", "schedule",
            "branch", "git", "commit", "workspace", "terminal", "compile",
            "my name", "who am i", "call me", "journal", "diary", "project",
            "yesterday", "today", "tomorrow"
        ]

    def should_bypass_cache(self, system_prompt: str, user_prompt: str) -> bool:
        """Evaluates prompt string contents for personal, stateful keywords."""
        prompt_lower = user_prompt.lower()
        return any(phrase in prompt_lower for phrase in self._banned_phrases)
