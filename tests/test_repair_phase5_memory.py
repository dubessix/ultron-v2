"""Regression tests for newest history and project-scoped durable memory."""

from __future__ import annotations

import asyncio
import uuid
import unittest

from fastapi.testclient import TestClient

from backend.app.brain.model_config import get_embedding_dimensions, get_model
from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.database.db import get_db_connection
from backend.app.database.models import (
    create_session,
    get_conversation_history,
    get_session,
    save_conversation,
)
from backend.app.main import app
from backend.app.memory.memory_engine import MemoryEngine
from backend.app.memory.vector_store import VectorStore
from backend.app.security.pending_actions import get_pending_action_registry
from backend.app.tools.tool_registry import ToolRegistry


class TestNewestHistory(unittest.TestCase):
    def test_limit_returns_newest_rows_in_chronological_order(self):
        session = "history_" + uuid.uuid4().hex
        with get_db_connection() as conn:
            create_session(conn, session)
            for index in range(60):
                save_conversation(
                    conn,
                    f"msg_{uuid.uuid4().hex}",
                    session,
                    f"user-{index}",
                    f"ai-{index}",
                    "ultron",
                    response_ms=index,
                )
            rows = get_conversation_history(conn, session, limit=5)
        self.assertEqual([row["user_message"] for row in rows], [f"user-{i}" for i in range(55, 60)])


class TestProjectSessionPersistence(unittest.TestCase):
    def test_chat_persists_and_reuses_project_scope(self):
        client = TestClient(app)
        session = "project_" + uuid.uuid4().hex
        first = client.post(
            "/api/chat",
            json={"session_id": session, "project_id": "alpha", "content": "hello"},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["project_id"], "alpha")
        second = client.post(
            "/api/chat",
            json={"session_id": session, "content": "hello again"},
        )
        self.assertEqual(second.json()["project_id"], "alpha")
        with get_db_connection() as conn:
            self.assertEqual(get_session(conn, session)["active_project"], "alpha")


class TestProjectScopedVectors(unittest.IsolatedAsyncioTestCase):
    async def test_recall_never_crosses_project_boundary(self):
        store = VectorStore()
        content_a = "alpha unique deployment decision " + uuid.uuid4().hex
        content_b = "beta unique billing decision " + uuid.uuid4().hex
        vector_a = await store.generate_embedding(content_a)
        vector_b = await store.generate_embedding(content_b)
        store.save_vector_memory(
            "mem_" + uuid.uuid4().hex,
            "episodic",
            content_a,
            vector_a,
            {"project_id": "alpha", "category": "decision"},
        )
        store.save_vector_memory(
            "mem_" + uuid.uuid4().hex,
            "episodic",
            content_b,
            vector_b,
            {"project_id": "beta", "category": "decision"},
        )
        alpha = store.search_similarity(
            "episodic", vector_a, limit=10, metadata_filter={"project_id": "alpha"}
        )
        beta = store.search_similarity(
            "episodic", vector_a, limit=10, metadata_filter={"project_id": "beta"}
        )
        self.assertTrue(all(item["metadata"]["project_id"] == "alpha" for item in alpha))
        self.assertTrue(all(item["metadata"]["project_id"] == "beta" for item in beta))
        self.assertIn(content_a, [item["content"] for item in alpha])
        self.assertNotIn(content_b, [item["content"] for item in alpha])

    async def test_saved_memory_records_embedding_model_and_dimensions(self):
        store = VectorStore()
        content = "embedding metadata " + uuid.uuid4().hex
        vector = await store.generate_embedding(content)
        memory_id = "mem_" + uuid.uuid4().hex
        store.save_vector_memory(
            memory_id,
            "semantic",
            content,
            vector,
            {"project_id": "metadata-project"},
        )
        item = store.get_memory(memory_id)
        self.assertEqual(item["metadata"]["embedding_model"], get_model("embedding"))
        self.assertEqual(item["metadata"]["embedding_dimensions"], get_embedding_dimensions())


class TestMemoryManagement(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        get_pending_action_registry().clear()
        self.registry = ToolRegistry()
        self.session = "memory_admin"
        self.project = "memory-project-" + uuid.uuid4().hex[:8]

    async def _confirm(self, tool_id, arguments):
        pending = await self.registry.execute_tool(
            tool_id, arguments, session_id=self.session
        )
        self.assertEqual(pending["status"], "PENDING_CONFIRMATION")
        return await self.registry.execute_tool(
            tool_id,
            arguments,
            has_confirmed=True,
            confirmation_token=pending["confirmation_token"],
            session_id=self.session,
            max_retries=0,
        )

    async def test_remember_correct_export_forget_restore_cycle(self):
        original = "Original preference " + uuid.uuid4().hex
        remembered = await self.registry.execute_tool(
            "manage_memory",
            {"action": "remember", "project_id": self.project, "content": original},
            session_id=self.session,
        )
        self.assertTrue(remembered["success"])

        listed = await self.registry.execute_tool(
            "manage_memory",
            {"action": "list", "project_id": self.project, "limit": 20},
            session_id=self.session,
        )
        memory = next(item for item in listed["data"]["memories"] if item["content"] == original)
        corrected_text = "Corrected preference " + uuid.uuid4().hex
        corrected = await self._confirm(
            "manage_memory",
            {
                "action": "correct",
                "project_id": self.project,
                "memory_id": memory["id"],
                "content": corrected_text,
            },
        )
        self.assertTrue(corrected["success"])

        exported = await self.registry.execute_tool(
            "manage_memory",
            {"action": "export", "project_id": self.project, "limit": 20},
            session_id=self.session,
        )
        corrected_memory = next(
            item for item in exported["data"]["memories"] if item["id"] == memory["id"]
        )
        self.assertEqual(corrected_memory["content"], corrected_text)

        forgotten = await self._confirm(
            "manage_memory",
            {"action": "forget", "project_id": self.project, "memory_id": memory["id"]},
        )
        self.assertTrue(forgotten["success"])

        restored = await self._confirm(
            "manage_memory",
            {
                "action": "restore",
                "project_id": self.project,
                "limit": 20,
                "memories": [corrected_memory],
            },
        )
        self.assertTrue(restored["success"])
        self.assertEqual(restored["data"]["restored"], 1)


class TestPromptAndConcurrencyIsolation(unittest.IsolatedAsyncioTestCase):
    async def test_short_term_turn_is_injected_once(self):
        orchestrator = CognitiveOrchestrator()
        marker = "UNIQUE_HISTORY_" + uuid.uuid4().hex
        session = "prompt_" + uuid.uuid4().hex
        orchestrator.memory.save_chat_turn(session, marker, "old answer")
        captured = {}

        async def fake_completion(system_prompt, **_kwargs):
            captured["system"] = system_prompt
            return "new answer"

        orchestrator.router.get_completions = fake_completion
        orchestrator.memory.gate.should_save = lambda _prompt: False
        await orchestrator.process_request("explain something", session, project_id="alpha")
        self.assertEqual(captured["system"].count(marker), 1)
        await orchestrator.close()

    async def test_shared_request_state_is_serialized(self):
        orchestrator = CognitiveOrchestrator()
        active = 0
        maximum = 0

        async def fake_unlocked(**kwargs):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.05)
            active -= 1
            return {"session": kwargs["session_id"]}

        orchestrator._process_request_unlocked = fake_unlocked
        await asyncio.gather(
            orchestrator.process_request("a", "session-a"),
            orchestrator.process_request("b", "session-b"),
        )
        self.assertEqual(maximum, 1)
        await orchestrator.close()

    def test_session_buffers_are_lru_bounded(self):
        memory = MemoryEngine()
        memory.MAX_SESSION_BUFFERS = 3
        for index in range(7):
            memory.save_chat_turn(f"session-{index}", "u", "a")
        self.assertEqual(memory.active_session_buffer_count(), 3)
        self.assertEqual(memory.get_session_context("session-6")[0]["user"], "u")


if __name__ == "__main__":
    unittest.main()
