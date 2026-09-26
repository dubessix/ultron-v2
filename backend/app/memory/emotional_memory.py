"""
Ultron Emotional Memory Layer
Handles emotional history, stress triggers, dialogue patterns, and session sentiments over time.
"""

from typing import List, Dict, Any, Optional
from backend.app.memory.vector_store import VectorStore

class EmotionalMemory:
    def __init__(self, store: Optional[VectorStore] = None) -> None:
        self.store = store or VectorStore()

    async def log_emotional_record(self, statement: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Save one emotional memory (kept even when the embedding service is down)."""
        return await self.store.remember("emotional", statement, metadata)

    async def recall_stress_triggers(
        self, query: str, limit: int = 3, project_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Similar emotional memories inside the active project scope."""
        return await self.store.recall("emotional", query, limit=limit, project_id=project_id)
