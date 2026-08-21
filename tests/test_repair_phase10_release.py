"""Final release regressions for dependency floors, quality config, and docs."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tomllib
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from click.testing import CliRunner

from backend.app.runtime_paths import isolated_test_artifact_path
from backend.app.tools.calendar_tool import CalendarTool
from backend.app.tools.code_optimizer_tool import CodeOptimizerTool
from backend.app.tools.reminder_tool import ReminderTool
from backend.app.tools.system_tools import VSCodeLauncherTool
from backend.app.tools.task_tool import TaskTool


ROOT = Path(__file__).resolve().parent.parent


class TestReleaseDependencies(unittest.TestCase):
    def test_python_requirements_use_audited_versions(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        expected = {
            "fastapi": "0.141.1",
            "python-dotenv": "1.2.2",
            "click": "8.4.2",
            "PyYAML": "6.0.3",
            "pydantic": "2.13.4",
            "httpx": "0.28.1",
            "python-multipart": "0.0.32",
        }
        for package, version in expected.items():
            self.assertRegex(requirements, rf"(?m)^{re.escape(package)}=={re.escape(version)}$")
        for vulnerable in ("fastapi==0.111.1", "python-dotenv==1.0.1", "click==8.1.7"):
            self.assertNotIn(vulnerable, requirements)

    def test_frontend_uses_fixed_vite_and_reproducible_direct_versions(self):
        package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["devDependencies"]["vite"], "7.3.6")
        self.assertEqual(package["devDependencies"]["@vitejs/plugin-react"], "5.1.4")
        self.assertEqual(package["dependencies"]["react"], "19.2.8")
        self.assertEqual(package["dependencies"]["react-dom"], "19.2.8")


class TestReleaseQualityConfiguration(unittest.TestCase):
    def test_ruff_and_application_coverage_gates_are_configured(self):
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("F", config["tool"]["ruff"]["lint"]["select"])
        self.assertIn("B", config["tool"]["ruff"]["lint"]["select"])
        self.assertEqual(config["tool"]["coverage"]["report"]["fail_under"], 70)
        self.assertEqual(config["tool"]["coverage"]["run"]["source"], ["backend", "launcher"])

    @unittest.skipIf(os.name == "nt", "POSIX executable bit is not meaningful on Windows")
    def test_linux_launcher_script_is_executable(self):
        self.assertTrue(os.access(ROOT / "start_ultron.sh", os.X_OK))


class TestConsoleLauncherOwnership(unittest.TestCase):
    def test_vscode_launcher_receives_verified_requested_path(self):
        directory = isolated_test_artifact_path("final_audit", "vscode_project")
        directory.mkdir(parents=True, exist_ok=True)
        launched = {"success": True, "data": {"message": "dispatched"}, "error": None}
        with patch(
            "backend.app.tools.system_tools._launch_verified",
            new=AsyncMock(return_value=launched),
        ) as start:
            result = asyncio.run(VSCodeLauncherTool().execute(path=str(directory)))
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["requested_path"], str(directory.resolve()))
        self.assertEqual(start.await_args.args[1], [str(directory.resolve())])

    def test_ultron_start_runs_launcher_in_current_process(self):
        from backend.app import cli

        launcher_main = Mock(return_value=0)
        with patch.object(
            cli.runpy,
            "run_path",
            return_value={"main": launcher_main},
        ) as run_path:
            result = CliRunner().invoke(cli.main, ["start"])
        self.assertEqual(result.exit_code, 0, result.output)
        run_path.assert_called_once()
        launcher_main.assert_called_once_with()


class TestOptimizerFailureSafety(unittest.TestCase):
    def test_read_only_analysis_does_not_request_destructive_confirmation(self):
        path = isolated_test_artifact_path("final_audit", "read_only_optimizer.py")
        path.write_text("def okay():\n    return 1\n", encoding="utf-8")
        from backend.app.tools.tool_registry import ToolRegistry

        result = asyncio.run(
            ToolRegistry().execute_tool(
                "optimize_code",
                {"filepath": str(path), "optimization_type": "solid", "apply_changes": False},
                session_id="optimizer-read-only",
            )
        )
        self.assertTrue(result["success"], result)
        self.assertNotEqual(result.get("status"), "PENDING_CONFIRMATION")

    def test_applying_changes_still_requires_exact_confirmation(self):
        path = isolated_test_artifact_path("final_audit", "write_optimizer.py")
        path.write_text("def greet(name):\n    message = 'Hi ' + name + '!'\n    return message\n", encoding="utf-8")
        from backend.app.tools.tool_registry import ToolRegistry

        result = asyncio.run(
            ToolRegistry().execute_tool(
                "optimize_code",
                {"filepath": str(path), "optimization_type": "readability", "apply_changes": True},
                session_id="optimizer-write",
            )
        )
        self.assertEqual(result.get("status"), "PENDING_CONFIRMATION")

    def test_syntax_error_is_not_reported_as_success(self):
        path = isolated_test_artifact_path("final_audit", "invalid_source.py")
        path.write_text("def broken(:\n    pass\n", encoding="utf-8")
        result = asyncio.run(
            CodeOptimizerTool().execute(
                filepath=str(path),
                optimization_type="readability",
                apply_changes=False,
            )
        )
        self.assertFalse(result["success"])
        self.assertTrue(result["data"]["original_preserved"])

    def test_applied_heuristic_is_syntax_verified_and_backed_up(self):
        path = isolated_test_artifact_path("final_audit", "candidate.py")
        original = "def greet(name):\n    message = 'Hello ' + name + '!'\n    return message\n"
        path.write_text(original, encoding="utf-8")
        result = asyncio.run(
            CodeOptimizerTool().execute(
                filepath=str(path),
                optimization_type="readability",
                apply_changes=True,
            )
        )
        self.assertTrue(result["success"], result)
        self.assertTrue(result["data"]["write_verification"]["verified"])
        self.assertIn("message = f'Hello {name}!'", path.read_text(encoding="utf-8"))
        backup = path.with_suffix(".py.bak")
        self.assertEqual(backup.read_text(encoding="utf-8"), original)

    def test_ambiguous_exact_type_check_is_analysis_only(self):
        path = isolated_test_artifact_path("final_audit", "type_check.py")
        original = "def check(value):\n    return type(value) == int\n"
        path.write_text(original, encoding="utf-8")
        result = asyncio.run(
            CodeOptimizerTool().execute(
                filepath=str(path),
                optimization_type="readability",
                apply_changes=True,
            )
        )
        self.assertTrue(result["success"])
        self.assertFalse(result["data"]["has_changes_detected"])
        self.assertTrue(any("review manually" in item for item in result["data"]["ast_findings"]))
        self.assertEqual(path.read_text(encoding="utf-8"), original)


class TestStrictProductivityValidation(unittest.TestCase):
    def test_task_does_not_silently_replace_invalid_values(self):
        result = asyncio.run(
            TaskTool().execute(
                action="create",
                title="invalid",
                priority="urgent",
                status="mystery",
            )
        )
        self.assertFalse(result["success"])
        self.assertIn("Unsupported", result["error"])

    def test_reminder_rejects_unknown_recurrence(self):
        result = asyncio.run(
            ReminderTool().execute(
                action="create",
                title="invalid",
                target_time="10m",
                recurrence="sometimes",
            )
        )
        self.assertFalse(result["success"])
        self.assertIn("Unsupported recurrence", result["error"])

    def test_calendar_handles_aware_times_and_rejects_bad_duration(self):
        tool = CalendarTool()
        events = [{
            "start_time": "2026-08-16T10:00:00+00:00",
            "end_time": "2026-08-16T11:00:00+00:00",
        }]
        slots = tool._find_free_slots(events, 1.0)
        self.assertIsInstance(slots, list)
        invalid = asyncio.run(tool.execute(action="smart_schedule", duration_hours=-1))
        self.assertFalse(invalid["success"])


class TestReleaseDocumentation(unittest.TestCase):
    def test_documentation_has_no_retired_models_endpoints_or_absolute_claims(self):
        documents = list(ROOT.glob("*.md")) + list((ROOT / "docs").glob("*.md"))
        combined = "\n".join(path.read_text(encoding="utf-8") for path in documents)
        forbidden = (
            "gemini-1.5-flash",
            "text-embedding-004",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "/ws/voice",
            "100% coverage",
            "fully un-mocked",
            "all green",
            "no technical debt",
        )
        for literal in forbidden:
            self.assertNotIn(literal.lower(), combined.lower(), literal)

    def test_readme_states_release_and_hardware_boundaries(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        config = (ROOT / "config.yaml").read_text(encoding="utf-8")
        self.assertIn("Personal V1 release candidate", readme)
        self.assertIn("owner's Windows/browser/microphone/Spotify hardware", readme)
        self.assertIn("gemini-embedding-001", readme)
        self.assertIn("POST /api/speak", readme)
        self.assertIn('status: "personal-v1-release-candidate"', config)
        self.assertNotIn('status: "pre-development"', config)


if __name__ == "__main__":
    unittest.main()
