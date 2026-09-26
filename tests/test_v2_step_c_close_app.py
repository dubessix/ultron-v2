"""V2 Step C1-C2: close app never lies.

Close gently -> check the process is really gone -> say the truth. A stubborn
app is reported as still running; force only when asked. System parts and
Ultron himself are never closed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.tools import pc_tools
from backend.app.tools.pc_tools import AppsTool


def fake_proc(pid, name, exe=None, cmdline=None, user=None):
    return SimpleNamespace(pid=pid, info={"pid": pid, "name": name, "exe": exe, "cmdline": cmdline or [],
                                         "username": user if user is not None else pc_tools._current_user()})


@unittest.skipIf(os.name == "nt", "real process-name test uses a Linux symlink")
class TestRealFakeApp(unittest.TestCase):
    def start_app(self, name, ignore_term=False):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        link = os.path.join(folder, name)
        os.symlink(sys.executable, link)
        code = "import signal,time\n"
        if ignore_term:
            code += "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        code += "print('up', flush=True)\ntime.sleep(60)\n"
        proc = subprocess.Popen([link, "-c", code], stdout=subprocess.PIPE)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        proc.stdout.readline()  # it is running
        return proc

    def test_closes_and_verifies_it_is_gone(self):
        app = self.start_app("ultronfakeapp")
        result = AppsTool._close("ultronfakeapp", None)
        self.assertTrue(result["success"], result)
        self.assertTrue(result["data"]["verified_gone"])
        app.wait(timeout=5)
        self.assertIsNotNone(app.poll())

    def test_stubborn_app_is_reported_then_force_closes(self):
        app = self.start_app("ultronstubborn", ignore_term=True)
        started = time.monotonic()
        result = AppsTool._close("ultronstubborn", None)
        self.assertFalse(result["success"], "never says closed while it runs")
        self.assertIn("still running", result["error"])
        self.assertLess(time.monotonic() - started, 12)
        self.assertIsNone(app.poll())
        forced = AppsTool._close("ultronstubborn", None, force=True)
        self.assertTrue(forced["success"], forced)
        app.wait(timeout=5)

    def test_not_running_is_said_plainly(self):
        result = AppsTool._close("ultronnothinglikethis", None)
        self.assertFalse(result["success"])
        self.assertIn("is not running", result["error"])


class TestMatching(unittest.TestCase):
    def keys(self, name, apps=None):
        with patch.object(pc_tools, "_linux_apps", return_value=apps or {}), patch.object(pc_tools, "IS_WINDOWS", False):
            return pc_tools._target_keys(name)

    def test_calculator_and_terminal_are_no_longer_blocked(self):
        calc = fake_proc(9101, "gnome-calculator")
        term = fake_proc(9102, "gnome-terminal-server")
        self.assertTrue(pc_tools._closable(calc, "calculator", None, self.keys("calculator")))
        self.assertTrue(pc_tools._closable(term, "terminal", None, self.keys("terminal")))

    def test_launcher_file_links_chrome_name_to_its_process(self):
        apps = {"googlechrome": ("google-chrome", "/usr/bin/google-chrome-stable %U")}
        chrome = fake_proc(9103, "chrome", exe="/opt/google/chrome/chrome")
        self.assertTrue(pc_tools._closable(chrome, "google chrome", None, self.keys("google chrome", apps)))

    def test_snap_firefox_by_program_path(self):
        firefox = fake_proc(9104, "firefox", exe="/snap/firefox/1234/usr/lib/firefox/firefox")
        self.assertTrue(pc_tools._closable(firefox, "Firefox", None, self.keys("Firefox")))

    def test_spoken_word_does_not_grab_other_programs(self):
        code = fake_proc(9105, "code")
        self.assertFalse(pc_tools._closable(code, "codeblocks", None, self.keys("codeblocks")))
        helper = fake_proc(9106, "mychrome-helper")
        self.assertFalse(pc_tools._closable(helper, "chrome", None, self.keys("chrome")))

    def test_ultron_itself_is_never_closed(self):
        from backend.app.install_paths import ASSET_ROOT
        server = fake_proc(9107, "node", cmdline=["node", f"{ASSET_ROOT}/frontend/node_modules/.bin/vite"])
        self.assertFalse(pc_tools._closable(server, "node", None, self.keys("node")))
        me = fake_proc(os.getpid(), "python3")
        self.assertFalse(pc_tools._closable(me, "python", None, self.keys("python")))
        editor = fake_proc(9108, "code", cmdline=["/usr/share/code/code", str(ASSET_ROOT)])
        self.assertTrue(pc_tools._closable(editor, "code", None, self.keys("code")), "VS Code on Ultron folder")


class TestProtectedParts(unittest.TestCase):
    def test_desktop_shell_is_refused_with_a_plain_reason(self):
        import psutil
        shell = fake_proc(9201, "gnome-shell")
        with patch.object(psutil, "process_iter", return_value=[shell]):
            result = AppsTool._close("gnome shell", None)
        self.assertFalse(result["success"])
        self.assertIn("part of the system", result["error"])


class TestGentleFirst(unittest.TestCase):
    def test_windows_uses_wm_close_not_a_hard_kill(self):
        with patch.object(pc_tools, "IS_WINDOWS", True), patch.object(pc_tools.subprocess, "run") as run:
            pc_tools._close_gently([SimpleNamespace(pid=11), SimpleNamespace(pid=12)], "notepad")
        argv = run.call_args.args[0]
        self.assertEqual(argv[:1], ["taskkill"])
        self.assertNotIn("/F", argv)
        self.assertIn("12", argv)


if __name__ == "__main__":
    unittest.main()
