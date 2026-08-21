"""
Ultron Unit & Integration Testing Suite — Developer Intelligence diagnostics
Verifies AST code optimization and semantic search graph execution.
"""

import unittest
import asyncio
from backend.app.tools.tool_registry import ToolRegistry
from backend.app.tools.code_optimizer_tool import CodeOptimizerTool
from backend.app.tools.semantic_graph_tool import SemanticGraphTool
from backend.app.tools.reminder_tool import ReminderTool
from backend.app.runtime_paths import isolated_test_artifact_path


def _run(coro):
    return asyncio.run(coro)


class TestDeveloperIntelligenceTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = ToolRegistry()
        cls.test_file_path = isolated_test_artifact_path("developer_intelligence", "temp_dev_test_file.py")
        
        # Create a sample python file with specific classes, functions, and standard patterns
        cls.test_content = (
            "import os\n"
            "from math import sqrt\n\n"
            "class SampleCalculator:\n"
            "    def __init__(self):\n"
            "        self.name = 'Sample'\n\n"
            "    def calculate_distance(self, x1, y1, x2, y2, z1=0, z2=0):\n"
            "        # This function accepts 6 arguments (violates SRP signature recommendation)\n"
            "        val = (x2 - x1)**2 + (y2 - y1)**2\n"
            "        return sqrt(val)\n\n"
            "def simple_add(a, b):\n"
            "    result = a + b\n"
            "    var_name = 'world'\n"
            "    message = 'Hello ' + var_name + '!'\n"
            "    print(message)\n"
            "    return result\n"
        )
        
        with open(cls.test_file_path, "w", encoding="utf-8") as f:
            f.write(cls.test_content)

        # Keep semantic indexing entirely inside the isolated test workspace.
        graph_tool = cls.registry.get_tool("semantic_code_graph")
        graph_tool.workspace_root = cls.test_file_path.parent
        graph_tool.graph_cache_path = isolated_test_artifact_path(
            "developer_intelligence", "semantic_graph.json"
        )

    @classmethod
    def tearDownClass(cls):
        if cls.test_file_path.exists():
            cls.test_file_path.unlink()
        
        bak_file = cls.test_file_path.with_suffix(".py.bak")
        if bak_file.exists():
            bak_file.unlink()

    def test_code_optimizer_ast_analysis(self):
        """Test CodeOptimizer AST analysis reports correct functions, classes, and violations."""
        tool = self.registry.get_tool("optimize_code")
        self.assertIsNotNone(tool)
        self.assertIsInstance(tool, CodeOptimizerTool)

        # Run async execute synchronously via asyncio loop
        result = _run(tool.execute(
            filepath=str(self.test_file_path),
            optimization_type="solid",
            apply_changes=False
        ))

        self.assertTrue(result["success"])
        data = result["data"]
        self.assertEqual(data["ast_metrics"]["num_classes"], 1)
        self.assertEqual(data["ast_metrics"]["num_functions"], 3)  # __init__, calculate_distance, simple_add
        
        # Verify single responsibility principle warning was detected for too many arguments (6 arguments)
        srp_violations = data["ast_metrics"]["solid_violations"]
        self.assertTrue(any("calculate_distance" in v["detail"] for v in srp_violations))

    def test_code_optimizer_heuristic_and_backup(self):
        """Test CodeOptimizer creates a backup (.bak) file when apply_changes is True."""
        tool = self.registry.get_tool("optimize_code")
        
        result = _run(tool.execute(
            filepath=str(self.test_file_path),
            optimization_type="readability",
            apply_changes=True
        ))

        self.assertTrue(result["success"])
        data = result["data"]
        # Use `data`: it should carry the optimization output key we rely on.
        self.assertIsInstance(data, dict)
        
        # Verify backup file was created
        bak_file = self.test_file_path.with_suffix(".py.bak")
        self.assertTrue(bak_file.exists())
        
        # Read backup content to make sure it matches original
        with open(bak_file, "r", encoding="utf-8") as f:
            bak_content = f.read()
        self.assertEqual(bak_content.strip(), self.test_content.strip())

    def test_semantic_code_graph_summary(self):
        """Test SemanticGraph can index the codebase and fetch summary stats."""
        tool = self.registry.get_tool("semantic_code_graph")
        self.assertIsNotNone(tool)
        self.assertIsInstance(tool, SemanticGraphTool)

        # Force a build to refresh graph with our temp file
        build_result = _run(tool.execute(query_type="build"))
        self.assertTrue(build_result["success"])

        # Fetch summary
        summary_result = _run(tool.execute(query_type="summary"))
        self.assertTrue(summary_result["success"])
        data = summary_result["data"]
        
        self.assertIn("stats", data)
        self.assertGreater(data["stats"]["files_indexed"], 0)
        self.assertGreaterEqual(data["stats"]["total_classes"], 1)
        self.assertGreaterEqual(data["stats"]["total_functions"], 3)

    def test_semantic_code_graph_search_and_callers(self):
        """Test SemanticGraph can find symbol definitions and tracking callers."""
        tool = self.registry.get_tool("semantic_code_graph")

        # Search for our SampleCalculator class symbol
        search_result = _run(tool.execute(
            query_type="search",
            target_symbol="SampleCalculator"
        ))
        self.assertTrue(search_result["success"])
        data = search_result["data"]
        self.assertEqual(data["symbol"], "SampleCalculator")
        self.assertEqual(len(data["definitions"]), 1)
        self.assertEqual(data["definitions"][0]["type"], "class")

        # Search callers for simple_add (not called anywhere, so usage should be empty)
        callers_result = _run(tool.execute(
            query_type="callers",
            target_symbol="simple_add"
        ))
        self.assertTrue(callers_result["success"])
        self.assertEqual(len(callers_result["data"]["callers"]), 0)

    def test_reminder_tool_crud(self):
        """Test ReminderTool can create, list, snooze, dismiss, and delete reminders."""
        tool = self.registry.get_tool("manage_reminder")
        self.assertIsNotNone(tool)
        self.assertIsInstance(tool, ReminderTool)

        
        # 1. Create a reminder
        create_res = _run(tool.execute(
            action="create",
            type="alarm",
            title="SaaS Review",
            target_time="10m",
            recurrence="daily"
        ))
        self.assertTrue(create_res["success"])
        rem_id = create_res["data"]["id"]
        self.assertEqual(create_res["data"]["recurrence"], "daily")
        
        # 2. List reminders
        list_res = _run(tool.execute(action="list"))
        self.assertTrue(list_res["success"])
        self.assertGreaterEqual(len(list_res["data"]["reminders"]), 1)
        
        # 3. Snooze reminder
        snooze_res = _run(tool.execute(action="snooze", reminder_id=rem_id))
        self.assertTrue(snooze_res["success"])
        self.assertEqual(snooze_res["data"]["snooze_count"], 1)
        
        # 4. Dismiss reminder (calculates next target for daily)
        dismiss_res = _run(tool.execute(action="dismiss", reminder_id=rem_id))
        self.assertTrue(dismiss_res["success"])
        self.assertEqual(dismiss_res["data"]["recurrence"], "daily")
        self.assertIsNotNone(dismiss_res["data"]["next_target_time"])
        
        # 5. Delete reminder
        delete_res = _run(tool.execute(action="delete", reminder_id=rem_id))
        self.assertTrue(delete_res["success"])

if __name__ == "__main__":
    unittest.main()
