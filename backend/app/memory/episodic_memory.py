"""
Ultron Episodic Memory Layer
Handles time-stamped past events, occurrences, and session histories.
"""

import uuid
from typing import List, Dict, Any, Optional
from backend.app.memory.vector_store import VectorStore

class EpisodicMemory:
    def __init__(self, store: Optional[VectorStore] = None) -> None:
        self.store = store or VectorStore()

    async def record_event(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Generates embeddings and saves a timestamped episodic event memory."""
        msg_id = str(uuid.uuid4())
        try:
            embedding = await self.store.generate_embedding(content)
            return self.store.save_vector_memory(
                msg_id=msg_id,
                mem_type="episodic",
                content=content,
                embedding=embedding,
                metadata=metadata or {}
            )
        except Exception as e:
            print(f"[EPISODIC_MEMORY] Warning: Failed to record event: {e}")
            return False

    async def recall_related_events(
        self, query: str, limit: int = 3, project_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search past events inside the active project scope."""
        try:
            query_emb = await self.store.generate_embedding(query)
            metadata_filter = {"project_id": project_id} if project_id else None
            return self.store.search_similarity(
                "episodic", query_emb, limit=limit, metadata_filter=metadata_filter
            )
        except Exception as e:
            print(f"[EPISODIC_MEMORY] Warning: Failed to recall events: {e}")
            return []
