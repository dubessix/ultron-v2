"""V2 Step 6 - new Jarvis PC tools. OS commands are mocked: no real app,
shutdown or screenshot ever happens in tests (Windows and Ubuntu CI)."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.tools import pc_tools
from backend.app.tools.pc_tools import (
    AppsTool, ClipboardTool, FileActionsTool, NotifyTool, PcControlTool, ScreenshotTool,
)
from backend.app.tools.tool_registry import ToolRegistry

NEW_TOOLS = ("apps", "pc_control", "file_actions", "clipboard", "screenshot", "notify")


def run(coro):
    return asyncio.run(coro)


class TempDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)


class TestRegistered(unittest.TestCase):
    def test_all_new_tools_are_registered_and_in_menu(self):
        from backend.app.tools.tool_catalog import build_tool_menu

        ids = ToolRegistry().get_registered_ids()
        menu = build_tool_menu(ids)
        for tool_id in NEW_TOOLS:
            self.assertIn(tool_id, ids)
            self.assertIn(tool_id + "(", menu)
        self.assertLess(len(menu) // 4, 1100)

    def test_risky_actions_need_the_owners_ok(self):
        self.assertEqual(AppsTool().permission_for_arguments({"action": "close"}), 2)
        self.assertLess(AppsTool().permission_for_arguments({"action": "open"}), 2)
        for action in ("sleep", "restart", "shutdown"):
            self.assertEqual(PcControlTool().permission_for_arguments({"action": action}), 2)
        for action in ("lock", "volume", "status", "mute"):
            self.assertLess(PcControlTool().permission_for_arguments({"action": action}), 2)

    def test_shutdown_through_registry_waits_for_confirmation(self):
        with patch.object(pc_tools, "_run") as fake:
            result = run(ToolRegistry().execute_tool("pc_control", {"action": "shutdown"}, session_id="s6"))
        self.assertEqual(result.get("status"), "PENDING_CONFIRMATION")
        fake.assert_not_called()


@unittest.skipIf(os.name == "nt", "Linux .desktop launcher")
class TestOpenAppLinux(TempDir):
    def setUp(self):
        super().setUp()
        (self.dir / "whatsapp-desktop.desktop").write_text(
            "[Desktop Entry]\nName=WhatsApp\nExec=/opt/whatsapp/whatsapp %U\n", encoding="utf-8")
        (self.dir / "org.videolan.vlc.desktop").write_text(
            "[Desktop Entry]\nName=VLC media player\nExec=/usr/bin/vlc --started-from-file %U\n", encoding="utf-8")
        (self.dir / "hidden.desktop").write_text("[Desktop Entry]\nName=Hidden\nExec=x\nNoDisplay=true\n", encoding="utf-8")
        for item in (patch.object(pc_tools, "_desktop_dirs", lambda: [self.dir]),
                     patch.object(pc_tools.shutil, "which", lambda name: None)):
            item.start()
            self.addCleanup(item.stop)

    def test_open_by_spoken_name(self):
        for spoken, argv in (("WhatsApp", ["/opt/whatsapp/whatsapp"]), ("whats app", ["/opt/whatsapp/whatsapp"]),
                             ("vlc", ["/usr/bin/vlc", "--started-from-file"])):
            with self.subTest(spoken=spoken), patch.object(pc_tools, "_spawn") as spawn:
                result = run(AppsTool().execute(action="open", name=spoken))
                self.assertTrue(result["success"], result)
                spawn.assert_called_once_with(argv)

    def test_unknown_app_is_honest(self):
        with patch.object(pc_tools, "_spawn") as spawn:
            result = run(AppsTool().execute(action="open", name="Hidden"))
        self.assertFalse(result["success"])
        self.assertIn("No installed app", result["error"])
        spawn.assert_not_called()


class TestAppsRunningAndClose(unittest.TestCase):
    def test_running_lists_heavy_apps(self):
        result = AppsTool._running(5)
        self.assertTrue(result["success"])
        self.assertLessEqual(len(result["data"]["apps"]), 5)
        self.assertIn("ram_free_gb", result["data"])

    def test_only_the_owners_own_matching_apps_can_close(self):
        from types import SimpleNamespace

        me = pc_tools._current_user()

        def proc(pid, name, user):
            return SimpleNamespace(info={"pid": pid, "name": name, "username": user})

        ok = lambda p, name=None, pid=None: pc_tools._closable(p, name, pid)  # noqa: E731
        self.assertTrue(ok(proc(9001, "chrome", me), "chrome"))
        self.assertTrue(ok(proc(9002, "chrome.exe", "PC\\" + me), "Chrome"))
        self.assertTrue(ok(proc(9003, "vlc", me), pid=9003))
        self.assertFalse(ok(proc(9004, "chrome", "root"), "chrome"))            # other user / service
        self.assertFalse(ok(proc(9005, "systemd-journald", me), "systemd"))     # system prefix
        self.assertFalse(ok(proc(9006, "gnome-shell", me), "gnome"))
        self.assertFalse(ok(proc(9007, "explorer.exe", me), "explorer"))
        self.assertFalse(ok(proc(os.getpid(), "python", me), "python"))         # Ultron itself
        self.assertFalse(ok(proc(9008, "mychrome-helper", me), "chrome"))       # start of name only
        self.assertFalse(ok(proc(9009, "vi", me), "vi"))                        # too short to be safe

    def test_close_never_touches_system_in_real_process_list(self):
        import psutil

        with patch.object(psutil.Process, "terminate") as terminate:
            result = AppsTool._close("systemd", None)
        self.assertFalse(result["success"])
        terminate.assert_not_called()


class TestPcControl(unittest.TestCase):
    def test_volume_needs_a_level(self):
        self.assertFalse(run(PcControlTool().execute(action="volume"))["success"])

    def test_runs_the_first_available_command(self):
        calls = []

        async def fake_run(argv, timeout=15.0, stdin=None):
            calls.append(argv)
            return 0, "", ""

        with patch.object(pc_tools.shutil, "which", lambda n: "/bin/" + n), patch.object(pc_tools, "_run", fake_run):
            result = run(PcControlTool().execute(action="volume", level=40))
            restart = run(PcControlTool().execute(action="restart"))
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["level"], 40)
        self.assertEqual(len(calls), 2)
        self.assertEqual(restart["data"]["in_seconds"], 60)  # a minute to cancel

    def test_missing_commands_are_reported(self):
        with patch.object(pc_tools.shutil, "which", lambda n: None):
            result = run(PcControlTool().execute(action="lock"))
        self.assertFalse(result["success"])

    def test_status_reports_battery_or_desktop(self):
        result = run(PcControlTool().execute(action="status"))
        self.assertTrue(result["success"])
        self.assertTrue("battery_percent" in result["data"] or "battery" in result["data"])


class TestFileActions(TempDir):
    def setUp(self):
        super().setUp()
        (self.dir / "big.iso").write_bytes(b"0" * 300_000)
        (self.dir / "report.pdf").write_bytes(b"0" * 1000)
        old = self.dir / "old.pdf"
        old.write_bytes(b"0" * 500)
        month_ago = time.time() - 30 * 86400
        os.utime(old, (month_ago, month_ago))
        (self.dir / "node_modules").mkdir()
        (self.dir / "node_modules" / "huge.bin").write_bytes(b"0" * 900_000)

    def test_biggest_files_skip_junk_folders(self):
        result = run(FileActionsTool().execute(action="biggest", path=str(self.dir)))
        self.assertTrue(result["data"]["files"][0]["path"].endswith("big.iso"))
        self.assertFalse(any("node_modules" in f["path"] for f in result["data"]["files"]))

    def test_pdfs_from_last_week(self):
        result = run(FileActionsTool().execute(action="recent", path=str(self.dir), ext="pdf", days=7))
        names = [Path(f["path"]).name for f in result["data"]["files"]]
        self.assertEqual(names, ["report.pdf"])

    def test_open_uses_default_app_and_missing_file_fails(self):
        with patch.object(pc_tools, "_spawn") as spawn, patch.object(pc_tools.shutil, "which", lambda n: "/usr/bin/" + n), \
                patch.object(pc_tools.os, "startfile", create=True) as startfile:
            ok = run(FileActionsTool().execute(action="open", path=str(self.dir / "report.pdf")))
        self.assertTrue(ok["success"])
        self.assertTrue(spawn.called or startfile.called)
        self.assertFalse(run(FileActionsTool().execute(action="open", path=str(self.dir / "nope.pdf")))["success"])


class TestClipboardScreenshotNotify(TempDir):
    def test_clipboard_read_write_save(self):
        store = {"text": ""}

        async def fake_run(argv, timeout=15.0, stdin=None):
            if stdin is not None:
                store["text"] = stdin
                return 0, "", ""
            return 0, store["text"], ""

        with patch.object(pc_tools.shutil, "which", lambda n: "/usr/bin/" + n), patch.object(pc_tools, "_run", fake_run), \
                patch("backend.app.security.path_locator.home_folder", lambda w: self.dir):
            self.assertTrue(run(ClipboardTool().execute(action="write", text="meeting at 5"))["success"])
            self.assertEqual(run(ClipboardTool().execute(action="read"))["data"]["text"], "meeting at 5")
            saved = run(ClipboardTool().execute(action="save"))
        self.assertIn("meeting at 5", Path(saved["data"]["saved_to"]).read_text(encoding="utf-8"))

    def test_clipboard_unavailable_is_honest(self):
        with patch.object(pc_tools.shutil, "which", lambda n: None):
            self.assertFalse(run(ClipboardTool().execute(action="read"))["success"])

    def test_screenshot_saved_to_pictures_ultron(self):
        async def fake_run(argv, timeout=15.0, stdin=None):
            target = next((a for a in argv if a.endswith(".png")), None)
            if target is None:  # Windows: path is inside the PowerShell script
                target = argv[-1].split("$i.Save('")[1].split("')")[0]
            Path(target).write_bytes(b"\x89PNG....")
            return 0, "", ""

        with patch.object(pc_tools.shutil, "which", lambda n: "/usr/bin/" + n), patch.object(pc_tools, "_run", fake_run), \
                patch("backend.app.security.path_locator.home_folder", lambda w: self.dir):
            result = run(ScreenshotTool().execute())
        self.assertTrue(result["success"], result)
        self.assertEqual(Path(result["data"]["saved_to"]).parent, self.dir / "Ultron")

    def test_notify(self):
        async def fake_run(argv, timeout=15.0, stdin=None):
            return 0, "", ""

        with patch.object(pc_tools.shutil, "which", lambda n: "/usr/bin/" + n), patch.object(pc_tools, "_run", fake_run):
            self.assertTrue(run(NotifyTool().execute(message="Build finished"))["success"])


if __name__ == "__main__":
    unittest.main()
