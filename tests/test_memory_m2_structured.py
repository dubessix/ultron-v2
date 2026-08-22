"""M2 regressions for structured, project-scoped durable memories."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.app.memory.structured_memory import (
    ALLOWED_MEMORY_CATEGORIES,
    STRUCTURED_MEMORY_SCHEMA_VERSION,
    build_structured_turn_memory,
    corrected_memory_metadata,
    explicit_memory_metadata,
    memory_inventory,
    normalize_category,
    normalize_importance,
    redact_sensitive_text,
)
from backend.app.tools.memory_tool import MemoryTool


ROOT = Path(__file__).resolve().parent.parent


class TestStructuredTurnClassification(unittest.TestCase):
    def test_memory_gate_saves_owner_preferences_decisions_and_problems(self):
        from backend.app.memory.memory_gate import MemoryGate

        gate = MemoryGate()
        for prompt in (
            "I prefer concise answers",
            "We decided to use SQLite",
            "Next step is to add tests",
            "There is a backend connection bug",
            "The issue was resolved",
        ):
            with self.subTest(prompt=prompt):
                self.assertTrue(gate.should_save(prompt))

    def test_owner_preference_is_high_importance_and_exact(self):
        record = build_structured_turn_memory(
            "I prefer emerald colours and I don't want emoji",
            "Preference acknowledged.",
            project_id="personal",
            session_id="session-pref",
        )
        self.assertEqual(record["metadata"]["category"], "owner_preference")
        self.assertEqual(record["metadata"]["importance"], "high")
        self.assertEqual(record["metadata"]["project_id"], "personal")
        self.assertEqual(record["metadata"]["session_id"], "session-pref")
        self.assertEqual(record["metadata"]["schema_version"], STRUCTURED_MEMORY_SCHEMA_VERSION)
        self.assertIn("Owner: I prefer emerald", record["content"])
        self.assertIn("Assistant outcome: Preference acknowledged.", record["content"])

    def test_category_priority_and_critical_importance_are_deterministic(self):
        cases = (
            ("We decided to use SQLite", "decision"),
            ("Our goal is to ship a local assistant", "goal"),
            ("Next step is to add a test", "task"),
            ("There is a backend connection bug", "problem"),
            ("The root cause was fixed", "solution"),
            ("The project uses FastAPI backend", "project_fact"),
            ("Save this session event", "session_event"),
        )
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                record = build_structured_turn_memory(
                    prompt,
                    "Exact outcome",
                    project_id="alpha",
                    session_id="s",
                )
                self.assertEqual(record["metadata"]["category"], expected)
        critical = build_structured_turn_memory(
            "Critical: never forget this owner rule",
            "Recorded",
            project_id="alpha",
            session_id="s",
        )
        self.assertEqual(critical["metadata"]["importance"], "critical")

    def test_structured_text_redacts_secrets_and_is_bounded(self):
        prompt = "Important key GROQ_API_KEY_3=gsk_owner_secret_value and ghp_abcdef1234567890 " + "x" * 900
        record = build_structured_turn_memory(
            prompt,
            "NVIDIA_API_KEY_4=nvapi-owner-secret",
            project_id="alpha",
            session_id="s",
        )
        encoded = json.dumps(record)
        self.assertNotIn("gsk_owner_secret_value", encoded)
        self.assertNotIn("ghp_abcdef1234567890", encoded)
        self.assertNotIn("nvapi-owner-secret", encoded)
        self.assertIn("[REDACTED]", encoded)
        self.assertLessEqual(len(record["content"]), 1250)


class TestStructuredMetadata(unittest.TestCase):
    def test_category_and_importance_aliases_are_normalized(self):
        self.assertEqual(normalize_category("preference"), "owner_preference")
        self.assertEqual(normalize_category("architecture"), "project_fact")
        self.assertEqual(normalize_category("bug"), "problem")
        self.assertEqual(normalize_category("episodic"), "session_event")
        self.assertEqual(normalize_category("semantic"), "project_fact")
        self.assertIsNone(normalize_category("unknown-category"))
        self.assertEqual(normalize_importance("medium"), "normal")
        self.assertEqual(normalize_importance("urgent"), "critical")
        self.assertIsNone(normalize_importance("maximum"))

    def test_explicit_metadata_and_corrections_are_versioned(self):
        content = redact_sensitive_text("Owner prefers concise answers")
        metadata = explicit_memory_metadata(
            project_id="alpha",
            category="preference",
            importance="important",
            content=content,
        )
        self.assertEqual(metadata["category"], "owner_preference")
        self.assertEqual(metadata["importance"], "high")
        self.assertEqual(metadata["revision"], 1)
        existing = {"content": content, "metadata": metadata}
        revised = corrected_memory_metadata(existing, "Owner prefers very concise answers")
        self.assertEqual(revised["revision"], 2)
        self.assertTrue(revised["corrected"])
        self.assertEqual(len(revised["correction_history"]), 1)
        self.assertEqual(revised["previous_content_sha256"], metadata["content_sha256"])
        self.assertNotEqual(revised["content_sha256"], metadata["content_sha256"])

    def test_inventory_is_project_scoped_and_uses_stable_buckets(self):
        rows = [
            {"type": "episodic", "metadata": {"project_id": "alpha", "category": "decision", "importance": "high"}},
            {"type": "episodic", "metadata": {"project_id": "alpha", "category": "preference", "importance": "critical"}},
            {"type": "semantic", "metadata": {"project_id": "beta", "category": "decision", "importance": "high"}},
        ]
        result = memory_inventory(rows, "alpha")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["categories"]["decision"], 1)
        self.assertEqual(result["categories"]["owner_preference"], 1)
        self.assertEqual(result["importance"]["critical"], 1)
        self.assertEqual(result["types"], {"episodic": 2})
        self.assertEqual(set(result["categories"]), set(ALLOWED_MEMORY_CATEGORIES))


class TestAutomaticStructuredPersistence(unittest.IsolatedAsyncioTestCase):
    async def test_orchestrator_persists_structured_owner_preference(self):
        from backend.app.core.orchestrator import CognitiveOrchestrator

        orchestrator = CognitiveOrchestrator()
        try:
            await orchestrator._persist_turn_to_memory(
                "I prefer short direct answers",
                "Preference acknowledged.",
                project_id="m2-auto",
                session_id="m2-auto-session",
            )
            rows = orchestrator.memory.vector_store.list_recent_memories(
                limit=10,
                project_id="m2-auto",
            )
        finally:
            await orchestrator.close()
        self.assertEqual(len(rows), 1)
        metadata = rows[0]["metadata"]
        self.assertEqual(metadata["kind"], "structured_turn")
        self.assertEqual(metadata["category"], "owner_preference")
        self.assertEqual(metadata["importance"], "high")
        self.assertEqual(metadata["session_id"], "m2-auto-session")


class TestMemoryToolM2(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_remember_organize_and_correct_preserve_project_scope(self):
        tool = MemoryTool()
        saved = await tool.execute(
            action="remember",
            project_id="m2-alpha",
            content="I prefer compact terminal output",
            category="preference",
            importance="important",
        )
        self.assertTrue(saved["success"], saved)
        listed = await tool.execute(action="list", project_id="m2-alpha", limit=20)
        self.assertEqual(listed["data"]["count"], 1)
        memory = listed["data"]["memories"][0]
        self.assertEqual(memory["metadata"]["category"], "owner_preference")
        self.assertEqual(memory["metadata"]["revision"], 1)

        other = await tool.execute(
            action="remember",
            project_id="m2-beta",
            content="Beta decision",
            category="decision",
            importance="normal",
        )
        self.assertTrue(other["success"], other)
        organized = await tool.execute(action="organize", project_id="m2-alpha", limit=100)
        self.assertTrue(organized["success"])
        self.assertEqual(organized["data"]["total"], 1)
        self.assertEqual(organized["data"]["categories"]["owner_preference"], 1)

        corrected = await tool.execute(
            action="correct",
            project_id="m2-alpha",
            memory_id=memory["id"],
            content="I prefer minimal compact terminal output",
            category="owner_preference",
            importance="high",
        )
        self.assertTrue(corrected["success"], corrected)
        updated = tool.memory.vector_store.get_memory(memory["id"])
        self.assertEqual(updated["metadata"]["revision"], 2)
        self.assertTrue(updated["metadata"]["corrected"])
        self.assertEqual(updated["metadata"]["project_id"], "m2-alpha")

    async def test_invalid_category_or_importance_fails_clearly(self):
        tool = MemoryTool()
        bad_category = await tool.execute(
            action="remember",
            project_id="m2-invalid",
            content="Do not store under an arbitrary bucket",
            category="random-bucket",
            importance="normal",
        )
        self.assertFalse(bad_category["success"])
        self.assertIn("Unsupported memory category", bad_category["error"])
        bad_importance = await tool.execute(
            action="remember",
            project_id="m2-invalid",
            content="Bad importance",
            category="explicit",
            importance="maximum",
        )
        self.assertFalse(bad_importance["success"])
        self.assertIn("Unsupported memory importance", bad_importance["error"])


class TestM2IntegrationContracts(unittest.TestCase):
    def test_orchestrator_uses_structured_turn_builder(self):
        source = (ROOT / "backend" / "app" / "core" / "orchestrator.py").read_text(encoding="utf-8")
        self.assertIn("build_structured_turn_memory", source)
        self.assertIn('"kind": "structured_turn"', (ROOT / "backend" / "app" / "memory" / "structured_memory.py").read_text(encoding="utf-8"))
        self.assertNotIn('entry = f"{user_prompt.strip()[:500]} ->', source)

    def test_memory_tool_exposes_organize_action(self):
        source = (ROOT / "backend" / "app" / "tools" / "memory_tool.py").read_text(encoding="utf-8")
        self.assertIn('action == "organize"', source)
        self.assertIn("memory_inventory", source)


if __name__ == "__main__":
    unittest.main()
