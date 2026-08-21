"""
Ultron Central Memory Engine
Co-ordinates data transfers across Short-Term, Persistent, Project, Episodic, Semantic, and Emotional layers.
"""

import threading
from collections import OrderedDict
from typing import Optional, List, Dict
from backend.app.memory.short_term import ShortTermMemory
from backend.app.memory.persistent_memory import PersistentMemory
from backend.app.memory.project_memory import ProjectMemory
from backend.app.memory.vector_store import VectorStore
from backend.app.memory.memory_gate import MemoryGate
from backend.app.memory.episodic_memory import EpisodicMemory
from backend.app.memory.semantic_memory import SemanticMemory
from backend.app.memory.emotional_memory import EmotionalMemory

class MemoryEngine:
    # Maximum size of each per-session short-term sliding window.
    SESSION_BUFFER_LIMIT = 50
    MAX_SESSION_BUFFERS = 100

    def __init__(self) -> None:
        # Default buffer kept for backward compatibility (tests/tools that poke
        # `self.short_term` directly still work). The orchestrator uses the
        # per-session buffers below so sessions never leak into each other.
        self.short_term = ShortTermMemory(limit=self.SESSION_BUFFER_LIMIT)
        self.persistent = PersistentMemory()
        self.project = ProjectMemory()

        # Per-session short-term buffers. Fixes the cross-session leak where
        # Session B could see Session A's recent turns in RAM.
        self._session_buffers = OrderedDict()
        self._session_lock = threading.RLock()

        # Initialize Hybrid Vector Engine layers
        self.vector_store = VectorStore()
        self.gate = MemoryGate()
        self.episodic = EpisodicMemory(self.vector_store)
        self.semantic = SemanticMemory(self.vector_store)
        self.emotional = EmotionalMemory(self.vector_store)

    def _buffer_for(self, session_id: str) -> ShortTermMemory:
        """Returns (creating if needed) the short-term buffer for a session."""
        key = session_id or "default_sess"
        with self._session_lock:
            buf = self._session_buffers.get(key)
            if buf is None:
                buf = ShortTermMemory(limit=self.SESSION_BUFFER_LIMIT)
                self._session_buffers[key] = buf
            self._session_buffers.move_to_end(key)
            while len(self._session_buffers) > self.MAX_SESSION_BUFFERS:
                self._session_buffers.popitem(last=False)
            return buf

    def save_chat_turn(
        self, session_id: str, user_message: str, ai_response: str
    ) -> None:
        """Syncs the latest dialogue turn into the session's short-term cache."""
        self._buffer_for(session_id).add_turn(user_message, ai_response)

    def get_session_context(self, session_id: str) -> List[Dict[str, str]]:
        """Returns the session-scoped short-term history (empty if none yet)."""
        return self._buffer_for(session_id).get_context_history()

    def clear_session_context(self, session_id: str) -> None:
        with self._session_lock:
            self._session_buffers.pop(session_id or "default_sess", None)

    def active_session_buffer_count(self) -> int:
        with self._session_lock:
            return len(self._session_buffers)

    def set_user_profile_param(self, key: str, value: str) -> None:
        """Saves a permanent user configuration parameter into persistent SQLite."""
        self.persistent.set(key, value)

    def get_user_profile_param(self, key: str) -> Optional[str]:
        """Retrieves a permanent user configuration parameter from persistent SQLite."""
        return self.persistent.get(key)
