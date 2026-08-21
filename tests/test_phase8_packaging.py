"""
Phase 8 regression — packaging.

The wheel must actually contain the backend code (find_packages() previously
returned an empty list -> empty wheel -> `ultron` CLI failed with
ModuleNotFoundError: No module named 'backend'). We assert the package discovery
used by setup.py finds the real code, and that the entry-point module is present.
"""

import unittest
from pathlib import Path

from setuptools import find_namespace_packages

ROOT = Path(__file__).resolve().parent.parent


class TestPackaging(unittest.TestCase):

    def test_find_namespace_packages_discovers_backend(self):
        # Chdir-independent: run find_namespace_packages from the repo root.
        import os
        old = os.getcwd()
        os.chdir(ROOT)
        try:
            pkgs = find_namespace_packages(include=["backend*"])
        finally:
            os.chdir(old)
        self.assertIn("backend.app.core", pkgs)
        self.assertIn("backend.app.tools", pkgs)
        self.assertIn("backend.app", pkgs)

    def test_requirements_list_edge_tts_dependency(self):
        """setup.py reads this canonical dependency list for wheel metadata."""
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        setup_text = (ROOT / "setup.py").read_text(encoding="utf-8")
        self.assertIn("edge-tts", requirements)
        self.assertIn("install_requires=_requirements()", setup_text)

    def test_cli_entry_point_module_exists(self):
        self.assertTrue((ROOT / "backend" / "app" / "cli.py").exists())

    def test_cli_exposes_main_entry(self):
        import backend.app.cli as cli
        self.assertTrue(hasattr(cli, "main"))


class TestLauncherHealthGate(unittest.TestCase):

    def test_health_gate_returns_true_when_backend_ready(self):
        from unittest.mock import Mock, patch
        from launcher import ServiceLauncher

        class FakeResp:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self):
                return b'{"status":"healthy","system_metrics":{},"models":{}}'

        launcher = ServiceLauncher()
        launcher.backend_process = Mock()
        launcher.backend_process.poll.return_value = None
        with patch("urllib.request.urlopen", return_value=FakeResp()):
            ok = launcher.wait_for_backend_health(timeout_sec=3.0)
        self.assertTrue(ok)

    def test_health_gate_rejects_unrelated_http_200(self):
        from unittest.mock import Mock, patch
        from launcher import ServiceLauncher

        class UnrelatedResponse:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return b'{"status":"ok","service":"something-else"}'

        launcher = ServiceLauncher(sleep_fn=lambda _seconds: None)
        launcher.backend_process = Mock()
        launcher.backend_process.poll.return_value = None
        with patch("urllib.request.urlopen", return_value=UnrelatedResponse()):
            ok = launcher.wait_for_backend_health(timeout_sec=0.01)
        self.assertFalse(ok)

    def test_health_gate_returns_false_on_timeout(self):
        from unittest.mock import Mock, patch
        from launcher import ServiceLauncher

        launcher = ServiceLauncher(sleep_fn=lambda _seconds: None)
        launcher.backend_process = Mock()
        launcher.backend_process.poll.return_value = None
        with patch("urllib.request.urlopen", side_effect=OSError("refused")):
            ok = launcher.wait_for_backend_health(timeout_sec=0.01)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
