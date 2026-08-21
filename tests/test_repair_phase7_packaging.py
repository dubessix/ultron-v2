"""Phase 7 regressions: wheel resources and clean installed CLI behavior."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class TestPhase7WheelInstall(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="ultron_phase7_wheel_"))
        cls.source_dir = cls.temp_dir / "source"
        cls.wheel_dir = cls.temp_dir / "wheel"
        cls.install_dir = cls.temp_dir / "install"
        cls.home_dir = cls.temp_dir / "home"
        shutil.copytree(
            ROOT,
            cls.source_dir,
            ignore=shutil.ignore_patterns(
                ".git",
                ".venv",
                "node_modules",
                "dist",
                "build",
                "*.egg-info",
                "__pycache__",
                ".pytest_cache",
                "data",
            ),
        )
        cls.wheel_dir.mkdir()
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--no-build-isolation",
                str(cls.source_dir),
                "-w",
                str(cls.wheel_dir),
            ],
            cwd=str(cls.temp_dir),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=120,
        )
        wheels = list(cls.wheel_dir.glob("ultron-*.whl"))
        if len(wheels) != 1:
            raise AssertionError(f"Expected one wheel, found: {wheels}")
        cls.wheel = wheels[0]
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--target",
                str(cls.install_dir),
                str(cls.wheel),
            ],
            cwd=str(cls.temp_dir),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=120,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    @classmethod
    def _installed_command(cls, *arguments: str) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        for key in (
            "ULTRON_TEST_MODE",
            "ULTRON_TEST_ROOT",
            "ULTRON_TEST_DB",
            "ULTRON_TEST_CACHE",
        ):
            env.pop(key, None)
        env["PYTHONPATH"] = str(cls.install_dir)
        env["ULTRON_HOME"] = str(cls.home_dir)
        return subprocess.run(
            [sys.executable, "-m", "backend.app.cli", *arguments],
            cwd=str(cls.temp_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
        )

    def test_wheel_contains_runtime_resources(self):
        with zipfile.ZipFile(self.wheel) as archive:
            names = set(archive.namelist())
        required_exact = {
            "backend/app/static_server.py",
            "backend/app/personalities/ultron.md",
            "backend/app/personalities/zora.md",
            "backend/app/skills/coding_agent.md",
            "backend/app/skills/multi_file_task.md",
            "backend/app/skills/project_context.md",
        }
        self.assertTrue(required_exact.issubset(names), required_exact - names)
        required_suffixes = {
            "share/ultron/config.yaml",
            "share/ultron/launcher.py",
            "share/ultron/.env.example",
            "share/ultron/frontend/package.json",
            "share/ultron/frontend/package-lock.json",
            "share/ultron/frontend/src/App.jsx",
            "share/ultron/frontend/src/index.css",
            "share/ultron/frontend/prebuilt/index.html",
            "share/ultron/frontend/prebuilt/build-meta.json",
            "share/ultron/SETUP_ULTRON_WINDOWS.bat",
            "share/ultron/SETUP_ULTRON_UBUNTU.sh",
            "share/ultron/start_ultron.bat",
            "share/ultron/start_ultron.sh",
            "share/ultron/images/ultron_icon.ico",
            "share/ultron/images/ultron_icon.png",
        }
        for suffix in required_suffixes:
            self.assertTrue(
                any(name.endswith(suffix) for name in names),
                f"Wheel missing {suffix}",
            )

    def test_wheel_declares_python_310_or_newer(self):
        with zipfile.ZipFile(self.wheel) as archive:
            metadata_name = next(
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            )
            metadata = archive.read(metadata_name).decode("utf-8")
        self.assertIn("Requires-Python: >=3.10", metadata)

    def test_clean_install_loads_real_config_prompts_and_skills(self):
        env = os.environ.copy()
        for key in (
            "ULTRON_TEST_MODE",
            "ULTRON_TEST_ROOT",
            "ULTRON_TEST_DB",
            "ULTRON_TEST_CACHE",
        ):
            env.pop(key, None)
        env["PYTHONPATH"] = str(self.install_dir)
        env["ULTRON_HOME"] = str(self.home_dir)
        script = """
import os
import runpy
from pathlib import Path
from backend.app.brain.model_config import validate_model_config
from backend.app.install_paths import APPLICATION_HOME, ASSET_ROOT
from backend.app.installer import ENV_FILE, SOURCE_MODE
from backend.app.main import app
from backend.app.personalities.base_personality import UltronPersonality
from backend.app.runtime_paths import PRODUCTION_DATA_ROOT
from backend.app.skills.loader import load_coding_skills
status = validate_model_config()
prompt = UltronPersonality().load_prompt_from_disk()
skills = load_coding_skills()
expected_home = Path(os.environ['ULTRON_HOME']).resolve()
assert status['valid'], status
assert len(prompt) > 200, len(prompt)
assert len(skills) > 200, len(skills)
assert APPLICATION_HOME == expected_home, (APPLICATION_HOME, expected_home)
assert PRODUCTION_DATA_ROOT == expected_home / 'data', PRODUCTION_DATA_ROOT
assert SOURCE_MODE is False
assert ENV_FILE == expected_home / '.env'
assert (ASSET_ROOT / 'frontend' / 'package.json').is_file(), ASSET_ROOT
launcher_scope = runpy.run_path(str(ASSET_ROOT / 'launcher.py'), run_name='ultron_packaging_check')
assert 'ServiceLauncher' in launcher_scope
assert app.title == 'ULTRON CORE ENGINE API', app.title
print('installed_resources_ok')
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(self.temp_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("installed_resources_ok", result.stdout)

    def test_clean_installed_cli_setup_doctor_and_start_check(self):
        version = self._installed_command("version")
        self.assertEqual(version.returncode, 0, version.stdout)
        self.assertIn("Version: 1.0.0", version.stdout)

        setup = self._installed_command("setup")
        self.assertEqual(setup.returncode, 0, setup.stdout)
        user_config = self.home_dir / "config.yaml"
        user_env = self.home_dir / ".env"
        self.assertTrue(user_config.is_file())
        self.assertTrue(user_env.is_file())

        # A later repair/setup pass must never erase personal config or live keys.
        user_config.write_text(user_config.read_text(encoding="utf-8") + "\n# owner-edit\n", encoding="utf-8")
        user_env.write_text("GROQ_API_KEY_1=owner-secret-placeholder\n", encoding="utf-8")
        forced = self._installed_command("setup", "--force")
        self.assertEqual(forced.returncode, 0, forced.stdout)
        self.assertIn("# owner-edit", user_config.read_text(encoding="utf-8"))
        self.assertEqual(
            user_env.read_text(encoding="utf-8"),
            "GROQ_API_KEY_1=owner-secret-placeholder\n",
        )

        doctor = self._installed_command("doctor")
        self.assertEqual(doctor.returncode, 0, doctor.stdout)
        self.assertNotIn("config.yaml: Missing", doctor.stdout)
        self.assertNotIn("All systems green", doctor.stdout)

        valid_config = user_config.read_text(encoding="utf-8")
        user_config.write_text("server: [malformed", encoding="utf-8")
        malformed = self._installed_command("doctor")
        self.assertNotEqual(malformed.returncode, 0, malformed.stdout)
        self.assertIn("malformed", malformed.stdout.lower())
        user_config.write_text(valid_config, encoding="utf-8")

        start_check = self._installed_command("start", "--check")
        self.assertEqual(start_check.returncode, 0, start_check.stdout)
        self.assertIn("installation assets verified", start_check.stdout.lower())


if __name__ == "__main__":
    unittest.main()
