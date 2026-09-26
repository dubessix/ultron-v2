"""Jarvis full access: any folder, auto-found by name, any shell — with guards."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.security import path_locator
from backend.app.security.path_guard import check_path, full_access_enabled, resolve_agent_tool_arguments
from backend.app.tools.locate_tool import LocatePathTool
from backend.app.tools.system_tools import TerminalRunTool, _approved_command
from backend.app.tools.tool_registry import ToolRegistry


class FullAccessCase(unittest.TestCase):
    """Fake owner PC: HOME with Desktop/Documents/Downloads + deep folders."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        # resolve(): Windows temp dirs use 8.3 short names (RUNNER~1) while
        # the guard returns the real long path (runneradmin).
        self.home = Path(self._tmp.name).resolve() / "owner"
        for rel in (
            "Desktop/old_screens",
            "Documents/College/Projects/Ultron-App",
            "Downloads",
            "Work/Client Invoices",
        ):
            (self.home / rel).mkdir(parents=True)
        (self.home / "Downloads" / "resume_2026.pdf").write_text("pdf")
        self.env = patch.dict(os.environ, {
            "HOME": str(self.home), "USERPROFILE": str(self.home),
            "ULTRON_TEST_FULL_ACCESS": "1", "ULTRON_ACCESS_MODE": "full",
            "ULTRON_TERMINAL_POLICY": "any",
        })
        self.env.start()
        path_locator._cache.clear()
        self.root = str(Path(__file__).resolve().parent.parent)

    def tearDown(self):
        self.env.stop()
        path_locator._cache.clear()
        self._tmp.cleanup()

    def resolve(self, tool, args):
        return resolve_agent_tool_arguments(tool, args, self.root, confine_to_project=False)


class TestAnyFolder(FullAccessCase):
    def test_full_access_mode_is_on(self):
        self.assertTrue(full_access_enabled())
        self.assertTrue(check_path(str(self.home / "Work"))["safe"])

    def test_desktop_word(self):
        r = self.resolve("list_contents", {"folderpath": "Desktop"})
        self.assertEqual(r["arguments"]["folderpath"], str(self.home / "Desktop"))

    def test_auto_find_deep_folder_from_spoken_name(self):
        r = self.resolve("organize_folder", {"folderpath": "my Projects folder"})
        self.assertTrue(r["safe"])
        self.assertEqual(r["arguments"]["folderpath"], str(self.home / "Documents/College/Projects"))

    def test_auto_find_ignores_case_and_spaces(self):
        r = self.resolve("list_contents", {"folderpath": "client_invoices"})
        self.assertEqual(r["arguments"]["folderpath"], str(self.home / "Work/Client Invoices"))

    def test_new_folder_gets_auto_found_parent(self):
        r = self.resolve("create_folder", {"folderpath": "Projects/NewJarvis"})
        self.assertEqual(r["arguments"]["folderpath"], str(self.home / "Documents/College/Projects/NewJarvis"))

    def test_terminal_cwd_auto_found(self):
        r = self.resolve("terminal_run", {"cwd": "Ultron-App"})
        self.assertEqual(r["arguments"]["cwd"], str(self.home / "Documents/College/Projects/Ultron-App"))

    def test_system_and_secret_paths_still_blocked(self):
        system = (
            (r"C:\Windows", r"c:\windows\system32", r"C:\Program Files")
            if os.name == "nt" else ("/etc", "/usr/bin")
        )
        for bad in (*system, "~/.ssh", "~/.env"):
            with self.subTest(path=bad):
                self.assertFalse(self.resolve("delete_folder", {"folderpath": bad})["safe"])

    def test_coding_turns_still_project_confined(self):
        r = resolve_agent_tool_arguments(
            "file_write", {"filepath": str(self.home / "Desktop/x.py")}, self.root, confine_to_project=True)
        self.assertFalse(r["safe"])


class TestLocateTool(FullAccessCase):
    def test_locates_file_and_folder(self):
        f = asyncio.run(LocatePathTool().execute(name="resume 2026", kind="file"))
        self.assertEqual(f["data"]["best"], str(self.home / "Downloads/resume_2026.pdf"))
        d = asyncio.run(LocatePathTool().execute(name="College"))
        self.assertEqual(d["data"]["best"], str(self.home / "Documents/College"))

    def test_unknown_name_is_honest(self):
        r = asyncio.run(LocatePathTool().execute(name="NoSuchFolderXYZ"))
        self.assertFalse(r["success"])


class TestAnyShell(FullAccessCase):
    def test_any_executable_allowed(self):
        for cmd in ("ffmpeg -i a.mp4 b.mp3", "powershell Get-Process", "code ."):
            with self.subTest(cmd=cmd):
                self.assertTrue(_approved_command(cmd))

    def test_disk_wipers_still_blocked(self):
        for cmd in ("rm -rf /", "mkfs /dev/sda", "shutdown now"):
            with self.subTest(cmd=cmd):
                r = asyncio.run(TerminalRunTool().execute(command=cmd, cwd=str(self.home)))
                self.assertFalse(r["success"])

    def test_shell_needs_one_approval_then_runs_anywhere(self):
        registry = ToolRegistry()
        args = {"command": "echo jarvis", "cwd": str(self.home / "Desktop")}
        pending = asyncio.run(registry.execute_tool("terminal_run", args, session_id="fa"))
        self.assertEqual(pending["status"], "PENDING_CONFIRMATION")
        done = asyncio.run(registry.execute_tool(
            "terminal_run", args, session_id="fa", has_confirmed=True,
            confirmation_token=pending["confirmation_token"]))
        self.assertTrue(done["success"])
        self.assertIn("jarvis", done["data"]["stdout"])


class TestEndToEndOrganizeByName(FullAccessCase):
    def test_brain_says_projects_orchestrator_finds_real_folder(self):
        seen = {}

        async def spy(self_registry, tool_id, args, **kwargs):
            seen[tool_id] = args
            return {"success": True, "data": {"organized": True}, "error": None}

        calls = []

        async def brain(system_prompt, user_prompt, tools, **kwargs):
            calls.append([t["tool_id"] for t in tools])
            if any(m.get("role") == "tool" for m in kwargs.get("conversation") or []):
                return {"content": "Organized.", "tool_calls": [], "provider": "groq",
                        "model": "t", "native_tools": True, "provider_state": None}
            return {"content": "", "tool_calls": [{"id": "c1", "name": "organize_folder",
                    "arguments": {"folderpath": "Projects"}}], "provider": "groq",
                    "model": "t", "native_tools": True, "provider_state": None}

        async def run():
            orchestrator = CognitiveOrchestrator()
            orchestrator.router.get_completions_with_tools = brain
            try:
                with patch.object(ToolRegistry, "execute_tool", new=spy):
                    return await orchestrator.process_request(
                        "Organize my Projects folder", session_id="fa-e2e")
            finally:
                await orchestrator.close()

        response = asyncio.run(run())
        self.assertIn("organize_folder", calls[0])
        self.assertIn("locate_path", calls[0])
        self.assertEqual(seen["organize_folder"]["folderpath"], str(self.home / "Documents/College/Projects"))
        self.assertEqual(response["tools_used"], ["organize_folder"])


if __name__ == "__main__":
    unittest.main()
