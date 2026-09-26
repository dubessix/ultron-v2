"""
Ultron Semantic Memory Layer
Handles developer concepts, rules, coding tricks, and long-term tech notes.
"""

from typing import List, Dict, Any, Optional
from backend.app.memory.vector_store import VectorStore

class SemanticMemory:
    def __init__(self, store: Optional[VectorStore] = None) -> None:
        self.store = store or VectorStore()

    async def learn_concept(self, concept_text: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Save one semantic memory (kept even when the embedding service is down)."""
        return await self.store.remember("semantic", concept_text, metadata)

    async def recall_related_concepts(
        self, query: str, limit: int = 3, project_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Similar semantic memories inside the active project scope."""
        return await self.store.recall("semantic", query, limit=limit, project_id=project_id)
