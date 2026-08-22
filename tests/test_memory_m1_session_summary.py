"""M1 regressions for deterministic, project-scoped session summaries."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.app.database.db import get_db_connection
from backend.app.database.models import create_session, save_conversation, update_session_project
from backend.app.memory.session_summary import (
    SUMMARY_SCHEMA_VERSION,
    get_last_session_summary,
    load_session_summary,
    refresh_session_summary,
)


ROOT = Path(__file__).resolve().parent.parent


class TestDeterministicSessionSummary(unittest.TestCase):
    def _create_session(self, session_id: str, project_id: str = "personal") -> None:
        with get_db_connection() as conn:
            create_session(conn, session_id, personality="ultron")
            update_session_project(conn, session_id, project_id)

    def _turn(
        self,
        session_id: str,
        index: int,
        user: str,
        assistant: str,
        *,
        intent: str = "Conversation",
        tools: list[str] | None = None,
        widget: str | None = None,
    ) -> None:
        with get_db_connection() as conn:
            save_conversation(
                conn,
                msg_id=f"{session_id}-{index}",
                session_id=session_id,
                user_message=user,
                ai_response=assistant,
                personality="ultron",
                tools_used=tools or [],
                widget_shown=widget,
                intent=intent,
                response_ms=10,
            )

    def test_summary_is_exact_bounded_and_stored_in_existing_session_field(self):
        self._create_session("summary-a", "project-a")
        self._turn("summary-a", 1, "Plan the calendar feature", "Created a safe plan.", intent="PLANNING")
        self._turn(
            "summary-a",
            2,
            "Remember the owner prefers emerald",
            "Preference recorded.",
            intent="MEMORY",
            tools=["manage_memory"],
            widget="memory",
        )
        with get_db_connection() as conn:
            summary = refresh_session_summary(conn, "summary-a")
            stored = load_session_summary(conn, "summary-a")

        self.assertEqual(summary, stored)
        self.assertEqual(summary["schema_version"], SUMMARY_SCHEMA_VERSION)
        self.assertEqual(summary["source"], "deterministic_db_digest")
        self.assertEqual(summary["session_id"], "summary-a")
        self.assertEqual(summary["project_id"], "project-a")
        self.assertEqual(summary["turn_count"], 2)
        self.assertEqual(summary["latest"]["user"], "Remember the owner prefers emerald")
        self.assertEqual(summary["latest"]["assistant"], "Preference recorded.")
        self.assertEqual(summary["tools_used"], ["manage_memory"])
        self.assertEqual(summary["widgets_shown"], ["memory"])
        self.assertEqual(len(summary["recent_focus"]), 2)
        self.assertIn("2 saved conversation turns", summary["summary_text"])

    def test_summary_redacts_common_secret_assignments_and_key_prefixes(self):
        self._create_session("summary-secret")
        self._turn(
            "summary-secret",
            1,
            "Use GROQ_API_KEY_1=gsk_owner_super_secret and token ghp_abcdef1234567890",
            "I will never print NVIDIA_API_KEY_2=nvapi-owner-secret.",
        )
        with get_db_connection() as conn:
            summary = refresh_session_summary(conn, "summary-secret")
        encoded = json.dumps(summary)
        self.assertNotIn("gsk_owner_super_secret", encoded)
        self.assertNotIn("ghp_abcdef1234567890", encoded)
        self.assertNotIn("nvapi-owner-secret", encoded)
        self.assertIn("[REDACTED]", encoded)

    def test_recent_focus_is_unique_and_bounded(self):
        self._create_session("summary-bounded")
        for index in range(1, 10):
            self._turn(
                "summary-bounded",
                index,
                f"Focus item {index} " + ("x" * 500),
                f"Result {index} " + ("y" * 600),
            )
        with get_db_connection() as conn:
            summary = refresh_session_summary(conn, "summary-bounded")
        self.assertEqual(summary["turn_count"], 9)
        self.assertLessEqual(len(summary["recent_focus"]), 5)
        self.assertLessEqual(len(summary["latest"]["user"]), 320)
        self.assertLessEqual(len(summary["latest"]["assistant"]), 420)
        self.assertTrue(summary["recent_focus"][-1]["user"].startswith("Focus item 9"))

    def test_last_session_summary_is_project_scoped_and_can_exclude_current(self):
        self._create_session("project-a-old", "project-a")
        self._turn("project-a-old", 1, "Old A", "Result old A")
        self._create_session("project-b", "project-b")
        self._turn("project-b", 1, "Only B", "Result B")
        self._create_session("project-a-current", "project-a")
        self._turn("project-a-current", 1, "Current A", "Result current A")
        with get_db_connection() as conn:
            refresh_session_summary(conn, "project-a-old")
            refresh_session_summary(conn, "project-b")
            refresh_session_summary(conn, "project-a-current")
            previous = get_last_session_summary(
                conn,
                project_id="project-a",
                exclude_session_id="project-a-current",
            )
        self.assertEqual(previous["session_id"], "project-a-old")
        self.assertEqual(previous["project_id"], "project-a")
        self.assertNotIn("Only B", json.dumps(previous))

    def test_missing_or_malformed_summary_is_reported_as_unavailable(self):
        self._create_session("summary-missing")
        with get_db_connection() as conn:
            self.assertIsNone(load_session_summary(conn, "summary-missing"))
            conn.execute("UPDATE sessions SET summary = ? WHERE id = ?", ("not-json", "summary-missing"))
            conn.commit()
            self.assertIsNone(load_session_summary(conn, "summary-missing"))


class TestChatServiceSummaryIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_canonical_chat_pipeline_persists_summary(self):
        from backend.app.services.chat_service import process_chat_message

        class FakeOrchestrator:
            async def process_request(self, **_kwargs):
                return {
                    "id": "chat-summary-message",
                    "content": "The exact integration result.",
                    "active_personality": "ultron",
                    "persisted_personality": "ultron",
                    "intent": "Conversation",
                    "structured_action": {"action": "none"},
                    "coding": False,
                    "events": [],
                    "provider_route": {"provider": None, "model": None, "offline": True},
                }

        result = await process_chat_message(
            orchestrator=FakeOrchestrator(),
            content="Summarize this saved integration turn",
            session_id="chat-summary-session",
            project_id="chat-summary-project",
        )
        with get_db_connection() as conn:
            summary = load_session_summary(conn, result["session_id"])
        self.assertIsNotNone(summary)
        self.assertEqual(summary["turn_count"], 1)
        self.assertEqual(summary["project_id"], "chat-summary-project")
        self.assertEqual(summary["latest"]["user"], "Summarize this saved integration turn")
        self.assertEqual(summary["latest"]["assistant"], "The exact integration result.")


class TestSessionSummaryIntegrationContracts(unittest.TestCase):
    def test_chat_service_refreshes_summary_after_saving_the_turn(self):
        source = (ROOT / "backend" / "app" / "services" / "chat_service.py").read_text(encoding="utf-8")
        self.assertIn("refresh_session_summary", source)
        self.assertLess(source.index("save_conversation("), source.index("refresh_session_summary("))

    def test_local_last_session_api_is_present(self):
        source = (ROOT / "backend" / "app" / "router.py").read_text(encoding="utf-8")
        self.assertIn('/session-summary/last', source)
        self.assertIn('/session-summary/{session_id}', source)
        self.assertIn("exclude_session_id", source)
        self.assertIn("get_last_session_summary", source)


if __name__ == "__main__":
    unittest.main()
