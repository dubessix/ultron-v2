"""V2 Step E4-E7 + E1: self-cleaning, plain-words doctor, autostart, one-word
restore, locked package versions. Everything runs on temp folders; nothing
touches real systemd, the real Startup folder or real user data."""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from backend.app import autostart, health_checks
from backend.app.database import backup as backup_module
from backend.app.database import db as _db
from backend.app.database import durability

ROOT = Path(__file__).resolve().parents[1]


def _make_file(path: Path, size: int, age_seconds: float = 0.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    stamp = time.time() - age_seconds
    os.utime(path, (stamp, stamp))
    return path


class TempFolder(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ultron_e4_"))
        self.addCleanup(shutil.rmtree, self.dir, True)


# ----------------------------------------------------------------------- E4
class TestSelfCleaning(TempFolder):
    def test_backups_total_size_is_capped_but_newest_three_stay(self):
        for index in range(10):  # 10 x 1 MB, oldest first
            _make_file(self.dir / f"ultron_{index:02d}.db", 1024 * 1024, age_seconds=1000 - index)
        result = backup_module.prune_backups(self.dir, generations=30, max_total_bytes=4 * 1024 * 1024)
        left = sorted(p.name for p in self.dir.glob("ultron_*.db"))
        self.assertEqual(left, ["ultron_06.db", "ultron_07.db", "ultron_08.db", "ultron_09.db"])
        self.assertEqual(result["removed"], 6)

        # Even when 3 copies are bigger than the cap, the newest three are kept.
        backup_module.prune_backups(self.dir, generations=30, max_total_bytes=1)
        self.assertEqual(len(list(self.dir.glob("ultron_*.db"))), backup_module.MIN_BACKUPS_KEPT)

    def test_generation_rule_still_works_without_size_cap(self):
        for index in range(6):
            _make_file(self.dir / f"ultron_{index}.db", 10, age_seconds=100 - index)
        backup_module.prune_backups(self.dir, generations=2)
        self.assertEqual(sorted(p.name for p in self.dir.glob("ultron_*.db")), ["ultron_4.db", "ultron_5.db"])

    def test_big_log_is_trimmed_to_its_newest_whole_lines(self):
        log = self.dir / "launcher-ui.log"
        lines = [f"line {i:06d} {'y' * 50}\n" for i in range(4000)]
        log.write_text("".join(lines), encoding="utf-8")
        small = self.dir / "small.log"
        small.write_text("keep me\n", encoding="utf-8")
        result = durability.cap_log_sizes(self.dir, max_bytes=100_000)
        self.assertEqual(result["trimmed"], 1)
        text = log.read_text(encoding="utf-8")
        self.assertLessEqual(len(text.encode()), 50_000)
        self.assertTrue(text.startswith("line "))            # cut at a line start
        self.assertTrue(text.endswith(lines[-1]))            # newest kept
        self.assertEqual(small.read_text(encoding="utf-8"), "keep me\n")

    def test_edit_backups_have_a_total_size_cap(self):
        from backend.app.tools import safe_write

        folder = self.dir / "file_backups"
        for index in range(5):
            _make_file(folder / f"b{index}.txt", 1000, age_seconds=100 - index)
        with patch.object(safe_write, "BACKUPS_MAX_BYTES", 2500):
            safe_write._prune_backups(folder)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["b3.txt", "b4.txt"])
        # One huge newest file is still kept (never delete the only backup).
        _make_file(folder / "huge.txt", 10_000)
        with patch.object(safe_write, "BACKUPS_MAX_BYTES", 2500):
            safe_write._prune_backups(folder)
        self.assertEqual([p.name for p in folder.iterdir()], ["huge.txt"])

    def test_scheduler_skips_backup_when_it_would_not_fit_and_prunes_daily(self):
        settings = durability.DurabilitySettings()
        scheduler = durability.DurabilityScheduler(settings)
        full = shutil._ntuple_diskusage(100, 99, 1)  # 1 byte free
        with patch.object(durability.shutil, "disk_usage", return_value=full), \
             patch.object(durability, "backup_database") as backup, \
             patch.object(durability, "check_integrity", return_value={}), \
             patch.object(durability, "checkpoint_wal", return_value={}), \
             patch.object(durability, "prune_audit_logs", return_value={}), \
             patch.object(durability, "_prune_terminal_jobs", return_value={"success": True}) as jobs, \
             patch.object(durability, "_latest_backup_mtime", return_value=None):
            result = scheduler.run_once(force=True)
        backup.assert_not_called()
        self.assertEqual(result["backup"]["status"], "skipped_low_disk")
        jobs.assert_called_once()
        for key in ("backups", "safety_copies", "big_logs", "terminal_jobs"):
            self.assertIn(key, result["retention"])

    def test_low_disk_rule_uses_database_size(self):
        scheduler = durability.DurabilityScheduler(durability.DurabilitySettings())
        roomy = shutil._ntuple_diskusage(10 * 1024 ** 3, 0, 800 * 1024 ** 2)  # 800 MB free
        with patch.object(durability.shutil, "disk_usage", return_value=roomy):
            self.assertFalse(scheduler._disk_is_low())  # small DB -> backups continue

    def test_settings_have_bounded_new_fields(self):
        settings = durability.load_durability_settings()
        self.assertGreaterEqual(settings.backups_max_total_mb, 100)
        self.assertGreaterEqual(settings.min_free_disk_mb, 50)

    def test_launch_log_rotates_by_size(self):
        import launcher as launcher_module

        launcher = launcher_module.ServiceLauncher.__new__(launcher_module.ServiceLauncher)
        launcher.launch_log_path = self.dir / "launch.log"
        _make_file(launcher.launch_log_path, launcher.MAX_LAUNCH_LOG_BYTES + 10)
        launcher._append_launch_log("fresh start\n")
        self.assertTrue((self.dir / "launch.old.log").is_file())
        self.assertLess(launcher.launch_log_path.stat().st_size, 1000)


# ----------------------------------------------------------------------- E6
class TestAutostart(TempFolder):
    def test_linux_unit_restarts_on_crash_and_stops_crash_loops(self):
        text = autostart.linux_unit_text(python="/usr/bin/python3")
        for needed in ("Restart=on-failure", "RestartSec=5", "StartLimitBurst=5",
                       "StartLimitIntervalSec=300", "WantedBy=graphical-session.target",
                       'Environment="ULTRON_AUTOSTART=1"',
                       'ExecStart="/usr/bin/python3" -m backend.app.cli start'):
            self.assertIn(needed, text)
        self.assertIn('Environment="ULTRON_HOME=', text)
        # StartLimit* belong in [Unit], Restart in [Service].
        unit, service = text.split("[Service]")[0], text.split("[Service]")[1]
        self.assertIn("StartLimitBurst", unit)
        self.assertIn("Restart=on-failure", service)

    @unittest.skipUnless(shutil.which("systemd-analyze"), "needs systemd-analyze")
    def test_linux_unit_passes_systemd_verify(self):
        import subprocess

        unit = self.dir / "ultron.service"
        unit.write_text(autostart.linux_unit_text(python=shutil.which("python3") or "/bin/true"))
        done = subprocess.run(["systemd-analyze", "verify", str(unit)],
                              capture_output=True, text=True, timeout=30)
        self.assertNotIn("ultron.service:", done.stderr)  # no syntax complaints about our file

    def test_linux_on_off_status_use_user_systemd_only(self):
        calls = []

        def fake_systemctl(*args):
            calls.append(args)
            if args[0] == "is-enabled":
                return True, "enabled"
            return True, ""

        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.dir)}), \
             patch.object(autostart.platform, "system", return_value="Linux"), \
             patch.object(autostart, "_systemctl", side_effect=fake_systemctl):
            self.assertFalse(autostart.status()["enabled"])
            result = autostart.enable()
            self.assertTrue(result["success"])
            unit = self.dir / "systemd" / "user" / "ultron.service"
            self.assertTrue(unit.is_file())
            self.assertTrue(autostart.status()["enabled"])
            autostart.disable()
            self.assertFalse(unit.exists())
        self.assertIn(("enable", "ultron.service"), calls)
        self.assertIn(("disable", "ultron.service"), calls)
        self.assertNotIn("--now", {a for call in calls for a in call})  # never kills the running one

    def test_linux_enable_reports_systemd_problem_plainly(self):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.dir)}), \
             patch.object(autostart.platform, "system", return_value="Linux"), \
             patch.object(autostart, "_systemctl", return_value=(False, "Failed to connect to bus")):
            result = autostart.enable()
        self.assertFalse(result["success"])
        self.assertIn("Failed to connect to bus", result["message"])

    def test_windows_startup_files(self):
        with patch.dict(os.environ, {"APPDATA": str(self.dir)}), \
             patch.object(autostart.platform, "system", return_value="Windows"), \
             patch.object(autostart, "windows_runner_path", return_value=self.dir / "run_ultron.cmd"):
            self.assertTrue(autostart.enable()["success"])
            entry = autostart.windows_entry_path()
            self.assertTrue(entry.is_file())
            self.assertIn("/min", entry.read_text())
            runner = (self.dir / "run_ultron.cmd").read_text()
            self.assertIn("if %tries% geq 5 goto :eof", runner)   # bounded restarts
            self.assertIn("if %errorlevel%==0 goto :eof", runner)  # normal stop stays stopped
            self.assertTrue(autostart.status()["enabled"])
            autostart.disable()
            self.assertFalse(entry.exists())

    def test_browser_opens_once_per_boot_under_autostart(self):
        import launcher as launcher_module

        launcher = launcher_module.ServiceLauncher.__new__(launcher_module.ServiceLauncher)
        launcher.application_home = self.dir
        with patch.dict(os.environ, {"ULTRON_AUTOSTART": "1"}):
            self.assertFalse(launcher.browser_already_opened_this_boot())  # first start: open
            self.assertTrue(launcher.browser_already_opened_this_boot())   # crash restart: no tab
        with patch.dict(os.environ, {"ULTRON_AUTOSTART": ""}):
            self.assertFalse(launcher.browser_already_opened_this_boot())  # manual start: open

    def test_cli_autostart_command(self):
        from backend.app.cli import main

        with patch.object(autostart, "enable", return_value={"success": True, "message": "done"}), \
             patch.object(autostart, "status", return_value={"enabled": True, "how": "x", "detail": "y"}):
            runner = CliRunner()
            self.assertEqual(runner.invoke(main, ["autostart", "on"]).exit_code, 0)
            out = runner.invoke(main, ["autostart"]).output
        self.assertIn("Autostart is ON", out)


# ----------------------------------------------------------------------- E5
class TestPlainDoctor(TempFolder):
    def test_browser_helper_three_states(self):
        ok = health_checks.check_browser_helper(8000, fetch=lambda url: {"browser_helper": {"connected": True, "version": "1.1.0"}})
        self.assertEqual(ok[0][0], "ok")
        self.assertIn("1.1.0", ok[0][1])
        off = health_checks.check_browser_helper(8000, fetch=lambda url: {"browser_helper": {"connected": False}})
        self.assertEqual(off[0][0], "warn")
        self.assertIn("chrome://extensions", off[0][2])

        def down(url):
            raise ConnectionError("refused")
        self.assertIn("start Ultron first", health_checks.check_browser_helper(8000, fetch=down)[0][1])

    def test_disk_levels(self):
        def usage(free):
            return shutil._ntuple_diskusage(100 * 1024 ** 3, 0, free)
        with patch.object(health_checks.shutil, "disk_usage", return_value=usage(500 * 1024 ** 2)):
            self.assertEqual(health_checks.check_disk(self.dir)[0][0], "fail")
        with patch.object(health_checks.shutil, "disk_usage", return_value=usage(3 * 1024 ** 3)):
            self.assertEqual(health_checks.check_disk(self.dir)[0][0], "warn")
        with patch.object(health_checks.shutil, "disk_usage", return_value=usage(50 * 1024 ** 3)):
            self.assertEqual(health_checks.check_disk(self.dir)[0][0], "ok")

    def _db(self, damaged: bool = False) -> Path:
        path = self.dir / "ultron.db"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE conversations (id TEXT)")
        conn.execute("CREATE TABLE vector_memories (id TEXT)")
        conn.executemany("INSERT INTO conversations VALUES (?)", [("a",), ("b",)])
        conn.execute("INSERT INTO vector_memories VALUES ('m')")
        conn.commit()
        conn.close()
        if damaged:
            data = bytearray(path.read_bytes())
            data[100:4000] = b"\x00" * 3900
            path.write_bytes(bytes(data))
        return path

    def test_database_healthy_counts_memory_and_backup_age(self):
        db = self._db()
        backups = self.dir / "backups"
        _make_file(backups / "ultron_old.db", 2048, age_seconds=5 * 86400)
        results = health_checks.check_database(db, backups)
        self.assertEqual(results[0][0], "ok")
        self.assertIn("2 chats, 1 saved memories", results[0][1])
        self.assertEqual(results[1][0], "warn")  # newest backup is 5 days old
        _make_file(backups / "ultron_new.db", 2048)
        self.assertIn("today", health_checks.check_database(db, backups)[1][1])

    def test_damaged_database_says_how_to_fix(self):
        results = health_checks.check_database(self._db(damaged=True), self.dir / "none")
        self.assertEqual(results[0][0], "fail")
        self.assertIn("ultron backup --restore", results[0][2])

    def test_no_keys_is_a_warning_with_a_fix(self):
        class NoKeys:
            def active_keys(self, provider):
                return ["your_groq_key_here"] if provider == "groq" else []
        with patch("backend.app.brain.api_key_manager.APIKeyManager", return_value=NoKeys()):
            result = health_checks.check_keys()
        self.assertEqual(result[0][0], "warn")
        self.assertIn("GROQ_API_KEY_1", result[0][2])

    def test_retired_model_is_reported(self):
        from backend.app.brain import model_fallback

        with patch.object(model_fallback, "status", return_value={"gone": ["groq|openai/gpt-oss-120b"], "discovered": {}}):
            result = health_checks.check_models()
        self.assertTrue(any("groq openai/gpt-oss-120b" in line for _, line, _ in result))

    def test_one_broken_check_never_hides_the_rest(self):
        with patch.object(health_checks, "check_keys", side_effect=RuntimeError("boom")), \
             patch.object(health_checks, "check_browser_helper", return_value=[("ok", "helper", "")]), \
             patch.object(health_checks, "check_autostart", return_value=[("ok", "auto", "")]):
            results = health_checks.run_all(home=self.dir, db_path=self.dir / "x.db",
                                            backup_dir=self.dir, port=1)
        lines = [line for _, line, _ in results]
        self.assertTrue(any("boom" in line for line in lines))
        self.assertIn("auto", lines)
        for _, line, _ in results:
            self.assertNotRegex(line, r"gsk_|AIza")  # never prints a key


# ----------------------------------------------------------------------- E7
class TestOneWordRestore(TempFolder):
    def setUp(self):
        super().setUp()
        self._orig = (_db.DB_PATH, _db.DB_DIR)
        _db.DB_DIR = self.dir
        _db.DB_PATH = self.dir / "ultron.db"
        self.addCleanup(self._put_back)
        from backend.app.database.models import initialize_database

        with _db.get_db_connection() as conn:
            initialize_database(conn)
            conn.execute("CREATE TABLE IF NOT EXISTS vector_memories (id TEXT PRIMARY KEY, type TEXT, "
                         "content TEXT, embedding BLOB, metadata TEXT, created_at DATETIME)")
            conn.execute("INSERT OR IGNORE INTO sessions (id, current_goal, current_mode, personality) "
                         "VALUES ('s', 'g', 'developer', 'ultron')")
            conn.execute("INSERT INTO conversations (id, session_id, user_message, ai_response, personality, "
                         "tools_used, intent, mode, path_used, response_ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (str(uuid.uuid4()), "s", "my sister is Riya", "Saved.", "ultron", "[]",
                          "Conversation", "developer", "fast", 1))
            conn.execute("INSERT INTO vector_memories VALUES ('m1', 'semantic', 'Sister: Riya', x'00', "
                         "'{\"kind\": \"fact\"}', CURRENT_TIMESTAMP)")
            conn.commit()

    def _put_back(self):
        _db.DB_PATH, _db.DB_DIR = self._orig

    def test_restore_without_path_skips_damaged_newest_and_brings_memory_back(self):
        from backend.app.cli import main

        good = backup_module.backup_database()
        self.assertTrue(good["success"])
        time.sleep(0.02)
        broken = backup_module.get_approved_backup_root() / "ultron_99999999_999999_999999.db"
        broken.write_bytes(b"not a database at all" * 100)
        self.assertEqual(backup_module.newest_good_backup(), Path(good["data"]["backup_path"]))

        with _db.get_db_connection() as conn:  # disaster: memory wiped
            conn.execute("DELETE FROM vector_memories")
            conn.execute("DELETE FROM conversations")
            conn.commit()

        out = CliRunner().invoke(main, ["backup", "--restore", "--yes"])
        self.assertEqual(out.exit_code, 0, out.output)
        self.assertIn("Restored", out.output)
        with _db.get_db_connection() as conn:
            self.assertEqual(conn.execute("SELECT content FROM vector_memories").fetchone()[0], "Sister: Riya")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0], 1)

    def test_restore_with_no_backups_changes_nothing(self):
        from backend.app.cli import main

        out = CliRunner().invoke(main, ["backup", "--restore", "--yes"])
        self.assertIn("No good backup found", out.output)
        with _db.get_db_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM vector_memories").fetchone()[0], 1)


# ----------------------------------------------------------------------- E1
class TestLockedVersions(unittest.TestCase):
    def test_constraints_cover_every_requirement_with_same_version(self):
        pins = {}
        for line in (ROOT / "constraints.txt").read_text(encoding="utf-8").splitlines():
            line = line.split(";")[0].strip()
            if line and not line.startswith("#"):
                name, version = line.split("==")
                pins[name.lower().replace("_", "-")] = version
        self.assertGreater(len(pins), 20)  # hidden dependencies are locked too
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                name, version = line.strip().split("==")
                self.assertEqual(pins[name.lower().replace("_", "-")], version, name)
        for hidden in ("starlette", "anyio", "pydantic-core", "h11", "aiohttp"):
            self.assertIn(hidden, pins)

    def test_installer_and_ci_use_the_constraints(self):
        self.assertIn("constraints.txt", (ROOT / "backend" / "app" / "installer.py").read_text(encoding="utf-8"))
        workflow = (ROOT / ".github" / "workflows" / "ultron-cloud-test.yml").read_text(encoding="utf-8")
        self.assertIn("-c constraints.txt", workflow)


if __name__ == "__main__":
    unittest.main()
