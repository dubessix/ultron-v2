"""M3 regressions for exact/FTS recall, provenance, ordering, and bounds."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.app.database.db import get_db_connection
from backend.app.database.models import create_session, save_conversation, update_session_project
from backend.app.memory.recall_context import MAX_RECALL_CONTEXT_CHARS, build_recall_context
from backend.app.memory.recall_index import rebuild_recall_index, search_recall_index
from backend.app.memory.session_summary import refresh_session_summary
from backend.app.memory.vector_store import VectorStore


ROOT = Path(__file__).resolve().parent.parent


class RecallFixture(unittest.TestCase):
    def create_session(self, session_id: str, project_id: str) -> None:
        with get_db_connection() as conn:
            create_session(conn, session_id, personality="ultron")
            update_session_project(conn, session_id, project_id)

    def turn(self, session_id: str, message_id: str, user: str, assistant: str) -> None:
        with get_db_connection() as conn:
            save_conversation(
                conn,
                msg_id=message_id,
                session_id=session_id,
                user_message=user,
                ai_response=assistant,
                personality="ultron",
                intent="Conversation",
                response_ms=4,
            )


class TestRecallIndex(RecallFixture):
    def test_memory_gate_recognizes_preference_decision_task_and_problem_questions(self):
        from backend.app.memory.memory_gate import MemoryGate

        gate = MemoryGate()
        for query in (
            "What do I prefer?",
            "What did we decide last session?",
            "What is the next step?",
            "What bug is unresolved?",
        ):
            with self.subTest(query=query):
                self.assertTrue(gate.should_recall(query))

    def test_rebuild_indexes_existing_history_and_porter_matches_decide_decided(self):
        self.create_session("m3-old-alpha", "m3-alpha")
        self.turn(
            "m3-old-alpha",
            "m3-old-alpha-message",
            "We decided to use SQLite for durable memory",
            "Decision recorded.",
        )
        with get_db_connection() as conn:
            refresh_session_summary(conn, "m3-old-alpha")
            counts = rebuild_recall_index(conn)
            results = search_recall_index(
                conn,
                "What did we decide about durable storage?",
                project_id="m3-alpha",
                limit=10,
            )
        self.assertGreaterEqual(counts["conversation"], 1)
        self.assertTrue(any(item["source_id"] == "m3-old-alpha-message" for item in results))
        self.assertTrue(any("SQLite" in item["content"] for item in results))

    def test_exact_recall_is_project_scoped_and_redacted(self):
        self.create_session("m3-secret-alpha", "m3-secret-alpha-project")
        self.turn(
            "m3-secret-alpha",
            "m3-secret-alpha-message",
            "Database token GITHUB_TOKEN_1=ghp_owner_secret_value",
            "Use SQLite database",
        )
        self.create_session("m3-secret-beta", "m3-secret-beta-project")
        self.turn(
            "m3-secret-beta",
            "m3-secret-beta-message",
            "Beta uses Postgres database",
            "Beta only",
        )
        with get_db_connection() as conn:
            rebuild_recall_index(conn)
            alpha = search_recall_index(
                conn,
                "database token SQLite",
                project_id="m3-secret-alpha-project",
            )
        encoded = json.dumps(alpha)
        self.assertIn("SQLite", encoded)
        self.assertNotIn("Postgres", encoded)
        self.assertNotIn("ghp_owner_secret_value", encoded)
        self.assertIn("[REDACTED]", encoded)


class TestCorrectForgetRecall(unittest.IsolatedAsyncioTestCase):
    async def test_corrected_memory_replaces_old_index_and_forget_removes_it(self):
        store = VectorStore()
        old_content = "Owner prefers verbose terminal output"
        embedding = await store.generate_embedding(old_content)
        saved = store.save_vector_memory(
            "m3-correct-memory",
            "episodic",
            old_content,
            embedding,
            {
                "project_id": "m3-correct-project",
                "category": "owner_preference",
                "importance": "high",
                "revision": 1,
            },
        )
        self.assertTrue(saved)
        with get_db_connection() as conn:
            old_results = search_recall_index(
                conn,
                "verbose",
                project_id="m3-correct-project",
            )
        self.assertTrue(any(item["source_id"] == "m3-correct-memory" for item in old_results))

        updated = await store.update_vector_memory(
            "m3-correct-memory",
            "Owner prefers concise terminal output",
            {
                "project_id": "m3-correct-project",
                "category": "owner_preference",
                "importance": "high",
                "revision": 2,
                "corrected": True,
            },
        )
        self.assertTrue(updated)
        with get_db_connection() as conn:
            old_after = search_recall_index(
                conn,
                "verbose",
                project_id="m3-correct-project",
            )
            new_after = search_recall_index(
                conn,
                "concise",
                project_id="m3-correct-project",
            )
        self.assertFalse(any(item["source_id"] == "m3-correct-memory" for item in old_after))
        corrected = next(item for item in new_after if item["source_id"] == "m3-correct-memory")
        self.assertEqual(corrected["revision"], 2)
        self.assertTrue(corrected["corrected"])

        self.assertTrue(store.delete_vector_memory("m3-correct-memory"))
        with get_db_connection() as conn:
            forgotten = search_recall_index(
                conn,
                "concise",
                project_id="m3-correct-project",
            )
        self.assertFalse(any(item["source_id"] == "m3-correct-memory" for item in forgotten))


class TestRecallContext(unittest.TestCase):
    def test_corrected_memory_wins_and_context_is_bounded_with_content_free_provenance(self):
        exact = [
            {
                "document_key": "memory:new",
                "source_type": "memory",
                "source_id": "new",
                "project_id": "alpha",
                "session_id": None,
                "category": "owner_preference",
                "importance": "high",
                "revision": 2,
                "corrected": True,
                "updated_at": "2026-08-22T02:00:00+00:00",
                "content": "Owner prefers concise answers",
            },
            {
                "document_key": "memory:old",
                "source_type": "memory",
                "source_id": "old",
                "project_id": "alpha",
                "session_id": None,
                "category": "owner_preference",
                "importance": "high",
                "revision": 1,
                "corrected": False,
                "updated_at": "2026-08-20T02:00:00+00:00",
                "content": "Owner prefers verbose answers",
            },
            {
                "document_key": "memory:decision",
                "source_type": "memory",
                "source_id": "decision",
                "project_id": "alpha",
                "session_id": None,
                "category": "decision",
                "importance": "critical",
                "revision": 1,
                "corrected": False,
                "updated_at": "2026-08-21T02:00:00+00:00",
                "content": "Use SQLite",
            },
        ]
        result = build_recall_context(
            project_id="alpha",
            exact_documents=exact,
            previous_summary={
                "session_id": "previous",
                "project_id": "alpha",
                "summary_text": "Previous session ended after the SQLite decision.",
                "schema_version": 1,
                "updated_at": "2026-08-22T01:00:00+00:00",
            },
            max_chars=900,
        )
        self.assertIn("Owner prefers concise answers", result["context"])
        self.assertNotIn("Owner prefers verbose answers", result["context"])
        self.assertIn("Use SQLite", result["context"])
        self.assertLessEqual(result["characters"], 900)
        self.assertLessEqual(result["characters"], MAX_RECALL_CONTEXT_CHARS)
        self.assertTrue(result["provenance"][0]["corrected"] or result["provenance"][0]["importance"] == "critical")
        self.assertNotIn("content", result["provenance"][0])

    def test_explicit_summary_source_replaces_duplicate_fts_summary_document(self):
        previous = {
            "session_id": "previous-dup",
            "project_id": "alpha",
            "summary_text": "Previous summary exact text.",
            "schema_version": 1,
            "updated_at": "2026-08-22T01:00:00+00:00",
        }
        result = build_recall_context(
            project_id="alpha",
            exact_documents=[
                {
                    "document_key": "summary:previous-dup",
                    "source_type": "session_summary",
                    "source_id": "previous-dup",
                    "project_id": "alpha",
                    "session_id": "previous-dup",
                    "category": "session_summary",
                    "importance": "high",
                    "revision": 1,
                    "corrected": False,
                    "content": "Previous summary exact text. Focus: duplicate",
                }
            ],
            previous_summary=previous,
        )
        sources = [item["source_type"] for item in result["provenance"]]
        self.assertIn("previous_session_summary", sources)
        self.assertNotIn("session_summary", sources)

    def test_empty_sources_do_not_create_fake_context(self):
        result = build_recall_context(project_id="empty", exact_documents=[])
        self.assertEqual(result, {"context": "", "provenance": [], "characters": 0})


class TestOrchestratorRecallIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_previous_summary_and_exact_decision_enter_relevant_prompt_context(self):
        from backend.app.core.orchestrator import CognitiveOrchestrator

        with get_db_connection() as conn:
            create_session(conn, "m3-integration-old", personality="ultron")
            update_session_project(conn, "m3-integration-old", "m3-integration")
            save_conversation(
                conn,
                msg_id="m3-integration-message",
                session_id="m3-integration-old",
                user_message="We decided the memory database will use SQLite",
                ai_response="SQLite decision recorded",
                personality="ultron",
                intent="PLANNING",
                response_ms=5,
            )
            refresh_session_summary(conn, "m3-integration-old")
            rebuild_recall_index(conn)

        orchestrator = CognitiveOrchestrator()
        try:
            result = await orchestrator._recall_long_term_memory(
                "What did we decide about the memory database last session?",
                project_id="m3-integration",
                session_id="m3-integration-current",
            )
        finally:
            await orchestrator.close()
        self.assertIn("SQLite", result["context"])
        self.assertTrue(result["provenance"])
        self.assertLessEqual(result["characters"], MAX_RECALL_CONTEXT_CHARS)
        self.assertTrue(
            any(item["source_type"] in {"conversation", "session_summary", "previous_session_summary"}
                for item in result["provenance"])
        )


class TestM3TransportContracts(unittest.TestCase):
    def test_rest_and_websocket_surface_content_free_memory_provenance(self):
        router = (ROOT / "backend" / "app" / "router.py").read_text(encoding="utf-8")
        websocket = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
        service = (ROOT / "backend" / "app" / "services" / "chat_service.py").read_text(encoding="utf-8")
        self.assertIn("memory_provenance", router)
        self.assertIn("memory_provenance", websocket)
        self.assertIn("memory_provenance", service)

    def test_recall_index_hooks_cover_conversation_summary_update_delete_and_prune(self):
        chat = (ROOT / "backend" / "app" / "services" / "chat_service.py").read_text(encoding="utf-8")
        summary = (ROOT / "backend" / "app" / "memory" / "session_summary.py").read_text(encoding="utf-8")
        vectors = (ROOT / "backend" / "app" / "memory" / "vector_store.py").read_text(encoding="utf-8")
        self.assertIn("index_conversation_turn", chat)
        self.assertIn("index_session_summary", summary)
        self.assertIn("index_vector_memory", vectors)
        self.assertIn("delete_recall_document", vectors)
        self.assertIn("mark_recall_index_dirty", vectors)


if __name__ == "__main__":
    unittest.main()
