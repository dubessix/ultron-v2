"""Beginner one-click setup, key preservation, prebuilt frontend, and shortcuts."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import psutil
from click.testing import CliRunner

from backend.app import cli, installer


class TestPrivateKeyEditor(unittest.TestCase):
    def test_key_save_preserves_existing_values_and_unrelated_lines(self):
        with tempfile.TemporaryDirectory(prefix="ultron keys ") as temp:
            root = Path(temp)
            env_file = root / ".env"
            example = root / ".env.example"
            example.write_text("GROQ_API_KEY_1=placeholder\nOTHER_SETTING=keep\n", encoding="utf-8")
            env_file.write_text("# local\nGROQ_API_KEY_1=old-secret\nOTHER_SETTING=keep\n", encoding="utf-8")
            with patch.object(installer, "ENV_FILE", env_file), patch.object(installer, "ENV_EXAMPLE", example):
                installer.save_keys({"GROQ_API_KEY_1": "", "GEMINI_API_KEY_1": "new-secret"})
            content = env_file.read_text(encoding="utf-8")
            self.assertIn("GROQ_API_KEY_1=old-secret", content)
            self.assertIn("GEMINI_API_KEY_1=new-secret", content)
            self.assertIn("OTHER_SETTING=keep", content)


class TestInstallerScripts(unittest.TestCase):
    def test_platform_scripts_quote_paths_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="Ultron Folder ") as temp:
            root = Path(temp)
            fake_venv = root / ".venv"
            python = fake_venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            python.parent.mkdir(parents=True)
            python.write_text("", encoding="utf-8")
            engine = installer.InstallerEngine(Mock(), Mock())
            with patch.object(installer, "ROOT", root), patch.object(
                installer, "APPLICATION_HOME", root
            ), patch.object(installer, "VENV_DIR", fake_venv):
                scripts = engine._write_launch_scripts()
            start = scripts["start"].read_text(encoding="utf-8")
            stop = scripts["stop"].read_text(encoding="utf-8")
            doctor = scripts["doctor"].read_text(encoding="utf-8")
            env_editor = scripts["env"].read_text(encoding="utf-8")
            expected_cd = f'cd /d "{root}"' if os.name == "nt" else f'cd "{root}"'
            self.assertIn(expected_cd, start)
            self.assertIn(' -m backend.app.cli start', start)
            self.assertIn(' -m backend.app.cli stop', stop)
            self.assertIn(' -m backend.app.cli doctor', doctor)
            self.assertIn(str(root / ".env"), env_editor)
            self.assertIn("ULTRON_LAUNCH_LOG", start)
            if os.name != "nt":
                self.assertTrue(scripts["start"].stat().st_mode & 0o100)

    def test_linux_application_menu_shortcuts_quote_space_paths(self):
        with tempfile.TemporaryDirectory(prefix="Ultron Menu ") as temp:
            root = Path(temp) / "Ultron Folder"
            home = Path(temp) / "Home Folder"
            root.mkdir()
            home.mkdir()
            (home / "Desktop").mkdir()
            icon = root / "images" / "ultron_icon.png"
            icon.parent.mkdir()
            icon.write_bytes(b"test-icon")
            fake_venv = root / ".venv"
            (fake_venv / "bin").mkdir(parents=True)
            (fake_venv / "bin" / "python").write_text("", encoding="utf-8")
            engine = installer.InstallerEngine(Mock(), Mock())
            with patch.object(installer, "ROOT", root), patch.object(
                installer, "APPLICATION_HOME", root
            ), patch.object(installer, "VENV_DIR", fake_venv), patch.object(
                installer.Path, "home", return_value=home
            ):
                scripts = engine._write_launch_scripts()
                engine._create_linux_shortcuts(scripts)
            desktop = home / ".local/share/applications/ultron.desktop"
            content = desktop.read_text(encoding="utf-8")
            self.assertIn(f'Exec="{scripts["start"]}"', content)
            self.assertIn("Terminal=true", content)
            self.assertIn(f"Icon={icon}", content)
            start_source = scripts["start"].read_text(encoding="utf-8")
            self.assertIn("launcher-ui.log", start_source)
            self.assertIn("ULTRON_LAUNCH_LOG", start_source)
            self.assertTrue((home / "Desktop" / "Ultron Doctor.desktop").is_file())
            self.assertTrue((home / "Desktop" / "Open Ultron .env.desktop").is_file())

    def test_windows_shortcuts_use_branded_ico_instead_of_python_icon(self):
        with tempfile.TemporaryDirectory(prefix="Ultron Windows Icon ") as temp:
            root = Path(temp) / "Ultron Folder"
            home = Path(temp) / "Owner Home"
            appdata = home / "AppData" / "Roaming"
            desktop = home / "Desktop"
            desktop.mkdir(parents=True)
            icon = root / "images" / "ultron_icon.ico"
            icon.parent.mkdir(parents=True)
            icon.write_bytes(b"test-icon")
            scripts = {}
            for key, filename in {
                "start": "Start Ultron.cmd",
                "stop": "Stop Ultron.cmd",
                "doctor": "Ultron Doctor.cmd",
                "env": "Open Ultron Env.cmd",
                "settings": "Ultron Keys.cmd",
            }.items():
                scripts[key] = root / filename
                scripts[key].write_text("@echo off\n", encoding="utf-8")
            engine = installer.InstallerEngine(Mock(), Mock())
            with patch.object(installer, "ROOT", root), patch.object(
                installer, "APPLICATION_HOME", root
            ), patch.object(installer.Path, "home", return_value=home), patch.dict(
                os.environ, {"APPDATA": str(appdata)}
            ), patch.object(installer.subprocess, "run") as run:
                engine._create_windows_shortcuts(scripts)
            self.assertEqual(run.call_count, 9)
            commands = [" ".join(call.args[0]) for call in run.call_args_list]
            self.assertTrue(all(str(icon) in command for command in commands), commands)
            self.assertTrue(all("python.exe" not in command.lower() for command in commands), commands)
            self.assertTrue(any("WindowStyle=1" in command for command in commands), commands)
            self.assertTrue(any("WindowStyle=7" in command for command in commands), commands)

    def test_repository_has_valid_multisize_branded_icons(self):
        root = Path(__file__).resolve().parent.parent
        png = (root / "images" / "ultron_icon.png").read_bytes()
        ico = (root / "images" / "ultron_icon.ico").read_bytes()
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", png[16:24]), (512, 512))
        reserved, kind, count = struct.unpack("<HHH", ico[:6])
        self.assertEqual((reserved, kind), (0, 1))
        self.assertGreaterEqual(count, 6)
        sizes = set()
        for index in range(count):
            offset = 6 + index * 16
            width, height = ico[offset], ico[offset + 1]
            sizes.add((width or 256, height or 256))
        self.assertTrue({(16, 16), (32, 32), (48, 48), (256, 256)}.issubset(sizes), sizes)

    def test_setup_window_uses_native_branded_icon_on_both_platforms(self):
        with tempfile.TemporaryDirectory(prefix="Ultron Setup Icon ") as temp:
            root = Path(temp)
            images = root / "images"
            images.mkdir()
            windows_icon = images / "ultron_icon.ico"
            linux_icon = images / "ultron_icon.png"
            windows_icon.write_bytes(b"ico")
            linux_icon.write_bytes(b"png")
            window = Mock()
            photo_factory = Mock(return_value=object())
            with patch.object(installer, "ROOT", root), patch.object(installer.os, "name", "nt"):
                retained = installer.set_window_icon(window, photo_factory)
            self.assertIsNone(retained)
            window.iconbitmap.assert_called_once_with(default=str(windows_icon))
            photo_factory.assert_not_called()

            window.reset_mock()
            photo_factory.reset_mock()
            photo = object()
            photo_factory.return_value = photo
            with patch.object(installer, "ROOT", root), patch.object(installer.os, "name", "posix"):
                retained = installer.set_window_icon(window, photo_factory)
            self.assertIs(retained, photo)
            photo_factory.assert_called_once_with(file=str(linux_icon))
            window.iconphoto.assert_called_once_with(True, photo)

    def test_install_sequence_uses_runtime_requirements_and_preserves_cli_setup(self):
        engine = installer.InstallerEngine(Mock(), Mock())
        engine._run = Mock()
        engine.create_shortcuts = Mock()
        with tempfile.TemporaryDirectory(prefix="ultron installer ") as temp:
            python = Path(temp) / "python"
            python.write_text("", encoding="utf-8")
            with patch.object(installer, "venv_python", return_value=python):
                engine.install()
        commands = [call.args[0] for call in engine._run.call_args_list]
        self.assertTrue(any("requirements.txt" in " ".join(command) for command in commands))
        self.assertTrue(any(command[-1] == "setup" for command in commands))
        self.assertTrue(any(command[-1] == "doctor" for command in commands))
        self.assertTrue(any(command[-2:] == ["start", "--check"] for command in commands))
        engine.create_shortcuts.assert_called_once_with()


class TestSetupProgressUI(unittest.TestCase):
    def test_setup_has_top_live_status_and_no_secret_logging(self):
        source = Path(installer.__file__).read_text(encoding="utf-8")
        self.assertIn("self.status_var", source)
        self.assertIn("Installing Ultron runtime packages", source)
        self.assertIn("secret values were not logged", source)
        self.assertNotIn("self.log(values", source)


class TestPlatformEntryScripts(unittest.TestCase):
    def test_windows_and_ubuntu_setup_are_double_click_entrypoints(self):
        root = Path(__file__).resolve().parent.parent
        windows = (root / "SETUP_ULTRON_WINDOWS.bat").read_text(encoding="utf-8")
        ubuntu = (root / "SETUP_ULTRON_UBUNTU.sh").read_text(encoding="utf-8")
        self.assertIn("-m backend.app.installer", windows)
        self.assertIn("-m backend.app.installer", ubuntu)
        self.assertNotIn("npm run dev", windows + ubuntu)

    def test_daily_scripts_use_canonical_cli_launcher(self):
        root = Path(__file__).resolve().parent.parent
        windows = (root / "start_ultron.bat").read_text(encoding="utf-8")
        ubuntu = (root / "start_ultron.sh").read_text(encoding="utf-8")
        self.assertIn("backend.app.cli start", windows)
        self.assertIn("backend.app.cli start", ubuntu)
        self.assertNotIn("npm run dev", windows + ubuntu)
        self.assertNotIn("taskkill /f /im python.exe", windows.lower())


class TestDesktopStopCommand(unittest.TestCase):
    def test_zombie_launcher_is_reported_as_cleanly_stopped(self):
        with tempfile.TemporaryDirectory(prefix="ultron stop home ") as temp:
            home = Path(temp).resolve()
            lock_id = hashlib.sha256(str(home).encode("utf-8")).hexdigest()[:16]
            lock_path = Path(tempfile.gettempdir()) / f"ultron-launcher-{lock_id}.lock"
            stop_path = Path(tempfile.gettempdir()) / f"ultron-stop-{lock_id}.request"
            lock_path.write_text("12345", encoding="utf-8")
            process = Mock()
            process.create_time.return_value = 100.0
            process.cmdline.return_value = ["python", "-m", "backend.app.cli", "start"]
            process.is_running.return_value = True
            process.status.return_value = psutil.STATUS_ZOMBIE
            try:
                with patch.object(cli, "APPLICATION_HOME", home), patch.object(
                    cli.psutil, "Process", return_value=process
                ):
                    result = CliRunner().invoke(cli.main, ["stop"])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertIn("stopped cleanly", result.output)
            finally:
                lock_path.unlink(missing_ok=True)
                stop_path.unlink(missing_ok=True)


class TestPrebuiltManifest(unittest.TestCase):
    def test_repository_prebuilt_manifest_matches_current_frontend_source(self):
        root = Path(__file__).resolve().parent.parent
        prebuilt = root / "frontend" / "prebuilt"
        metadata = json.loads((prebuilt / "build-meta.json").read_text(encoding="utf-8"))
        from launcher import ServiceLauncher

        self.assertEqual(metadata["source_digest"], ServiceLauncher._frontend_digest(root / "frontend"))
        self.assertEqual(metadata["api_url"], "http://127.0.0.1:8000")
        self.assertIn("index.html", metadata["files"])


if __name__ == "__main__":
    unittest.main()
