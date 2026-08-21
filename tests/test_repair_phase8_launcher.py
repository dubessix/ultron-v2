"""Phase 8 regressions: loopback production launcher and service lifecycle."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

from backend.app.cli import check_port_availability as cli_check_port_availability
from backend.app.static_server import create_server
from launcher import LauncherError, ServiceLauncher


ROOT = Path(__file__).resolve().parent.parent


def _layout(source_checkout: bool = True):
    root = Path(tempfile.mkdtemp(prefix="ultron_phase8_launcher_"))
    assets = root / "assets"
    home = root / "home"
    frontend = assets / "frontend"
    (frontend / "src").mkdir(parents=True)
    (frontend / "package.json").write_text('{"scripts":{"build":"vite build"}}', encoding="utf-8")
    (frontend / "package-lock.json").write_text('{"lockfileVersion":3}', encoding="utf-8")
    (frontend / "src" / "App.jsx").write_text("export default function App(){}", encoding="utf-8")
    (assets / "config.yaml").write_text(
        "server:\n  host: '127.0.0.1'\n  backend_port: 8000\n  frontend_port: 5173\n",
        encoding="utf-8",
    )
    if source_checkout:
        (assets / "setup.py").write_text("# source marker", encoding="utf-8")
    launcher = ServiceLauncher(
        asset_root=assets,
        application_home=home,
        config_path=assets / "config.yaml",
        sleep_fn=lambda _seconds: None,
    )
    return root, launcher


class FakeProcess:
    def __init__(self, return_code=None, pid=424242):
        self.return_code = return_code
        self.pid = pid
        self.stdout = None
        self.terminated = False

    def poll(self):
        return self.return_code

    def terminate(self):
        self.terminated = True
        self.return_code = 0

    def wait(self, timeout=None):
        self.return_code = 0 if self.return_code is None else self.return_code
        return self.return_code


class TestLoopbackConfiguration(unittest.TestCase):
    def test_vite_dev_and_preview_are_loopback_only(self):
        source = (ROOT / "frontend" / "vite.config.js").read_text(encoding="utf-8")
        self.assertNotIn("host: true", source)
        self.assertNotIn("allowedHosts: true", source)
        self.assertIn("127.0.0.1", source)

    def test_unsafe_configured_bind_host_is_rejected(self):
        root, launcher = _layout()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        launcher.config_path.write_text(
            "server:\n  host: '0.0.0.0'\n  backend_port: 8000\n  frontend_port: 5173\n",
            encoding="utf-8",
        )
        with self.assertRaises(LauncherError):
            ServiceLauncher(
                asset_root=launcher.asset_root,
                application_home=launcher.application_home,
                config_path=launcher.config_path,
            )

    def test_daily_launcher_uses_static_production_server_not_vite_dev(self):
        source = (ROOT / "launcher.py").read_text(encoding="utf-8")
        self.assertNotIn('["npm", "run", "dev"]', source)
        self.assertIn("backend.app.static_server", source)
        self.assertIn('"--host",\n            self.host', source)

    def test_frontend_digest_is_stable_across_lf_and_windows_crlf_checkout(self):
        with tempfile.TemporaryDirectory(prefix="ultron_digest_") as temp:
            root = Path(temp)
            linux = root / "linux"
            windows = root / "windows"
            for folder, newline in ((linux, "\n"), (windows, "\r\n")):
                (folder / "src").mkdir(parents=True)
                (folder / "src" / "App.jsx").write_bytes(
                    f"export default function App() {{{newline}  return null{newline}}}{newline}".encode("utf-8")
                )
                (folder / "package.json").write_bytes(
                    f'{{{newline}  "name": "ultron"{newline}}}{newline}'.encode("utf-8")
                )
            self.assertEqual(
                ServiceLauncher._frontend_digest(linux),
                ServiceLauncher._frontend_digest(windows),
            )

    def test_fastapi_uses_lifespan_not_deprecated_event_hooks(self):
        source = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("@app.on_event", source)
        from backend.app.main import app
        self.assertIn("lifespan=application_lifespan", source)
        self.assertTrue(callable(app.router.lifespan_context))


class TestFrontendProductionServer(unittest.TestCase):
    def test_health_static_index_and_spa_fallback(self):
        with tempfile.TemporaryDirectory(prefix="ultron_static_") as temp:
            root = Path(temp)
            (root / "index.html").write_text("<h1>Ultron Ready</h1>", encoding="utf-8")
            server = create_server(root, "127.0.0.1", 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address[:2]
            try:
                with urllib.request.urlopen(f"http://{host}:{port}/healthz", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(payload["status"], "healthy")
                with urllib.request.urlopen(f"http://{host}:{port}/some/spa/route", timeout=2) as response:
                    page = response.read().decode("utf-8")
                self.assertIn("Ultron Ready", page)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
            self.assertTrue(ServiceLauncher.check_port_availability(port, "127.0.0.1"))
            self.assertTrue(cli_check_port_availability(port, "127.0.0.1"))

    def test_non_loopback_bind_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="ultron_static_") as temp:
            root = Path(temp)
            (root / "index.html").write_text("ok", encoding="utf-8")
            with self.assertRaises(ValueError):
                create_server(root, "0.0.0.0", 5173)


class TestLauncherHealthAndLifecycle(unittest.TestCase):
    def _ready_launcher(self):
        root, launcher = _layout()
        launcher.acquire_instance_lock = Mock(return_value=True)
        launcher.release_instance_lock = Mock()
        launcher.preflight_port_check = Mock(return_value=True)
        launcher.prepare_frontend = Mock(return_value=True)
        launcher.install_signal_handlers = Mock()
        launcher.backend_process = FakeProcess()
        launcher.frontend_process = FakeProcess(pid=424243)
        launcher.start_services = Mock()
        launcher.terminate_process_tree = Mock(return_value=True)
        return root, launcher

    def test_signal_during_frontend_preparation_stops_without_starting_services(self):
        root, launcher = self._ready_launcher()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))

        def interrupted_prepare():
            launcher.shutdown_handler(signal.SIGTERM, None)
            return False

        launcher.prepare_frontend = interrupted_prepare
        with patch("launcher.webbrowser.open") as browser:
            result = launcher.run()
        self.assertEqual(result, 0)
        launcher.start_services.assert_not_called()
        browser.assert_not_called()

    def test_source_frontend_server_starts_from_importable_asset_root(self):
        root, launcher = _layout()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        backend = FakeProcess()
        frontend = FakeProcess(pid=424243)
        launcher._start_process = Mock(side_effect=[backend, frontend])
        launcher.start_services()
        self.assertEqual(launcher._start_process.call_args_list[0].args[1], launcher.asset_root)
        self.assertEqual(launcher._start_process.call_args_list[1].args[1], launcher.asset_root)
        self.assertIn("backend.app.static_server", launcher._start_process.call_args_list[1].args[0])

    def test_backend_health_failure_never_opens_browser_and_stops_children(self):
        root, launcher = self._ready_launcher()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        launcher.wait_for_backend_health = Mock(return_value=False)
        launcher.wait_for_frontend_health = Mock(return_value=True)
        with patch("launcher.webbrowser.open") as browser:
            result = launcher.run()
        self.assertEqual(result, 1)
        browser.assert_not_called()
        self.assertEqual(launcher.terminate_process_tree.call_count, 3)

    def test_frontend_health_failure_never_opens_browser_and_stops_children(self):
        root, launcher = self._ready_launcher()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        launcher.wait_for_backend_health = Mock(return_value=True)
        launcher.wait_for_frontend_health = Mock(return_value=False)
        with patch("launcher.webbrowser.open") as browser:
            result = launcher.run()
        self.assertEqual(result, 1)
        browser.assert_not_called()
        self.assertEqual(launcher.terminate_process_tree.call_count, 3)

    def test_signal_during_startup_is_clean_not_a_false_health_failure(self):
        root, launcher = self._ready_launcher()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        launcher.wait_for_backend_health = Mock(return_value=True)

        def interrupted_frontend_gate():
            launcher.shutdown_handler(signal.SIGTERM, None)
            return False

        launcher.wait_for_frontend_health = interrupted_frontend_gate
        with patch("launcher.webbrowser.open") as browser:
            result = launcher.run()
        self.assertEqual(result, 0)
        browser.assert_not_called()
        self.assertEqual(launcher.terminate_process_tree.call_count, 3)

    def test_browser_opens_only_after_both_health_gates(self):
        root, launcher = self._ready_launcher()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        launcher.wait_for_backend_health = Mock(return_value=True)
        launcher.wait_for_frontend_health = Mock(return_value=True)
        launcher.monitor_services = Mock(return_value=0)
        with patch("launcher.webbrowser.open", return_value=True) as browser:
            result = launcher.run()
        self.assertEqual(result, 0)
        browser.assert_called_once_with("http://127.0.0.1:5173")

    def test_cloud_mode_skips_real_browser_only_after_both_health_gates(self):
        root, launcher = self._ready_launcher()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        launcher.wait_for_backend_health = Mock(return_value=True)
        launcher.wait_for_frontend_health = Mock(return_value=True)
        launcher.monitor_services = Mock(return_value=0)
        with patch.dict(os.environ, {"ULTRON_NO_BROWSER": "1"}), patch(
            "launcher.webbrowser.open"
        ) as browser:
            result = launcher.run()
        self.assertEqual(result, 0)
        browser.assert_not_called()
        launcher.monitor_services.assert_called_once_with()

    def test_unexpected_child_exit_returns_failure_and_stops_sibling(self):
        root, launcher = self._ready_launcher()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        launcher.wait_for_backend_health = Mock(return_value=True)
        launcher.wait_for_frontend_health = Mock(return_value=True)
        launcher.backend_process.return_code = 7
        with patch("launcher.webbrowser.open", return_value=True):
            result = launcher.run()
        self.assertEqual(result, 1)
        self.assertEqual(launcher.terminate_process_tree.call_count, 3)

    def test_duplicate_launcher_lock_is_rejected(self):
        root, first = _layout()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        second = ServiceLauncher(
            asset_root=first.asset_root,
            application_home=first.application_home,
            config_path=first.config_path,
        )
        self.assertTrue(first.acquire_instance_lock())
        try:
            self.assertNotEqual(first.mutex_path, first.lock_path)
            self.assertEqual(int(first.lock_path.read_text(encoding="utf-8")), os.getpid())
            self.assertFalse(second.acquire_instance_lock())
        finally:
            first.release_instance_lock()
        self.assertTrue(second.acquire_instance_lock())
        second.release_instance_lock()

    def test_desktop_stop_request_ends_monitor_cleanly(self):
        root, launcher = self._ready_launcher()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        launcher.stop_request_path.write_text("stop", encoding="utf-8")
        result = launcher.monitor_services(poll_interval=0)
        self.assertEqual(result, 0)
        self.assertFalse(launcher.stop_request_path.exists())

    def test_process_tree_escalates_after_bounded_grace_timeout(self):
        root, launcher = _layout()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        process = Mock()
        process.pid = 98765
        process.poll.side_effect = [None, 0]
        process.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="child", timeout=0.01),
            0,
        ]
        with patch("launcher.platform.system", return_value="Linux"), patch(
            "launcher.os.getpgid", return_value=98765, create=True
        ), patch("launcher.os.killpg", create=True) as killpg, patch(
            "launcher.signal.SIGKILL", 9, create=True
        ):
            stopped = launcher.terminate_process_tree(process, grace_seconds=0.01)
        self.assertTrue(stopped)
        self.assertEqual(
            [call.args[1] for call in killpg.call_args_list],
            [signal.SIGTERM, 9],
        )

    def test_verified_prebuilt_frontend_avoids_node_and_npm(self):
        root, launcher = _layout()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        prebuilt = launcher.source_frontend / "prebuilt"
        prebuilt.mkdir()
        (prebuilt / "index.html").write_text("<div id='root'></div>", encoding="utf-8")
        source_digest = launcher._frontend_digest(launcher.source_frontend)
        index_hash = hashlib.sha256((prebuilt / "index.html").read_bytes()).hexdigest()
        (prebuilt / "build-meta.json").write_text(json.dumps({
            "source_digest": source_digest,
            "api_url": "http://127.0.0.1:8000",
            "files": {"index.html": index_hash},
        }), encoding="utf-8")
        launcher._node_build_supported = Mock(return_value=False)
        launcher._run_npm = Mock(return_value=True)
        self.assertTrue(launcher.prepare_frontend())
        self.assertTrue((launcher.frontend_dist / "index.html").is_file())
        launcher._node_build_supported.assert_not_called()
        launcher._run_npm.assert_not_called()

    def test_frontend_prepare_rejects_unsupported_node_before_npm(self):
        root, launcher = _layout()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        launcher._node_build_supported = Mock(return_value=False)
        launcher._run_npm = Mock(return_value=True)
        self.assertFalse(launcher.prepare_frontend())
        launcher._run_npm.assert_not_called()

    def test_frontend_prepare_runs_ci_and_build_once_then_uses_fingerprint(self):
        root, launcher = _layout()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        calls = []
        build_environments = []

        def fake_npm(arguments, timeout, env=None):
            calls.append(tuple(arguments))
            if arguments[:2] == ["run", "build"]:
                build_environments.append(dict(env or {}))
            if arguments[0] == "ci":
                (launcher.frontend_dir / "node_modules").mkdir(exist_ok=True)
            if arguments[:2] == ["run", "build"]:
                launcher.frontend_dist.mkdir(exist_ok=True)
                (launcher.frontend_dist / "index.html").write_text("built", encoding="utf-8")
            return True

        launcher._run_npm = fake_npm
        self.assertTrue(launcher.prepare_frontend())
        self.assertEqual(calls, [("ci", "--no-audit", "--no-fund"), ("run", "build")])
        self.assertEqual(build_environments[0]["VITE_API_URL"], "http://127.0.0.1:8000")
        self.assertTrue(launcher.prepare_frontend())
        self.assertEqual(len(calls), 2)

        (launcher.frontend_dir / "src" / "App.jsx").write_text("// changed", encoding="utf-8")
        self.assertTrue(launcher.prepare_frontend())
        self.assertEqual(calls[-1], ("run", "build"))
        self.assertEqual(calls.count(("ci", "--no-audit", "--no-fund")), 1)


if __name__ == "__main__":
    unittest.main()
