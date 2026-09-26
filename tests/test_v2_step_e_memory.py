"""V2 Step E: Jarvis memory - keeps what matters forever, huge history, light RAM.

Each test uses its own temporary SQLite file so the big "one year of use"
data never touches the shared test database.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import sqlite3
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

# Load every module that does `from db import get_db_connection` BEFORE the
# TempDb patch; a first import during the patch would keep the temp function.
from backend.app.core import orchestrator as _orchestrator
from backend.app.memory import core_profile
from backend.app.tools import memory_tool as _memory_tool
from backend.app.memory import vector_store as vs
from backend.app.memory.recall_index import (
    ensure_recall_index,
    index_conversation_turn,
    rebuild_recall_index,
    search_recall_index,
)


_PRELOADED = (_orchestrator, _memory_tool)

class NoGeminiKeys:
    """Key manager with no Gemini key: embeddings are labelled offline vectors."""

    def has_real_key(self, provider):
        return False


class GeminiKeyButServiceDown(NoGeminiKeys):
    def has_real_key(self, provider):
        return provider == "gemini"


def run(coro):
    return asyncio.run(coro)


class TempDb(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.db = self.dir / "memory.db"

        @contextlib.contextmanager
        def connect():
            conn = sqlite3.connect(str(self.db), timeout=15.0)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

        self.connect = connect
        for target in ("backend.app.memory.vector_store.get_db_connection",
                       "backend.app.database.db.get_db_connection"):
            patcher = patch(target, connect)
            patcher.start()
            self.addCleanup(patcher.stop)
        core_profile.forget_cache()
        self.addCleanup(core_profile.forget_cache)
        self.store = vs.VectorStore(key_manager=NoGeminiKeys())
        with connect() as conn:
            conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, active_project TEXT, summary TEXT, started_at TEXT)")
            conn.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, session_id TEXT, timestamp TEXT, "
                         "user_message TEXT, ai_response TEXT, intent TEXT)")
            ensure_recall_index(conn)
            conn.commit()

    def remember(self, text, category="explicit", importance="normal", kind="explicit_remember",
                 project="personal"):
        meta = {"kind": kind, "source": "user" if kind == "explicit_remember" else "automatic_exact_turn",
                "category": category, "importance": importance, "project_id": project}
        return run(self.store.remember("episodic", text, meta, return_status=True))


class TestKeepsWhatHeToldForever(TempDb):
    def test_told_facts_survive_pruning_but_old_automatic_turns_are_capped(self):
        self.assertEqual(self.remember("My sister's name is Riya"), "saved")
        self.assertEqual(self.remember("I prefer tea over coffee", category="owner_preference",
                                       kind="note"), "saved")
        for i in range(30):
            self.remember(f"automatic chat number {i} about topic {i * 7}", category="session_event",
                          kind="structured_turn")
        removed = self.store.prune(max_per_type=10)
        self.assertEqual(removed, 20)
        left = [r["content"] for r in self.store.list_recent_memories(limit=100)]
        self.assertIn("My sister's name is Riya", left)
        self.assertIn("I prefer tea over coffee", left)
        self.assertIn("automatic chat number 29 about topic 203", left)   # newest kept
        self.assertNotIn("automatic chat number 0 about topic 0", left)  # oldest capped
        # pruned rows also left the word index
        with self.connect() as conn:
            hits = search_recall_index(conn, "automatic chat number topic", project_id="personal", limit=50)
        self.assertEqual(len([h for h in hits if h["source_type"] == "memory"]), 10)

    def test_default_cap_is_years_not_two_thousand(self):
        self.assertEqual(vs._memory_setting("max_auto_memories", 20000, 500, 500000), 20000)
        with patch.object(self.store, "prune", wraps=self.store.prune) as prune:
            self.store._writes_since_prune = self.store.prune_interval - 1
            self.remember("one more automatic turn", category="session_event", kind="structured_turn")
            prune.assert_called_once_with()  # uses the config cap (20,000), not 2,000

    def test_repeat_fact_is_already_known_not_an_error(self):
        self.assertEqual(self.remember("My birthday is 5 May"), "saved")
        self.assertEqual(self.remember("My birthday is 5 May"), "duplicate")

    def test_embedding_service_down_still_saves_and_word_search_finds_it(self):
        store = vs.VectorStore(key_manager=GeminiKeyButServiceDown())

        async def down(_text):
            raise RuntimeError("quota exhausted")

        with patch.object(store, "generate_embedding", down):
            status = run(store.remember("episodic", "Wifi password hint is the dog's name",
                                        {"kind": "explicit_remember", "source": "user",
                                         "category": "explicit", "importance": "normal"},
                                        return_status=True))
        self.assertEqual(status, "saved")
        row = store.list_recent_memories(limit=1)[0]
        self.assertEqual(row["metadata"]["embedding_model"], vs.OFFLINE_EMBEDDING)
        self.assertTrue(row["metadata"]["needs_reembed"])
        with self.connect() as conn:
            hits = search_recall_index(conn, "dog name hint", project_id="personal")
        self.assertTrue(hits)

    def test_offline_vectors_are_never_compared_with_real_ones(self):
        self.remember("offline saved fact")
        real = [0.0] * 768
        real[0] = 1.0
        self.assertEqual(self.store.search_similarity("episodic", real, embedding_model="gemini-embedding-001"), [])
        same_kind = self.store.search_similarity("episodic", real, embedding_model=vs.OFFLINE_EMBEDDING)
        self.assertEqual([m["content"] for m in same_kind], ["offline saved fact"])


class TestAlwaysKnowsHim(TempDb):
    def test_profile_holds_told_facts_and_preferences_only(self):
        self.remember("My sister's name is Riya")
        self.remember("I prefer short answers", category="owner_preference", kind="note")
        self.remember("we decided to use sqlite for the app", category="decision", kind="structured_turn")
        self.remember("random chat about weather", category="session_event", kind="structured_turn")
        block = core_profile.build_core_profile("personal")
        self.assertIn("WHAT YOU KNOW ABOUT THE OWNER", block)
        self.assertIn("Riya", block)
        self.assertIn("short answers", block)
        self.assertNotIn("weather", block)
        self.assertNotIn("sqlite", block)      # kept forever, but found by search, not always sent

    def test_profile_is_small_even_with_hundreds_of_facts(self):
        for i in range(120):
            self.remember(f"Fact number {i}: my friend {i} lives in city {i} and likes colour {i}")
        block = core_profile.build_core_profile("personal")
        self.assertLessEqual(len(block), core_profile.MAX_CHARS + 250)
        self.assertIn("Fact number 119", block)  # newest first

    def test_empty_until_he_saves_something_and_refreshes_after_a_write(self):
        self.assertEqual(core_profile.build_core_profile("personal"), "")
        self.remember("I live in Bhatpara")
        self.assertIn("Bhatpara", core_profile.build_core_profile("personal"))

    def test_profile_never_breaks_a_turn(self):
        with patch.object(vs, "VectorStore", side_effect=RuntimeError("db locked")):
            core_profile.forget_cache()
            self.assertEqual(core_profile.build_core_profile("personal"), "")


class TestSearchAndForget(TempDb):
    def test_search_gives_memory_id_so_forget_works(self):
        from backend.app.tools.memory_tool import MemoryTool

        self.remember("My old address is 12 Station Road")
        tool = MemoryTool.__new__(MemoryTool)
        tool.memory = type("M", (), {})()
        tool.memory.vector_store = self.store
        tool.memory.episodic = type("E", (), {"recall_related_events": lambda *a, **k: _empty()})()
        found = run(tool.execute(action="search", content="old address station road"))
        self.assertTrue(found["success"])
        hit = found["data"]["results"][0]
        self.assertEqual(hit["kind"], "saved fact")
        gone = run(tool.execute(action="forget", memory_id=hit["memory_id"]))
        self.assertTrue(gone["success"])
        self.assertEqual(self.store.list_recent_memories(limit=5), [])

    def test_bengali_and_hindi_words_are_searchable(self):
        self.remember("আমার বোনের নাম রিয়া")
        self.remember("मेरी बहन का नाम रिया है")
        with self.connect() as conn:
            bn = search_recall_index(conn, "বোনের নাম কী", project_id="personal")
            hi = search_recall_index(conn, "बहन का नाम", project_id="personal")
        self.assertTrue(bn)
        self.assertTrue(hi)


async def _empty():
    return []


class TestOneYearOfUseStaysLight(TempDb):
    """~1 year: 40,000 chats + 25,000 memories. Search stays fast, RAM bounded."""

    def test_huge_history_search_and_rebuild(self):
        np = vs._lazy_numpy()
        rng = np.random.default_rng(7)
        with self.connect() as conn:
            conn.execute("INSERT INTO sessions VALUES ('s1', 'personal', NULL, '2025-09-01')")
            conn.executemany(
                "INSERT INTO conversations VALUES (?, 's1', ?, ?, ?, 'Conversation')",
                [(f"c{i}", f"2025-{1 + i % 12:02d}-01", f"open project number {i} please",
                  f"Opened project {i}.") for i in range(40000)],
            )
            conn.execute("INSERT INTO conversations VALUES ('first', 's1', '2025-01-01', "
                         "'my bike lock code hint is grandma', 'Noted.', 'Conversation')")
            rows = []
            for i in range(25000):
                meta = {"kind": "structured_turn", "category": "session_event", "importance": "normal",
                        "project_id": "personal", "embedding_model": vs.OFFLINE_EMBEDDING}
                rows.append((str(uuid.uuid4()), "episodic", f"auto memory {i}",
                             sqlite3.Binary(rng.standard_normal(768).astype(np.float32).tobytes()),
                             json.dumps(meta)))
            conn.executemany("INSERT INTO vector_memories (id, type, content, embedding, metadata) "
                             "VALUES (?, ?, ?, ?, ?)", rows)
            conn.commit()
            started = time.perf_counter()
            counts = rebuild_recall_index(conn)
            rebuild_seconds = time.perf_counter() - started
        self.assertEqual(counts["conversation"], 40001)   # every chat, not only 5,000
        self.assertEqual(counts["memory"], 25000)
        self.assertLess(rebuild_seconds, 60)

        with self.connect() as conn:
            started = time.perf_counter()
            hits = search_recall_index(conn, "bike lock code", project_id="personal")
            fts_ms = (time.perf_counter() - started) * 1000
        self.assertTrue(any("grandma" in h["content"] for h in hits))  # oldest chat still found
        self.assertLess(fts_ms, 1500)

        query = rng.standard_normal(768).astype(np.float32).tolist()
        started = time.perf_counter()
        found = self.store.search_similarity("episodic", query, limit=5, embedding_model=vs.OFFLINE_EMBEDDING)
        vector_seconds = time.perf_counter() - started
        self.assertEqual(len(found), 5)
        self.assertLess(vector_seconds, 10)

        # the scan is bounded: never more than vector_scan_limit + kept rows at once
        with patch.object(vs, "_memory_setting", side_effect=lambda name, d, lo, hi: 300 if name == "vector_scan_limit" else d):
            seen_rows = []
            real_vstack = np.vstack

            def counting_vstack(items):
                seen_rows.append(len(items))
                return real_vstack(items)

            with patch.object(np, "vstack", counting_vstack):
                self.store.search_similarity("episodic", query, limit=3, embedding_model=vs.OFFLINE_EMBEDDING)
        self.assertEqual(seen_rows, [300])

    def test_new_chats_are_indexed_forever(self):
        with self.connect() as conn:
            rebuild_recall_index(conn)  # first-run sync happened already
            for i in range(50):
                index_conversation_turn(conn, message_id=f"m{i}", session_id="s", project_id="personal",
                                        user_message=f"note {i} zebra{i}", ai_response="ok",
                                        intent="Conversation", timestamp="2026-01-01")
            conn.commit()
            self.assertTrue(search_recall_index(conn, "zebra0", project_id="personal"))


if __name__ == "__main__":
    unittest.main()
