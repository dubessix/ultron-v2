"""
Ultron Emotional Memory Layer
Handles emotional history, stress triggers, dialogue patterns, and session sentiments over time.
"""

import uuid
from typing import List, Dict, Any, Optional
from backend.app.memory.vector_store import VectorStore

class EmotionalMemory:
    def __init__(self, store: Optional[VectorStore] = None) -> None:
        self.store = store or VectorStore()

    async def log_emotional_record(self, statement: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Generates embeddings and saves emotional logs to SQLite vector tables."""
        msg_id = str(uuid.uuid4())
        try:
            embedding = await self.store.generate_embedding(statement)
            return self.store.save_vector_memory(
                msg_id=msg_id,
                mem_type="emotional",
                content=statement,
                embedding=embedding,
                metadata=metadata or {}
            )
        except Exception as e:
            print(f"[EMOTIONAL_MEMORY] Warning: Failed to log emotional record: {e}")
            return False

    async def recall_stress_triggers(
        self, query: str, limit: int = 3, project_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search emotional states inside the active project scope."""
        try:
            query_emb = await self.store.generate_embedding(query)
            metadata_filter = {"project_id": project_id} if project_id else None
            return self.store.search_similarity(
                "emotional", query_emb, limit=limit, metadata_filter=metadata_filter
            )
        except Exception as e:
            print(f"[EMOTIONAL_MEMORY] Warning: Failed to recall emotional states: {e}")
            return []
