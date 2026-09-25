"""
Ultron Cache Policy Abstraction
Defines the strict base interface and the V1 heuristic keyword-based cache policy.
Enables seamless V2+ semantic intent upgrades without router modifications.

Phase 1: live-world questions (weather, news, prices, system status, "latest",
"current", time) always bypass the cache — a Jarvis must never answer
"what's the weather" with yesterday's cached text. Matching is word-boundary
anchored at the start of the term so "task" also covers "tasks" while
unrelated substrings do not trigger.
"""

import re
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
    # Personal / stateful workspace data.
    STATEFUL_TERMS = (
        "todo", "task", "goal", "reminder", "remind", "alarm", "calendar", "schedule",
        "branch", "git", "commit", "workspace", "terminal", "compile",
        "my name", "who am i", "call me", "journal", "diary", "project",
        "yesterday", "today", "tomorrow", "tonight",
    )
    # Live-world data that changes minute to minute.
    DYNAMIC_TERMS = (
        "weather", "forecast", "temperature", "rain", "humid",
        "news", "headline", "latest", "current", "currently", "right now", "live",
        "price", "stock", "market", "bitcoin", "crypto", "score",
        "time", "date", "clock", "now playing", "playing",
        "cpu", "ram", "battery", "disk", "memory usage", "uptime", "process",
        "search", "google", "look up", "lookup", "find", "open", "play",
        "download", "screenshot", "volume", "status",
    )

    def __init__(self) -> None:
        # Kept for backwards compatibility with callers that inspect it.
        self._banned_phrases = list(self.STATEFUL_TERMS + self.DYNAMIC_TERMS)
        alternation = "|".join(
            re.escape(term).replace(r"\ ", r"\s+")
            for term in sorted(self._banned_phrases, key=len, reverse=True)
        )
        self._pattern = re.compile(rf"\b(?:{alternation})", re.IGNORECASE)

    def should_bypass_cache(self, system_prompt: str, user_prompt: str) -> bool:
        """True for personal, stateful or live-world prompts."""
        return bool(self._pattern.search(user_prompt or ""))
