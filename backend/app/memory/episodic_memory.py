"""
Ultron Episodic Memory Layer
Handles time-stamped past events, occurrences, and session histories.
"""

from typing import List, Dict, Any, Optional
from backend.app.memory.vector_store import VectorStore

class EpisodicMemory:
    def __init__(self, store: Optional[VectorStore] = None) -> None:
        self.store = store or VectorStore()

    async def record_event(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Save one episodic memory (kept even when the embedding service is down)."""
        return await self.store.remember("episodic", content, metadata)

    async def recall_related_events(
        self, query: str, limit: int = 3, project_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Similar episodic memories inside the active project scope."""
        return await self.store.recall("episodic", query, limit=limit, project_id=project_id)
