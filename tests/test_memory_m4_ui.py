"""M4 regressions for the project-scoped memory dashboard."""

from __future__ import annotations

import json
import unittest
import uuid
from pathlib import Path

from backend.app.database.db import get_db_connection
from backend.app.database.models import create_session, save_conversation, update_session_project
from backend.app.memory.memory_ui import build_memory_ui_payload, safe_export_memories
from backend.app.memory.session_summary import refresh_session_summary
from backend.app.memory.vector_store import VectorStore


ROOT = Path(__file__).resolve().parent.parent


class TestMemoryUiPayload(unittest.TestCase):
    def _seed_memory(
        self,
        store: VectorStore,
        *,
        memory_id: str,
        project_id: str,
        content: str,
        category: str,
        importance: str,
        vector: list[float],
        revision: int = 1,
        corrected: bool = False,
    ) -> None:
        saved = store.save_vector_memory(
            memory_id,
            "episodic",
            content,
            vector,
            {
                "project_id": project_id,
                "session_id": f"session-{project_id}",
                "category": category,
                "importance": importance,
                "kind": "explicit_remember",
                "source": "user",
                "revision": revision,
                "corrected": corrected,
                "created_at": "2026-08-20T10:00:00+00:00",
                "updated_at": "2026-08-22T11:30:00+00:00",
            },
        )
        self.assertTrue(saved)

    def test_dashboard_lists_summaries_and_important_memories_with_safe_provenance(self):
        suffix = uuid.uuid4().hex
        project = f"m4-dashboard-{suffix}"
        other_project = f"m4-other-{suffix}"
        store = VectorStore()
        self._seed_memory(
            store,
            memory_id=f"decision-{suffix}",
            project_id=project,
            content="We decided the memory database will use SQLite",
            category="decision",
            importance="critical",
            vector=[1.0, 0.0, 0.0],
            revision=2,
            corrected=True,
        )
        self._seed_memory(
            store,
            memory_id=f"task-{suffix}",
            project_id=project,
            content="Next step is the owner laptop acceptance",
            category="task",
            importance="normal",
            vector=[0.0, 1.0, 0.0],
        )
        self._seed_memory(
            store,
            memory_id=f"other-{suffix}",
            project_id=other_project,
            content="Other project must not leak",
            category="decision",
            importance="critical",
            vector=[0.0, 0.0, 1.0],
        )

        session_id = f"m4-summary-{suffix}"
        with get_db_connection() as conn:
            create_session(conn, session_id, personality="ultron")
            update_session_project(conn, session_id, project)
            save_conversation(
                conn,
                msg_id=f"m4-turn-{suffix}",
                session_id=session_id,
                user_message="Review the SQLite memory decision",
                ai_response="The exact decision remains active.",
                personality="ultron",
                intent="decision",
                response_ms=8,
            )
            refresh_session_summary(conn, session_id)

        payload = build_memory_ui_payload(project_id=project, limit=50)
        encoded = json.dumps(payload)
        self.assertEqual(payload["project_id"], project)
        self.assertEqual(payload["counts"]["memories"], 2)
        self.assertEqual(payload["counts"]["important"], 1)
        self.assertEqual(payload["counts"]["sessions"], 1)
        self.assertNotIn("Other project must not leak", encoded)

        decision = next(item for item in payload["memories"] if item["category"] == "decision")
        self.assertEqual(decision["importance"], "critical")
        self.assertEqual(decision["revision"], 2)
        self.assertTrue(decision["corrected"])
        self.assertEqual(decision["provenance"]["source_type"], "memory")
        self.assertEqual(decision["provenance"]["source_id"], decision["id"])
        self.assertEqual(payload["summaries"][0]["provenance"]["source_type"], "session_summary")
        self.assertEqual(payload["summaries"][0]["turn_count"], 1)

    def test_exact_local_search_filters_and_legacy_secret_redaction(self):
        suffix = uuid.uuid4().hex
        project = f"m4-search-{suffix}"
        store = VectorStore()
        self._seed_memory(
            store,
            memory_id=f"search-hit-{suffix}",
            project_id=project,
            content="Owner prefers emerald controls; GROQ_API_KEY_1=gsk_owner_secret_value",
            category="owner_preference",
            importance="high",
            vector=[1.0, 0.0, 0.0, 0.0],
        )
        self._seed_memory(
            store,
            memory_id=f"search-miss-{suffix}",
            project_id=project,
            content="A normal calendar event",
            category="session_event",
            importance="normal",
            vector=[0.0, 1.0, 0.0, 0.0],
        )

        payload = build_memory_ui_payload(
            project_id=project,
            query="emerald controls",
            category="owner_preference",
            importance="high",
            limit=50,
        )
        encoded = json.dumps(payload)
        self.assertEqual(len(payload["memories"]), 1)
        self.assertIn("emerald controls", payload["memories"][0]["content"])
        self.assertIn("[REDACTED]", encoded)
        self.assertNotIn("gsk_owner_secret_value", encoded)
        self.assertEqual(payload["filters"]["mode"], "local_exact_fts")

    def test_export_uses_only_redacted_public_fields(self):
        rows = [
            {
                "id": "legacy-secret",
                "type": "episodic",
                "content": "TOKEN=github_pat_owner_private_value",
                "created_at": "2026-08-22T10:00:00+00:00",
                "metadata": {
                    "project_id": "personal",
                    "category": "decision",
                    "importance": "high",
                    "revision": 1,
                    "embedding_model": "must-not-be-exported",
                },
            }
        ]
        exported = safe_export_memories(rows, "personal")
        encoded = json.dumps(exported)
        self.assertIn("[REDACTED]", encoded)
        self.assertNotIn("github_pat_owner_private_value", encoded)
        self.assertNotIn("embedding_model", encoded)
        self.assertEqual(exported["format"], "ultron-memory-export-v1")


class TestMemoryUiFrontendContract(unittest.TestCase):
    def test_memory_widget_has_planned_m4_controls_and_exact_confirmation(self):
        source = (ROOT / "frontend" / "src" / "components" / "widgets" / "MemoryWidget.jsx").read_text(encoding="utf-8")
        for contract in (
            "/api/memory/ui",
            "Session summaries",
            "Important memories",
            "category",
            "importance",
            "Search exact memory",
            "Export",
            "Correct",
            "Forget",
            "confirmation_token",
            "executeTool('manage_memory'",
            "data-testid=\"memory-ui\"",
        ):
            self.assertIn(contract, source)
        self.assertNotIn("window.confirm", source)

    def test_memory_widget_remains_a_large_floating_overlay_not_a_left_panel(self):
        manager = (ROOT / "frontend" / "src" / "components" / "widgets" / "WidgetManager.js").read_text(encoding="utf-8")
        left = (ROOT / "frontend" / "src" / "components" / "LeftPanel.jsx").read_text(encoding="utf-8")
        self.assertIn('title: "Memory Console"', manager)
        self.assertRegex(manager, r"memory:\s*\{[\s\S]*?defaultWidth:\s*7[0-9]{2}")
        self.assertNotIn("MemoryWidget", left)

    def test_router_exposes_project_scoped_memory_ui_endpoint(self):
        router = (ROOT / "backend" / "app" / "router.py").read_text(encoding="utf-8")
        self.assertIn('@api_router.get("/memory/ui"', router)
        self.assertIn("build_memory_ui_payload", router)


if __name__ == "__main__":
    unittest.main()
