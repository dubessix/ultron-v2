"""V2 Step 7 - Tony mode: safe actions just run, risky ones ask once, voice
approval, trust rules only the owner can create, undo, action log."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.core import action_journal, trash, trust_rules
from backend.app.runtime_paths import isolated_test_artifact_path
from backend.app.security.pending_actions import get_pending_action_registry
from backend.app.tools.folder_tools import (
    CreateFolderTool, DeleteFolderTool, MoveFolderTool, OrganizeFolderTool, RenameFolderTool,
)
from backend.app.tools.jarvis_actions_tool import JarvisActionsArgs, JarvisActionsTool
from backend.app.tools.system_tools import TerminalRunTool
from backend.app.tools.tool_registry import ToolRegistry


def run(coro):
    return asyncio.run(coro)


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.root = isolated_test_artifact_path("step7", self.id().rsplit(".", 1)[-1], "x").parent
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self._trash = tempfile.TemporaryDirectory()
        env = patch.dict(os.environ, {"ULTRON_TRASH_DIR": self._trash.name})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self._trash.cleanup)
        self.addCleanup(shutil.rmtree, self.root, True)
        action_journal.clear()
        trust_rules.clear()
        get_pending_action_registry().clear()
        self.addCleanup(action_journal.clear)
        self.addCleanup(trust_rules.clear)

    def folder(self, *parts, files=()):
        path = self.root.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        for name in files:
            (path / name).write_text(name, encoding="utf-8")
        return path


class TestSafeActionsJustRun(unittest.TestCase):
    def test_everyday_actions_need_no_ok(self):
        registry = ToolRegistry()
        for tool_id in ("spotify_play", "spotify_pause", "play_music", "set_volume", "open_chrome",
                        "open_vscode", "open_calculator", "create_folder", "copy_folder", "compress_folder",
                        "manage_reminder", "apps", "screenshot", "security_scan"):
            with self.subTest(tool=tool_id):
                self.assertLess(registry.get_tool(tool_id).permission_level, 2)

    def test_risky_actions_still_ask(self):
        registry = ToolRegistry()
        for tool_id in ("delete_folder", "move_folder", "rename_folder", "organize_folder",
                        "terminal_run", "download_file", "database_restore", "file_write"):
            with self.subTest(tool=tool_id):
                self.assertGreaterEqual(registry.get_tool(tool_id).permission_level, 2)

    def test_look_only_shell_commands_run_free(self):
        tool = TerminalRunTool()
        for command in ("ls -la", "df -h", "git status", "python3 --version", "ping -c 2 google.com", "free -m"):
            self.assertEqual(tool.permission_for_arguments({"command": command}), 1, command)
        for command in ("rm -rf build", "git push", "ls; rm x", "cat .env", "printenv", "sudo ls",
                        "echo hi > file", "npm install", "ping google.com", "python3 script.py"):
            self.assertEqual(tool.permission_for_arguments({"command": command}), 2, command)


class TestDeleteGoesToTrashAndUndo(Sandbox):
    def test_delete_then_undo_restores_everything(self):
        target = self.folder("Old Project", files=("notes.txt",))
        result = run(DeleteFolderTool().execute(folderpath=str(target)))
        self.assertTrue(result["success"], result)
        self.assertFalse(target.exists())
        self.assertTrue(any(Path(self._trash.name, "files").iterdir()))  # in the Trash, not destroyed
        undo = run(JarvisActionsTool().execute(action="undo"))
        self.assertTrue(undo["success"], undo)
        self.assertEqual((target / "notes.txt").read_text(encoding="utf-8"), "notes.txt")
        self.assertFalse(run(JarvisActionsTool().execute(action="undo"))["success"])  # nothing left

    @unittest.skipIf(os.name == "nt", "freedesktop Trash is Linux only")
    def test_ubuntu_trash_is_the_real_files_app_trash(self):
        target = self.folder("ToTrash", files=("a.txt",))
        with tempfile.TemporaryDirectory() as data_home, patch.dict(os.environ, {"XDG_DATA_HOME": data_home}):
            os.environ.pop("ULTRON_TRASH_DIR", None)
            record = trash.send_to_trash(target)
            info = Path(record["info"]).read_text(encoding="utf-8")
            self.assertIn("[Trash Info]", info)
            self.assertIn("ToTrash", info)
            self.assertTrue(record["trashed"].startswith(str(Path(data_home, "Trash", "files"))))
            trash.restore(record)
        self.assertTrue((target / "a.txt").exists())

    def test_undo_move_rename_organize_create(self):
        src = self.folder("Photos", files=("a.jpg",))
        dest = self.folder("Backup")
        run(MoveFolderTool().execute(source_path=str(src), destination_path=str(dest)))
        self.assertTrue((dest / "Photos" / "a.jpg").exists())
        run(JarvisActionsTool().execute(action="undo"))
        self.assertTrue((src / "a.jpg").exists())

        run(RenameFolderTool().execute(old_path=str(src), new_path=str(self.root / "Pics")))
        run(JarvisActionsTool().execute(action="undo"))
        self.assertTrue(src.exists())

        messy = self.folder("Downloads", files=("cv.pdf", "song.mp3", "photo.png"))
        run(OrganizeFolderTool().execute(folderpath=str(messy)))
        self.assertTrue((messy / "documents" / "cv.pdf").exists())
        run(JarvisActionsTool().execute(action="undo"))
        self.assertEqual(sorted(p.name for p in messy.iterdir()), ["cv.pdf", "photo.png", "song.mp3"])

        new = self.root / "Brand New"
        run(CreateFolderTool().execute(folderpath=str(new)))
        run(JarvisActionsTool().execute(action="undo"))
        self.assertFalse(new.exists())

    def test_undo_list_shows_history(self):
        self.folder("A")
        run(RenameFolderTool().execute(old_path=str(self.root / "A"), new_path=str(self.root / "B")))
        listed = run(JarvisActionsTool().execute(action="undo_list"))
        self.assertIn("renamed A to B", listed["data"]["actions"][0]["what"])


class TestTrustRules(Sandbox):
    def test_offer_after_three_approvals_and_scope(self):
        downloads = self.folder("Downloads")
        args = {"folderpath": str(downloads)}
        self.assertIsNone(trust_rules.note_approval("organize_folder", args))
        self.assertIsNone(trust_rules.note_approval("organize_folder", args))
        offer = trust_rules.note_approval("organize_folder", args)
        self.assertIsNotNone(offer)
        self.assertIn("Always allow", offer["question"])
        trust_rules.allow(offer)
        self.assertTrue(trust_rules.allows("organize_folder", {"folderpath": str(downloads / "sub")}))
        self.assertIsNone(trust_rules.allows("organize_folder", {"folderpath": str(self.folder("Other"))}))
        self.assertIsNone(trust_rules.allows("delete_folder", {"folderpath": str(downloads / "x")}))

    def test_some_things_can_never_be_trusted(self):
        for tool_id, args in (("database_restore", {"backup_path": "x"}), ("pc_control", {"action": "shutdown"}),
                              ("pc_control", {"action": "restart"}), ("github_integration", {"action": "commit_push"})):
            for _ in range(4):
                self.assertIsNone(trust_rules.note_approval(tool_id, args))
        with self.assertRaises(ValueError):
            trust_rules.allow({"tool_id": "database_restore", "kind": "tool", "value": "*"})
        with self.assertRaises(ValueError):
            trust_rules.allow({"tool_id": "delete_folder", "kind": "folder", "value": str(Path.home())})
        with self.assertRaises(ValueError):
            trust_rules.allow({"tool_id": "terminal_run", "kind": "tool", "value": "*"})

    def test_ai_has_no_way_to_create_rules(self):
        choices = JarvisActionsArgs.model_fields["action"].annotation.__args__
        self.assertNotIn("allow", choices)
        self.assertFalse(any("allow" in c and c != "revoke" for c in choices))

    def test_trusted_action_runs_without_asking_and_is_labelled(self):
        src = self.folder("Inbox", "report")
        dest = self.folder("Inbox", "archive")
        registry = ToolRegistry()
        asked = run(registry.execute_tool("move_folder", {"source_path": str(src), "destination_path": str(dest)},
                                          session_id="t7"))
        self.assertEqual(asked.get("status"), "PENDING_CONFIRMATION")
        trust_rules.allow({"tool_id": "move_folder", "kind": "folder", "value": str(self.root / "Inbox"),
                           "label": "move folders inside Inbox"})
        done = run(registry.execute_tool("move_folder", {"source_path": str(src), "destination_path": str(dest)},
                                         session_id="t7"))
        self.assertTrue(done["success"], done)
        self.assertEqual(done["trusted_by_rule"]["label"], "move folders inside Inbox")

    def test_confirm_counts_and_offers(self):
        registry = ToolRegistry()
        offer = None
        for index in range(3):
            path = self.folder("Work", f"p{index}")
            pending = run(registry.execute_tool("rename_folder", {"old_path": str(path), "new_path": str(path) + "_x"},
                                                session_id="t7c"))
            result = run(registry.execute_pending_action(pending["confirmation_token"], "t7c"))
            self.assertTrue(result["success"], result)
            offer = result.get("trust_offer")
        self.assertIsNotNone(offer)
        self.assertEqual(Path(offer["value"]), self.root / "Work")


class TestApiAndLog(Sandbox):
    def test_cancel_drops_the_action_and_trust_api_validates(self):
        client = TestClient(__import__("backend.app.main", fromlist=["app"]).app)
        path = self.folder("KeepMe")
        pending = run(ToolRegistry().execute_tool("delete_folder", {"folderpath": str(path)}, session_id="t7api"))
        cancel = client.post("/api/actions/cancel", json={"confirmation_token": pending["confirmation_token"],
                                                          "session_id": "t7api"}).json()
        self.assertTrue(cancel["data"]["cancelled"])
        confirm = client.post("/api/actions/confirm", json={"confirmation_token": pending["confirmation_token"],
                                                            "session_id": "t7api"}).json()
        self.assertFalse(confirm["success"])
        self.assertTrue(path.exists())
        bad = client.post("/api/trust", json={"tool_id": "database_restore", "kind": "tool", "value": "*"}).json()
        self.assertFalse(bad["success"])
        good = client.post("/api/trust", json={"tool_id": "organize_folder", "kind": "folder",
                                               "value": str(self.folder("Downloads"))}).json()
        self.assertTrue(good["success"], good)
        self.assertEqual(len(client.get("/api/trust").json()["data"]["rules"]), 1)
        client.delete(f"/api/trust/{good['data']['rule']['id']}")
        self.assertEqual(client.get("/api/trust").json()["data"]["rules"], [])

    def test_what_did_you_do_today(self):
        registry = ToolRegistry()
        run(registry.execute_tool("create_folder", {"folderpath": str(self.root / "LogMe")}, session_id="t7log"))
        run(registry.execute_tool("delete_folder", {"folderpath": str(self.root / "LogMe")}, session_id="t7log"))
        log = run(JarvisActionsTool().execute(action="log", day="today"))
        self.assertTrue(log["success"], log)
        tools = [item["tool"] for item in log["data"]["latest"]]
        self.assertIn("Folder Creator", tools)
        self.assertNotIn("Folder Deleter", tools)  # only asked, never ran


if __name__ == "__main__":
    unittest.main()
