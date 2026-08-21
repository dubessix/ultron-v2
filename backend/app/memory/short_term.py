"""
Ultron Short-Term Memory Buffer
Maintains a sliding window of the last 50 conversational turns in RAM.
Prevents context window overflow and local memory consumption spikes.
"""

from collections import deque
from typing import List, Dict

class ShortTermMemory:
    def __init__(self, limit: int = 50) -> None:
        self.limit = limit
        # Thread-safe double-ended queue with maximum capacity limits
        self._history: deque = deque(maxlen=limit)

    def add_turn(self, user_message: str, ai_response: str) -> None:
        """Appends a new conversational turn to the sliding context window."""
        self._history.append({
            "user": user_message,
            "ai": ai_response
        })

    def get_context_history(self) -> List[Dict[str, str]]:
        """Extracts history logs in clean chronological lists."""
        return list(self._history)

    def clear(self) -> None:
        """Flushes short term memory registry."""
        self._history.clear()
