"""JARVIS FINAL EXAM — 20 everyday commands, end to end through the orchestrator.

For every command we prove the whole chain the owner cares about:
  1. the right tool schema reaches the brain  (orchestrator arms the LLM)
  2. the brain's tool call is executed        (native agent loop)
  3. the tool result goes back to the brain   (role=tool message)
  4. the brain's final words are what the user gets, and tools_used is truthful

The "brain" is a scripted stand-in that behaves like a good tool-calling model:
it can only call a tool whose schema it was actually given. So if the
orchestrator strips or forgets a tool, the exam fails — exactly the original bug.
Tool execution is stubbed for side-effect tools (no music, no browser, no
deletes on CI); a real safe tool (system_metrics) and a real confirmation gate
(delete_folder) are exercised without stubs.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.app.core.orchestrator import CognitiveOrchestrator
from backend.app.tools.tool_registry import ToolRegistry

# command -> (tool the brain should pick, arguments it would send)
EXAM = [
    ("What's the weather in Kolkata today?", "weather_tool", {"city": "Kolkata"}),
    ("Will it rain in Bhatpara tomorrow?", "weather_tool", {"city": "Bhatpara"}),
    ("Play some music", "play_music", {}),
    ("Pause the music", "pause_music", {}),
    ("Increase the volume", "set_volume", {"level": 70}),
    ("Open Spotify and play Believer", "open_spotify", {}),
    ("Search the web for latest AI news", "google_search", {"query": "latest AI news"}),
    ("Read me the news", "news_search", {}),
    ("Show me my CPU and RAM usage", "system_metrics", {}),
    ("Open Chrome", "open_chrome", {}),
    ("Open VS Code", "open_vscode", {}),
    ("Find all pdf files in my documents", "find_files", {"pattern": "*.pdf"}),
    ("Thanks! Now find my invoice pdf", "find_files", {"pattern": "*invoice*.pdf"}),
    ("Organize my desktop files", "organize_folder", {"folderpath": "Desktop"}),
    ("Compress the Reports folder", "compress_folder", {"folderpath": "Reports"}),
    ("Set a reminder for 5pm to call mom", "manage_reminder", {"action": "create"}),
    ("Remember that my birthday is on 12 March", "manage_memory", {"action": "remember"}),
    ("Check my git status", "git_status", {}),
    ("Convert sales.json to csv", "convert_file_format", {"filepath": "sales.json"}),
    ("Give me my daily briefing", "daily_briefing", {}),
]


class ScriptedBrain:
    """Acts like a disciplined tool-calling LLM with a fixed intention."""

    def __init__(self, want_tool: str, args: dict):
        self.want_tool = want_tool
        self.args = args
        self.calls: list[dict] = []

    async def __call__(self, system_prompt, user_prompt, tools, **kwargs):
        conversation = kwargs.get("conversation") or []
        self.calls.append({"system": system_prompt, "tools": [t["tool_id"] for t in tools],
                           "conversation": conversation})
        tool_msgs = [m for m in conversation if m.get("role") == "tool"]
        if tool_msgs:
            last = tool_msgs[-1]
            return {"content": f"Done with {last['name']}.", "tool_calls": [],
                    "provider": "groq", "model": "exam", "native_tools": True, "provider_state": None}
        if self.want_tool not in self.calls[-1]["tools"]:
            # A real model cannot call an undeclared tool — it would just talk.
            return {"content": "I can't do that from here.", "tool_calls": [],
                    "provider": "groq", "model": "exam", "native_tools": True, "provider_state": None}
        return {"content": "", "tool_calls": [{"id": "call-1", "name": self.want_tool, "arguments": self.args}],
                "provider": "groq", "model": "exam", "native_tools": True, "provider_state": None}


def _stub_success(tool_id, args, **_kwargs):
    return {"success": True, "data": {"stub": tool_id, "args": args}, "error": None}


class TestJarvisFinalExam(unittest.IsolatedAsyncioTestCase):
    async def test_twenty_everyday_commands(self):
        report = []
        for index, (command, tool_id, args) in enumerate(EXAM):
            with self.subTest(command=command):
                orchestrator = CognitiveOrchestrator()
                brain = ScriptedBrain(tool_id, args)
                orchestrator.router.get_completions_with_tools = brain
                orchestrator.router.get_completions = AsyncMock(return_value="(no tools path)")
                try:
                    # This exam checks brain wiring; path policy has its own tests. Allow the
                    # paths so a blocked path cannot hide behind a scripted "Done" reply.
                    with patch.object(ToolRegistry, "execute_tool",
                                      new=AsyncMock(side_effect=_stub_success)), \
                         patch("backend.app.security.path_guard.check_path",
                               lambda p: {"safe": True, "reason": None, "path": p}):
                        response = await orchestrator.process_request(
                            command, session_id=f"exam-{index}")
                finally:
                    await orchestrator.close()

                self.assertTrue(brain.calls, f"brain never armed for: {command}")
                self.assertIn(tool_id, brain.calls[0]["tools"], f"tool not offered for: {command}")
                self.assertNotIn("No tool execution is needed", brain.calls[0]["system"])
                self.assertIn(tool_id, response["tools_used"])
                self.assertEqual(len(brain.calls), 2, "tool result must return to the brain")
                self.assertIn(f"Done with {tool_id}", response["content"])
                report.append((command, tool_id))
        self.assertEqual(len(report), 20)

    async def test_real_tool_result_flows_back_to_brain(self):
        orchestrator = CognitiveOrchestrator()
        brain = ScriptedBrain("system_metrics", {})
        orchestrator.router.get_completions_with_tools = brain
        try:
            response = await orchestrator.process_request(
                "Show me my CPU and RAM usage", session_id="exam-real")
        finally:
            await orchestrator.close()
        tool_msg = [m for m in brain.calls[-1]["conversation"] if m.get("role") == "tool"][0]
        self.assertEqual(tool_msg["name"], "system_metrics")
        payload = json.loads(tool_msg["content"]) if tool_msg["content"].startswith("{") else {}
        self.assertTrue(payload or tool_msg["content"], "real metrics must reach the brain")
        self.assertEqual(response["tools_used"], ["system_metrics"])

    async def test_destructive_command_stops_for_owner_confirmation(self):
        # Inside an allowlisted root: must stop at the exact-confirmation gate.
        target = Path(tempfile.mkdtemp(prefix="_jarvis_exam_", dir=Path(__file__).resolve().parent.parent / "backend"))
        try:
            (target / "keep.txt").write_text("precious")
            orchestrator = CognitiveOrchestrator()
            orchestrator.router.get_completions_with_tools = ScriptedBrain(
                "delete_folder", {"folderpath": str(target)})
            try:
                response = await orchestrator.process_request(
                    "Delete my downloads folder", session_id="exam-danger")
            finally:
                await orchestrator.close()
            self.assertIsNotNone(response["pending_confirmation"])
            self.assertEqual(response["pending_confirmation"]["tool_id"], "delete_folder")
            self.assertTrue((target / "keep.txt").exists(), "nothing may be deleted before confirmation")
        finally:
            import shutil
            shutil.rmtree(target, ignore_errors=True)

    async def test_destructive_command_outside_allowed_roots_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "Downloads"
            target.mkdir()
            (target / "keep.txt").write_text("precious")
            orchestrator = CognitiveOrchestrator()
            orchestrator.router.get_completions_with_tools = ScriptedBrain(
                "delete_folder", {"folderpath": str(target)})
            try:
                await orchestrator.process_request("Delete my downloads folder", session_id="exam-guard")
            finally:
                await orchestrator.close()
            self.assertTrue((target / "keep.txt").exists())

    async def test_small_talk_stays_light(self):
        """No word list decides 'this is small talk': the AI gets its tools and simply
        answers without calling one (one LLM call, same as before)."""
        orchestrator = CognitiveOrchestrator()
        native = AsyncMock(return_value={"content": "Hey Debjeet, all good.", "tool_calls": [],
                                         "provider": "groq", "native_tools": True, "provider_state": None})
        orchestrator.router.get_completions_with_tools = native
        try:
            result = await orchestrator.process_request("Hi there, good morning!", session_id="exam-hi")
        finally:
            await orchestrator.close()
        native.assert_awaited_once()
        self.assertEqual(result["content"], "Hey Debjeet, all good.")
        self.assertEqual(result["tools_used"], [])


if __name__ == "__main__":
    unittest.main()
