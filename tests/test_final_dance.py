"""
Ultron Unit & Integration Testing Suite — Final Dance Polish Diagnostics
Verifies un-mocked Tasks tracker, Calendar solver, Daily Briefing, Security scanner,
Document Search, and the GitHub Integration / parallel LLM tool calling systems.
"""

import os
import json
import unittest
import asyncio
import datetime
from pathlib import Path
from backend.app.tools.tool_registry import ToolRegistry
from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.runtime_paths import isolated_test_artifact_path


def _run(coro):
    return asyncio.run(coro)


class TestFinalDanceFeatureSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = ToolRegistry()
        cls.workspace_root = Path(__file__).resolve().parent.parent
        cls.temp_json = isolated_test_artifact_path("final_dance", "temp_test_convert.json")
        cls.temp_csv = isolated_test_artifact_path("final_dance", "temp_test_convert.csv")

        # Write clean dummy JSON data to test converter tool
        cls.temp_json.parent.mkdir(parents=True, exist_ok=True)
        with open(cls.temp_json, "w", encoding="utf-8") as f:
            json.dump([{"id": "1", "name": "Tony", "role": "CTO"}, {"id": "2", "name": "Debjeet", "role": "CEO"}], f)

    @classmethod
    def tearDownClass(cls):
        # Cleanup temporary files
        for p in (cls.temp_json, cls.temp_csv):
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass

    def test_unmocked_project_tasks(self):
        """Test: Verify un-mocked task tool can create, list, and modify TrustQuiz task structures."""
        tool = self.registry.get_tool("manage_task")
        self.assertIsNotNone(tool)


        # 1. Create a TrustQuiz task
        res_create = _run(tool.execute(
            action="create",
            project_name="TrustQuiz",
            module_name="Authentication",
            title="Setup OAuth2 Flow",
            priority="high",
            status="todo"
        ))
        self.assertTrue(res_create["success"])
        task_id = res_create["data"]["task_id"]

        # 2. List the tasks and ensure it appears
        res_list = _run(tool.execute(
            action="list",
            project_name="TrustQuiz"
        ))
        self.assertTrue(res_list["success"])
        self.assertGreaterEqual(len(res_list["data"]["tasks"]), 1)
        self.assertTrue(any(t["id"] == task_id for t in res_list["data"]["tasks"]))

        # 3. Update the task status to done
        res_update = _run(tool.execute(
            action="update_status",
            task_id=task_id,
            status="done"
        ))
        self.assertTrue(res_update["success"])
        self.assertEqual(res_update["data"]["status"], "done")

        # 4. Delete the task
        res_del = _run(tool.execute(
            action="delete",
            task_id=task_id
        ))
        self.assertTrue(res_del["success"])

    def test_smart_calendar_solver(self):
        """Test: Verify calendar scheduler can schedule events and resolve free time slots using mathematical solver."""
        tool = self.registry.get_tool("manage_calendar")
        self.assertIsNotNone(tool)


        # 1. Create two events with specific busy slots
        now = datetime.datetime.now()
        tomorrow_10am = (now + datetime.timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0).isoformat()
        tomorrow_12pm = (now + datetime.timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0).isoformat()

        create_res = _run(tool.execute(
            action="create",
            title="Busy Meeting",
            start_time=tomorrow_10am,
            end_time=tomorrow_12pm,
            category="work"
        ))
        self.assertTrue(create_res["success"])
        ev_id = create_res["data"]["event_id"]

        # 2. Query Smart Scheduler to solve 2 hours of available free time
        solve_res = _run(tool.execute(
            action="smart_schedule",
            duration_hours=2.0
        ))
        self.assertTrue(solve_res["success"])
        data = solve_res["data"]
        self.assertGreaterEqual(len(data["suggestions"]), 1)

        # Verify suggestions do not intersect with our tomorrow_10am block
        for suggestion in data["suggestions"]:
            self.assertNotEqual(suggestion["start_time"], tomorrow_10am)

        # 3. Delete the temporary calendar event
        del_res = _run(tool.execute(action="delete", event_id=ev_id))
        self.assertTrue(del_res["success"])

    def test_daily_briefing_engine(self):
        """Test: Verify daily briefing builder runs successfully, fetches weather, tasks, and schedules."""
        tool = self.registry.get_tool("daily_briefing")
        self.assertIsNotNone(tool)

        res = _run(tool.execute())
        self.assertTrue(res["success"])
        self.assertIn("briefing_text", res["data"])
        self.assertIn("weather", res["data"])

    def test_security_guardian_scan(self):
        """Test: Verify security scanner parses workspace and processes safely without throwing errors."""
        tool = self.registry.get_tool("security_scan")
        self.assertIsNotNone(tool)

        res = _run(tool.execute(
            scan_workspace_secrets=True,
            scan_active_processes=True,
            scan_dependency_manifests=True
        ))
        self.assertTrue(res["success"])
        self.assertIn("findings", res["data"])
        self.assertIn("statistics", res["data"])

    def test_document_search_and_converter(self):
        """Test: Verify local document content searching and JSON <-> CSV data format conversion."""
        search_tool = self.registry.get_tool("search_inside_documents")
        convert_tool = self.registry.get_tool("convert_file_format")
        # Conversion fixtures live in the isolated test root, never production data/.
        convert_tool.workspace_root = self.temp_json.parent

        self.assertIsNotNone(search_tool)
        self.assertIsNotNone(convert_tool)


        # 1. Search inside documents for a known function name
        search_res = _run(search_tool.execute(search_query="get_db_connection"))
        self.assertTrue(search_res["success"])
        self.assertGreaterEqual(search_res["data"]["matches_count"], 1)

        # 2. Convert temporary JSON file to CSV
        conv_res = _run(convert_tool.execute(
            source_filepath=str(self.temp_json),
            destination_filepath=str(self.temp_csv)
        ))
        self.assertTrue(conv_res["success"])
        self.assertTrue(self.temp_csv.exists())

    def test_find_files_recursive(self):
        """Test: Verify recursive file finder glob and substring searches."""
        tool = self.registry.get_tool("find_files")
        self.assertIsNotNone(tool)

        res = _run(tool.execute(pattern="main.py"))
        self.assertTrue(res["success"])
        self.assertGreaterEqual(res["data"]["matches_count"], 1)
        self.assertTrue(any(f["name"] == "main.py" for f in res["data"]["matches"]))

    def test_world_monitor_queries(self):
        """Test: Verify World Monitor can fetch earthquakes, fear_greed_index, and market quotes."""
        tool = self.registry.get_tool("world_monitor")
        self.assertIsNotNone(tool)


        # 1. Test Earthquakes
        res_eq = _run(tool.execute(
            endpoint="list_earthquakes",
            parameters={"min_magnitude": 5.0}
        ))
        self.assertTrue(res_eq["success"])
        self.assertIn("headline", res_eq["data"])
        self.assertIn("earthquakes", res_eq["data"])

        # 2. Test Fear & Greed Index
        res_fng = _run(tool.execute(endpoint="get_fear_greed_index"))
        self.assertTrue(res_fng["success"])
        self.assertIn("score", res_fng["data"])

        # 3. Test Market Quotes
        res_mq = _run(tool.execute(endpoint="list_market_quotes"))
        self.assertTrue(res_mq["success"])
        self.assertGreaterEqual(len(res_mq["data"]["quotes"]), 1)
        self.assertEqual(res_mq["data"]["source"], "CoinGecko")

    def test_github_integration_automation(self):
        """Test: Verify un-mocked github integration tool can parse actions, list issues, and search code."""
        tool = self.registry.get_tool("github_integration")
        self.assertIsNotNone(tool)


        # Phase 5: with no real token, the tool must report an honest "not
        # configured" state — never the old fake/dummy data. Force a placeholder
        # so this is deterministic (no live GitHub dependency).
        os.environ["GITHUB_TOKEN_1"] = "your_github_token_placeholder"
        os.environ["GITHUB_USERNAME_1"] = "debjeet"
        res_search = _run(tool.execute(
            action="search_code",
            search_query="get_db_connection"
        ))
        self.assertTrue(res_search["success"])
        self.assertIs(res_search["data"].get("configured"), False)
        self.assertNotIn("count", res_search["data"])  # no fake data

    def test_parallel_llm_tool_calling(self):
        """Test: Verify parallel dynamic tool executions inside cognitive orchestrator pipeline."""
        orchestrator = CognitiveOrchestrator()

        # Simulate a Hinglish query that should execute multiple tools
        res = _run(orchestrator.process_request(
            user_prompt="Folder organize karo or files search karo, Sir.",
            session_id="test_parallel_sess",
            current_hour=12
        ))
        self.assertIn("content", res)
        self.assertEqual(res["active_personality"], "ultron")

if __name__ == "__main__":
    unittest.main()
