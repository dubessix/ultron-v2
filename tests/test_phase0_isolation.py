"""Phase 0 regression tests for test/data isolation and bounded scanners."""

from __future__ import annotations

import unittest
from pathlib import Path

from backend.app.runtime_paths import (
    PRODUCTION_DATA_ROOT,
    TEST_MODE,
    TEST_ROOT,
    assert_safe_test_path,
    isolated_test_artifact_path,
)
from backend.app.database import db
from backend.app.brain import smart_cache
from backend.app.tools.semantic_graph_tool import SemanticGraphTool


class TestRuntimeIsolation(unittest.TestCase):
    def test_test_mode_and_storage_paths_are_isolated(self):
        self.assertTrue(TEST_MODE)
        self.assertIsNotNone(TEST_ROOT)
        self.assertTrue(Path(db.DB_PATH).resolve().is_relative_to(TEST_ROOT))
        self.assertTrue(Path(smart_cache.CACHE_PATH).resolve().is_relative_to(TEST_ROOT))
        self.assertFalse(Path(db.DB_PATH).resolve().is_relative_to(PRODUCTION_DATA_ROOT))

    def test_guard_refuses_production_data(self):
        with self.assertRaises(RuntimeError):
            assert_safe_test_path(PRODUCTION_DATA_ROOT / "memory" / "ultron.db")

    def test_unittest_schema_is_initialized_without_pytest_fixture(self):
        with db.get_db_connection() as conn:
            names = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
            }
        self.assertIn("sessions", names)
        self.assertIn("conversations", names)
        self.assertIn("reminders_alarms", names)
        self.assertIn("project_tasks", names)
        self.assertIn("calendar_events", names)


class TestSemanticGraphBounds(unittest.TestCase):
    def _tool_for(self, workspace: Path) -> SemanticGraphTool:
        tool = SemanticGraphTool()
        tool.workspace_root = workspace
        tool.graph_cache_path = isolated_test_artifact_path("phase0", "semantic_graph.json")
        tool.max_scan_seconds = 5.0
        tool.max_cache_bytes = 1024 * 1024
        return tool

    def test_semantic_cache_is_inside_test_root_and_venv_is_skipped(self):
        workspace = isolated_test_artifact_path("phase0_workspace")
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "visible.py").write_text("def visible():\n    return 1\n", encoding="utf-8")
        hidden = workspace / ".venv" / "lib"
        hidden.mkdir(parents=True, exist_ok=True)
        (hidden / "hidden.py").write_text("def hidden():\n    return 2\n", encoding="utf-8")

        tool = self._tool_for(workspace)
        graph = tool._scan_workspace()

        self.assertEqual(set(graph["files"]), {"visible.py"})
        self.assertTrue(tool.graph_cache_path.resolve().is_relative_to(TEST_ROOT))
        self.assertTrue(tool.graph_cache_path.exists())
        self.assertLess(tool.graph_cache_path.stat().st_size, tool.max_cache_bytes)

    def test_file_limit_truncates_scan(self):
        workspace = isolated_test_artifact_path("phase0_limit_workspace")
        workspace.mkdir(parents=True, exist_ok=True)
        for index in range(5):
            (workspace / f"f{index}.py").write_text(f"VALUE = {index}\n", encoding="utf-8")

        tool = self._tool_for(workspace)
        tool.max_index_files = 2
        graph = tool._scan_workspace()

        self.assertEqual(len(graph["files"]), 2)
        self.assertTrue(graph["meta"]["truncated"])
        self.assertEqual(graph["meta"]["reason"], "file_limit")


if __name__ == "__main__":
    unittest.main()
