"""
Phase 1 regression tests — chat/state/memory correctness.

Covered fixes:
  - /ws/chat now persists conversations to SQLite, resolves/creates sessions,
    and includes structured_action + resolved session_id in the `done` packet.
  - /ws/chat no longer closes the SHARED orchestrator on disconnect (so a later
    chat still works).
  - Short-term RAM memory is per-session (no cross-session leak).

These tests never touch real data: conftest.py forces a temporary DB/cache.
"""

import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.database.db import get_db_connection
from backend.app.database.models import get_conversation_history, get_session
from backend.app.memory.memory_engine import MemoryEngine


def _collect_ws_chat(client: TestClient, session_id: str, content: str):
    """Send one WS chat message and return the final `done` frame."""
    with client.websocket_connect("/ws/chat?client_id=ph1_%s" % uuid.uuid4().hex[:6]) as ws:
        ws.send_json({"session_id": session_id, "content": content})
        frames = []
        while True:
            msg = ws.receive_json()
            frames.append(msg)
            if msg["type"] == "done":
                return frames, msg


class TestWsPersistsToDatabase(unittest.TestCase):

    @patch("backend.app.brain.llm_router.LLMRouter.get_completions",
           return_value="Deterministic assistant reply")
    def test_ws_chat_creates_session_and_saves_conversation(self, _mock):
        client = TestClient(app)
        sess = "ph1_ws_db_" + uuid.uuid4().hex[:8]

        frames, done = _collect_ws_chat(client, sess, "record this turn")

        # The final `done` frame must include the resolved session + action fields.
        self.assertEqual(done["type"], "done")
        self.assertEqual(done["session_id"], sess)
        self.assertIn("structured_action", done)
        self.assertIn("provider_route", done)
        self.assertIn("message_id", done)

        # Session must exist in the DB with a persisted personality.
        with get_db_connection() as conn:
            s = get_session(conn, sess)
            self.assertIsNotNone(s)
            self.assertEqual(s["personality"], "ultron")

            hist = get_conversation_history(conn, sess)
            self.assertEqual(len(hist), 1)
            self.assertEqual(hist[0]["user_message"], "record this turn")


class TestWsDoesNotCloseSharedOrchestrator(unittest.TestCase):

    @patch("backend.app.brain.llm_router.LLMRouter.get_completions",
           return_value="still alive")
    def test_chat_after_ws_disconnect_still_works(self, _mock):
        client = TestClient(app)
        sess = "ph1_ws_close_" + uuid.uuid4().hex[:8]

        # First WS message (then the connection closes normally).
        with client.websocket_connect("/ws/chat?client_id=ph1_x1") as ws:
            ws.send_json({"session_id": sess, "content": "first"})
            while ws.receive_json()["type"] != "done":
                pass
        # Connection is now closed.

        # A second WS chat on the SAME process must still succeed — proving the
        # shared orchestrator's HTTPX client was not closed by the first disconnect.
        frames2, done2 = _collect_ws_chat(client, sess, "second")
        self.assertEqual(done2["type"], "done")


class TestShortTermMemoryIsolation(unittest.TestCase):

    def test_sessions_do_not_leak_short_term_context(self):
        mem = MemoryEngine()
        mem.save_chat_turn("sess_A", "hello from A", "hi A")
        mem.save_chat_turn("sess_B", "hello from B", "hi B")

        ctx_a = mem.get_session_context("sess_A")
        ctx_b = mem.get_session_context("sess_B")

        self.assertEqual(len(ctx_a), 1)
        self.assertEqual(len(ctx_b), 1)
        self.assertEqual(ctx_a[0]["user"], "hello from A")
        self.assertEqual(ctx_b[0]["user"], "hello from B")
        self.assertNotEqual(ctx_a[0]["user"], ctx_b[0]["user"])


if __name__ == "__main__":
    unittest.main()
