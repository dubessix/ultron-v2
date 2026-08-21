"""Reliable localhost-only launcher for Ultron's backend and production frontend."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import webbrowser
from pathlib import Path
from threading import Thread
from typing import Callable, Optional

import yaml


LOOPBACK_HOST = "127.0.0.1"
DEFAULT_BACKEND_PORT = 8000
DEFAULT_FRONTEND_PORT = 5173
_FRONTEND_TEXT_SUFFIXES = {
    ".css", ".html", ".js", ".json", ".jsx", ".md", ".mjs", ".cjs",
    ".ts", ".tsx", ".txt", ".yaml", ".yml",
}

# Compact terminal palette. The launcher colours only ordinary text and box
# characters, so it stays readable without custom fonts or external binaries.
TERMINAL_EMERALD = "38;2;52;211;153"
TERMINAL_CYAN = "38;2;56;189;248"
TERMINAL_TEAL = "38;2;94;234;212"
TERMINAL_WHITE = "38;2;226;232;240"
TERMINAL_DIM = "38;2;100;116;124"


class LauncherError(RuntimeError):
    pass


class ServiceLauncher:
    def __init__(
        self,
        asset_root: Optional[Path] = None,
        application_home: Optional[Path] = None,
        config_path: Optional[Path] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.asset_root = Path(asset_root or Path(__file__).resolve().parent).resolve()
        configured_home = os.getenv("ULTRON_HOME", "").strip()
        if application_home is not None:
            self.application_home = Path(application_home).expanduser().resolve()
        elif configured_home:
            self.application_home = Path(configured_home).expanduser().resolve()
        elif (self.asset_root / "setup.py").is_file():
            self.application_home = self.asset_root
        else:
            self.application_home = (Path.home() / ".ultron").resolve()

        configured_config = os.getenv("ULTRON_CONFIG", "").strip()
        if config_path is not None:
            self.config_path = Path(config_path).expanduser().resolve()
        elif configured_config:
            self.config_path = Path(configured_config).expanduser().resolve()
        elif (self.application_home / "config.yaml").is_file():
            self.config_path = self.application_home / "config.yaml"
        else:
            self.config_path = self.asset_root / "config.yaml"

        config = self._load_config()
        self.config = config
        self.version = str(config.get("ultron", {}).get("version", "unknown"))
        self.launch_started_at: Optional[float] = None
        server = config.get("server", {}) or {}
        configured_host = str(server.get("host", LOOPBACK_HOST)).strip().lower()
        if configured_host not in {"127.0.0.1", "localhost", "::1"}:
            raise LauncherError("server.host must be loopback-only (127.0.0.1, localhost, or ::1).")
        self.backend_port = self._valid_port(server.get("backend_port"), DEFAULT_BACKEND_PORT)
        self.frontend_port = self._valid_port(server.get("frontend_port"), DEFAULT_FRONTEND_PORT)
        if self.backend_port == self.frontend_port:
            raise LauncherError("Backend and frontend ports must be different.")
        try:
            configured_timeout = float(server.get("startup_timeout_seconds", 45.0))
        except (TypeError, ValueError) as exc:
            raise LauncherError("server.startup_timeout_seconds must be numeric.") from exc
        self.startup_timeout = max(5.0, min(configured_timeout, 180.0))
        self.host = LOOPBACK_HOST
        self.sleep = sleep_fn

        self.source_frontend = self.asset_root / "frontend"
        self.frontend_dir = (
            self.source_frontend
            if (self.asset_root / "setup.py").is_file()
            else self.application_home / "frontend"
        )
        self.frontend_dist = self.frontend_dir / "dist"

        configured_launch_log = os.getenv("ULTRON_LAUNCH_LOG", "").strip()
        self.launch_log_path = (
            Path(configured_launch_log).expanduser().resolve()
            if configured_launch_log
            else None
        )

        lock_id = hashlib.sha256(str(self.application_home).encode("utf-8")).hexdigest()[:16]
        self.lock_path = Path(tempfile.gettempdir()) / f"ultron-launcher-{lock_id}.lock"
        self.mutex_path = Path(tempfile.gettempdir()) / f"ultron-launcher-{lock_id}.mutex"
        self.stop_request_path = Path(tempfile.gettempdir()) / f"ultron-stop-{lock_id}.request"
        self._lock_handle = None
        self.preparation_process = None
        self.backend_process = None
        self.frontend_process = None
        self._output_threads: list[Thread] = []
        self.is_shutting_down = False
        self._requested_exit_code = 0

    @staticmethod
    def _valid_port(value, default: int) -> int:
        try:
            port = int(value)
        except (TypeError, ValueError):
            port = default
        if not 1 <= port <= 65535:
            raise LauncherError(f"Invalid configured TCP port: {port}")
        return port

    def _load_config(self) -> dict:
        if not self.config_path.is_file():
            raise LauncherError(f"Configuration file is missing: {self.config_path}")
        try:
            config = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise LauncherError(f"Configuration file is invalid: {exc}") from exc
        if not isinstance(config, dict) or not isinstance(config.get("server"), dict):
            raise LauncherError("Configuration must contain a 'server' mapping.")
        return config

    def _append_launch_log(self, text: str) -> None:
        if self.launch_log_path is None:
            return
        try:
            self.launch_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.launch_log_path.open("a", encoding="utf-8") as handle:
                handle.write(text.rstrip("\n") + "\n")
        except OSError:
            # Console startup must continue even when optional diagnostic logging
            # is unavailable; the visible terminal still contains the error.
            pass

    def console(self, text: str = "", color_code: Optional[str] = None) -> None:
        rendered = f"\033[1;{color_code}m{text}\033[0m" if color_code else text
        print(rendered, flush=True)
        self._append_launch_log(text)

    def console_segments(self, segments: list[tuple[str, Optional[str]]]) -> None:
        plain = "".join(text for text, _color in segments)
        rendered = "".join(
            f"\033[1;{color}m{text}\033[0m" if color else text
            for text, color in segments
        )
        print(rendered, flush=True)
        self._append_launch_log(plain)

    def log(self, service: str, message: str, color_code: str = "32") -> None:
        plain = f"[{service}] {message}"
        print(f"\033[1;{color_code}m[{service}]\033[0m {message}", flush=True)
        self._append_launch_log(plain)

    @staticmethod
    def _unicode_box_supported() -> bool:
        try:
            "╭─╮│╰╯•".encode(sys.stdout.encoding or "utf-8")
            return True
        except (LookupError, UnicodeEncodeError):
            return False

    def render_startup_banner(self) -> None:
        if platform.system() == "Windows":
            # Enables virtual-terminal colour processing in current Windows
            # consoles without requiring a third-party dependency.
            os.system("")
        major_version = self.version.split(".", 1)[0]
        box_inner = 64
        name_plain = f"  ULTRON  v{major_version}"
        subtitle_left = "  Personal AI Assistant"
        subtitle_gap = "  •  "
        subtitle_right = "Local Startup Console"
        subtitle_plain = subtitle_left + subtitle_gap + subtitle_right

        if self._unicode_box_supported():
            self.console("╭" + "─" * box_inner + "╮", TERMINAL_EMERALD)
            self.console_segments([
                ("│  ", TERMINAL_DIM),
                ("ULTRON", TERMINAL_EMERALD),
                ("  ", None),
                (f"v{major_version}", TERMINAL_CYAN),
                (" " * (box_inner - len(name_plain)), None),
                ("│", TERMINAL_DIM),
            ])
            self.console_segments([
                ("│", TERMINAL_DIM),
                (subtitle_left, TERMINAL_WHITE),
                (subtitle_gap, TERMINAL_DIM),
                (subtitle_right, TERMINAL_TEAL),
                (" " * (box_inner - len(subtitle_plain)), None),
                ("│", TERMINAL_DIM),
            ])
            self.console("╰" + "─" * box_inner + "╯", TERMINAL_EMERALD)
        else:
            self.console("+" + "-" * box_inner + "+", "32")
            self.console(f"|{name_plain:<{box_inner}}|", "32")
            fallback_subtitle = subtitle_plain.replace("•", "|")
            self.console(f"|{fallback_subtitle:<{box_inner}}|", "36")
            self.console("+" + "-" * box_inner + "+", "32")

    def progress(self, step: int, label: str, status: str, color_code: str = "36") -> None:
        dots = "." * max(2, 42 - len(label))
        self.console(f"[{step}/5] {label} {dots} {status}", color_code)

    @staticmethod
    def _is_real_key(value: str) -> bool:
        lowered = value.strip().lower()
        if not lowered:
            return False
        markers = (
            "placeholder", "changeme", "change_me", "replace_me", "your_groq",
            "your_gemini", "your_nvidia", "your_api", "api_key_here",
        )
        return not any(marker in lowered for marker in markers)

    def configured_ai_key_slots(self) -> int:
        values = dict(os.environ)
        env_path = self.application_home / ".env"
        try:
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, value = line.split("=", 1)
                values.setdefault(name.strip(), value.strip())
        except OSError:
            pass
        names = [
            f"{prefix}_API_KEY_{index}"
            for prefix in ("GROQ", "GEMINI", "NVIDIA")
            for index in range(1, 5)
        ]
        return sum(1 for name in names if self._is_real_key(values.get(name, "")))

    def render_ready(self, url: str, browser_opened: bool, browser_disabled: bool) -> None:
        elapsed = max(0.0, time.monotonic() - (self.launch_started_at or time.monotonic()))
        runtime = f"{elapsed:.1f}s" if elapsed < 60 else f"{int(elapsed // 60)}m {int(elapsed % 60)}s"
        key_slots = self.configured_ai_key_slots()
        self.console("")
        panel_width = 70
        heading = "─ ULTRON IS ONLINE "
        self.console("╭" + heading + "─" * (panel_width - len(heading)) + "╮", "32")
        self.console(f"│ {f'Dashboard  {url}':<{panel_width - 2}} │", "36")
        self.console(f"│ {f'Startup runtime  {runtime}':<{panel_width - 2}} │", "90")
        self.console(f"│ {'Systems ready. Local services are online.':<{panel_width - 2}} │", "32")
        self.console("╰" + "─" * panel_width + "╯", "32")
        if browser_opened:
            self.console("Browser opened successfully.", "32")
        elif browser_disabled:
            self.console("Browser auto-open was intentionally disabled for this run.", "33")
        else:
            self.console("Browser did not open automatically; use the dashboard URL above.", "33")
        if key_slots == 0:
            self.console(
                "AI Core: LOCAL ONLY — providers not configured; local widgets/tools remain available.",
                "33",
            )
        else:
            self.console(
                f"AI Core: {key_slots} key slot(s) configured; live reachability not checked at startup.",
                "36",
            )
        self.console("[LOCK] Loopback Mode: ON   >_ You are in control.   ULTRON Personal AI", "90")
        self.console("Keep this window open; use Stop Ultron for a graceful stop.", "90")

    def acquire_instance_lock(self) -> bool:
        """Take one cross-platform mutex while keeping launcher PID readable."""
        self.mutex_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.mutex_path, "a+", encoding="utf-8")
        pid_temp = self.lock_path.with_suffix(f".lock.{os.getpid()}.tmp")
        try:
            if platform.system() == "Windows":
                import msvcrt
                handle.seek(0)
                if handle.read(1) == "":
                    handle.write("0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Windows denies other processes access to the byte locked by
            # msvcrt. Keep that mutex in a separate file so Stop Ultron can
            # always read the public PID/control record while the app runs.
            pid_temp.write_text(str(os.getpid()), encoding="utf-8")
            os.replace(pid_temp, self.lock_path)
            self._lock_handle = handle
            self.stop_request_path.unlink(missing_ok=True)
            return True
        except (OSError, BlockingIOError):
            handle.close()
            pid_temp.unlink(missing_ok=True)
            return False

    def release_instance_lock(self) -> None:
        handle = self._lock_handle
        self._lock_handle = None
        if handle is None:
            return
        try:
            if platform.system() == "Windows":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()

    @staticmethod
    def check_port_availability(port: int, host: str = LOOPBACK_HOST) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                if platform.system() == "Windows" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                else:
                    # Permit immediate restart after a clean shutdown leaves only
                    # harmless TCP TIME_WAIT entries; active listeners still fail.
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((host, int(port)))
                return True
            except OSError:
                return False

    def preflight_port_check(self) -> bool:
        ok = True
        for name, port in (
            ("backend", self.backend_port),
            ("frontend", self.frontend_port),
        ):
            if self.check_port_availability(port, self.host):
                self.log("Launcher", f"Loopback port {self.host}:{port} is free for {name}.")
            else:
                self.log(
                    "Launcher",
                    f"Loopback port {self.host}:{port} is already in use for {name}.",
                    "31",
                )
                ok = False
        return ok

    @staticmethod
    def _frontend_files(root: Path):
        excluded = {"node_modules", "dist", "prebuilt", ".vite"}
        for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if any(part in excluded for part in relative.parts):
                continue
            if path.name.startswith(".ultron_"):
                continue
            yield path, relative

    @classmethod
    def _frontend_digest(cls, root: Path) -> str:
        digest = hashlib.sha256()
        for path, relative in cls._frontend_files(root):
            digest.update(relative.as_posix().encode("utf-8"))
            digest.update(b"\0")
            content = path.read_bytes()
            if path.suffix.lower() in _FRONTEND_TEXT_SUFFIXES:
                # Git may check text out as CRLF on Windows. Release signatures
                # must identify the same source on both supported platforms.
                content = content.replace(b"\r\n", b"\n")
            digest.update(content)
            digest.update(b"\0")
        return digest.hexdigest()

    @staticmethod
    def _read_marker(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    @staticmethod
    def _write_marker(path: Path, value: str) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(value + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def _sync_installed_frontend(self) -> bool:
        if not self.source_frontend.is_dir():
            self.log("Launcher", f"Packaged frontend source is missing: {self.source_frontend}", "31")
            return False
        if self.frontend_dir.resolve() == self.source_frontend.resolve():
            return True
        source_digest = self._frontend_digest(self.source_frontend)
        marker = self.frontend_dir / ".ultron_source.sha256"
        if self._read_marker(marker) == source_digest:
            return True
        self.frontend_dir.mkdir(parents=True, exist_ok=True)
        for source, relative in self._frontend_files(self.source_frontend):
            destination = self.frontend_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        self._write_marker(marker, source_digest)
        return True

    def _prepare_from_prebuilt(self, source_digest: str, api_url: str, build_key: str) -> bool:
        """Install release-built frontend assets when they match source and API defaults."""
        prebuilt = self.source_frontend / "prebuilt"
        metadata_path = prebuilt / "build-meta.json"
        if not metadata_path.is_file():
            return False
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("source_digest") != source_digest or metadata.get("api_url") != api_url:
                return False
            files = metadata.get("files") or {}
            if not files or "index.html" not in files:
                return False
            for relative, expected in files.items():
                source = (prebuilt / relative).resolve(strict=True)
                if not source.is_relative_to(prebuilt.resolve()):
                    return False
                if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
                    self.log("Launcher", f"Prebuilt frontend checksum failed: {relative}", "31")
                    return False
            if self.frontend_dist.exists():
                shutil.rmtree(self.frontend_dist)
            self.frontend_dist.mkdir(parents=True, exist_ok=True)
            for relative in files:
                source = prebuilt / relative
                destination = self.frontend_dist / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            self._write_marker(self.frontend_dir / ".ultron_build.sha256", build_key)
            self.log("Launcher", "Verified prebuilt frontend installed; Node/npm not required.")
            return True
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False

    def _node_build_supported(self) -> bool:
        executable = shutil.which("node")
        if not executable:
            self.log("Launcher", "Node.js is unavailable; changed frontend assets cannot be built.", "31")
            return False
        try:
            completed = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5.0,
            )
            version = completed.stdout.strip().lstrip("v")
            major, minor, *_ = [int(part) for part in version.split(".")]
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.log("Launcher", f"Could not verify Node.js version: {exc}", "31")
            return False
        supported = (major == 20 and minor >= 19) or (major == 22 and minor >= 12) or major > 22
        if not supported:
            self.log(
                "Launcher",
                f"Node.js {version} is unsupported; install Node 20.19+ or 22.12+.",
                "31",
            )
        return supported

    def _run_npm(self, arguments: list[str], timeout: float, env: Optional[dict] = None) -> bool:
        executable = shutil.which("npm.cmd" if platform.system() == "Windows" else "npm")
        if not executable:
            self.log("Launcher", "npm is unavailable; cannot prepare changed frontend assets.", "31")
            return False
        command = [executable, *arguments]
        use_shell = platform.system() == "Windows"
        if use_shell:
            # npm is commonly npm.cmd on Windows; quote the fixed argument list
            # rather than interpolating user input into a shell string.
            command = subprocess.list2cmdline(command)
        try:
            process = subprocess.Popen(
                command,
                cwd=str(self.frontend_dir),
                env=env,
                shell=use_shell,
                **self._process_options(),
            )
            self.preparation_process = process
            try:
                return_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.terminate_process_tree(process, grace_seconds=3.0)
                self.log("Launcher", f"npm {' '.join(arguments)} timed out and was stopped.", "31")
                return False
            finally:
                if self.preparation_process is process:
                    self.preparation_process = None
        except OSError as exc:
            self.log("Launcher", f"npm {' '.join(arguments)} failed to run: {exc}", "31")
            return False
        if return_code != 0:
            self.log(
                "Launcher",
                f"npm {' '.join(arguments)} exited with status {return_code}.",
                "31",
            )
            return False
        return True

    def prepare_frontend(self) -> bool:
        """Sync/install/build only when source or lock content has changed."""
        if not self._sync_installed_frontend():
            return False
        package_json = self.frontend_dir / "package.json"
        package_lock = self.frontend_dir / "package-lock.json"
        if not package_json.is_file() or not package_lock.is_file():
            self.log("Launcher", "Frontend package.json/package-lock.json is missing.", "31")
            return False

        source_digest = self._frontend_digest(self.frontend_dir)
        api_url = f"http://{self.host}:{self.backend_port}"
        build_key = hashlib.sha256(f"{source_digest}|{api_url}".encode("utf-8")).hexdigest()
        build_marker = self.frontend_dir / ".ultron_build.sha256"
        if (
            (self.frontend_dist / "index.html").is_file()
            and self._read_marker(build_marker) == build_key
        ):
            self.log("Launcher", "Frontend production build is current; skipping npm work.")
            return True

        if self._prepare_from_prebuilt(source_digest, api_url, build_key):
            return True

        if not self._node_build_supported():
            return False

        dependency_key = hashlib.sha256(
            package_json.read_bytes() + b"\0" + package_lock.read_bytes()
        ).hexdigest()
        dependency_marker = self.frontend_dir / ".ultron_dependencies.sha256"
        if (
            not (self.frontend_dir / "node_modules").is_dir()
            or self._read_marker(dependency_marker) != dependency_key
        ):
            self.log("Launcher", "Frontend dependency lock changed; running npm ci once.", "33")
            if not self._run_npm(["ci", "--no-audit", "--no-fund"], timeout=600.0):
                return False
            self._write_marker(dependency_marker, dependency_key)

        self.log("Launcher", "Building production frontend assets.", "35")
        build_env = os.environ.copy()
        build_env["VITE_API_URL"] = api_url
        if not self._run_npm(["run", "build"], timeout=300.0, env=build_env):
            return False
        if not (self.frontend_dist / "index.html").is_file():
            self.log("Launcher", "Frontend build completed without dist/index.html.", "31")
            return False
        self._write_marker(build_marker, build_key)
        return True

    def _process_options(self) -> dict:
        if platform.system() == "Windows":
            return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
        return {"start_new_session": True}

    def _start_process(
        self,
        command: list[str],
        cwd: Path,
        name: str,
        color: str,
        env: Optional[dict] = None,
    ):
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            **self._process_options(),
        )
        thread = Thread(
            target=self.stream_output,
            args=(process, name, color),
            daemon=True,
            name=f"ultron-{name.lower()}-logs",
        )
        thread.start()
        self._output_threads.append(thread)
        return process

    def stream_output(self, process, name: str, color_code: str) -> None:
        stream = getattr(process, "stdout", None)
        if stream is None:
            return
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                self.log(name, line.rstrip(), color_code)
        except (OSError, ValueError):
            pass

    def start_services(self) -> None:
        child_env = os.environ.copy()
        child_env["ULTRON_HOME"] = str(self.application_home)
        child_env["ULTRON_CONFIG"] = str(self.config_path)
        backend_command = [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            self.host,
            "--port",
            str(self.backend_port),
        ]
        frontend_command = [
            sys.executable,
            "-m",
            "backend.app.static_server",
            "--directory",
            str(self.frontend_dist),
            "--host",
            self.host,
            "--port",
            str(self.frontend_port),
        ]
        self.log("Launcher", "Starting FastAPI backend on loopback.", "34")
        self.backend_process = self._start_process(
            backend_command, self.asset_root, "FastAPI", "34", env=child_env
        )
        if self.is_shutting_down:
            return
        self.log("Launcher", "Starting production frontend static server on loopback.", "36")
        self.frontend_process = self._start_process(
            frontend_command, self.asset_root, "Frontend", "36", env=child_env
        )

    def _wait_for_http(
        self,
        url: str,
        process,
        timeout_sec: float,
        validator: Callable[[dict], bool],
    ) -> bool:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if self.stop_request_path.exists():
                self.stop_request_path.unlink(missing_ok=True)
                self._requested_exit_code = 0
                self.shutdown()
                return False
            if process is None or process.poll() is not None:
                return False
            try:
                with urllib.request.urlopen(url, timeout=2.0) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    if response.status == 200 and validator(payload):
                        return True
            except Exception:
                pass
            self.sleep(0.25)
        return False

    def wait_for_backend_health(self, timeout_sec: Optional[float] = None) -> bool:
        return self._wait_for_http(
            f"http://{self.host}:{self.backend_port}/api/health",
            self.backend_process,
            timeout_sec or self.startup_timeout,
            lambda payload: (
                payload.get("status") in {"healthy", "degraded"}
                and isinstance(payload.get("system_metrics"), dict)
                and isinstance(payload.get("models"), dict)
            ),
        )

    def wait_for_frontend_health(self, timeout_sec: Optional[float] = None) -> bool:
        return self._wait_for_http(
            f"http://{self.host}:{self.frontend_port}/healthz",
            self.frontend_process,
            timeout_sec or self.startup_timeout,
            lambda payload: (
                payload.get("status") == "healthy"
                and payload.get("service") == "ultron-frontend"
            ),
        )

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self.shutdown_handler)
        signal.signal(signal.SIGTERM, self.shutdown_handler)

    def monitor_services(self, poll_interval: float = 0.5) -> int:
        while not self.is_shutting_down:
            if self.stop_request_path.exists():
                self.stop_request_path.unlink(missing_ok=True)
                self.log("Launcher", "Stop requested from the desktop/application shortcut.", "33")
                self._requested_exit_code = 0
                return 0
            for name, process in (
                ("backend", self.backend_process),
                ("frontend", self.frontend_process),
            ):
                if process is None:
                    self.log("Launcher", f"{name} process was not started.", "31")
                    return 1
                return_code = process.poll()
                if return_code is not None:
                    self.log(
                        "Launcher",
                        f"{name} exited unexpectedly with status {return_code}; stopping sibling service.",
                        "31",
                    )
                    return 1
            self.sleep(poll_interval)
        return self._requested_exit_code

    def shutdown_handler(self, _signum, _frame) -> None:
        self._requested_exit_code = 0
        self.shutdown()

    def terminate_process_tree(self, process, grace_seconds: float = 5.0) -> bool:
        if process is None or process.poll() is not None:
            return True
        try:
            if platform.system() == "Windows":
                process.terminate()
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            process.wait(timeout=grace_seconds)
            return True
        except subprocess.TimeoutExpired:
            pass
        except (OSError, ProcessLookupError):
            try:
                process.terminate()
                process.wait(timeout=grace_seconds)
                return True
            except (OSError, subprocess.TimeoutExpired):
                pass

        try:
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=10.0,
                )
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            process.wait(timeout=5.0)
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
            pass
        return process.poll() is not None

    # Backward-compatible name used by previous tests/integrations.
    kill_process_tree = terminate_process_tree

    def shutdown(self) -> None:
        if self.is_shutting_down:
            return
        self.is_shutting_down = True
        self.log("Launcher", "Stopping Ultron services.", "33")
        preparation_stopped = self.terminate_process_tree(self.preparation_process)
        frontend_stopped = self.terminate_process_tree(self.frontend_process)
        backend_stopped = self.terminate_process_tree(self.backend_process)
        if not preparation_stopped or not frontend_stopped or not backend_stopped:
            self.log("Launcher", "One or more child processes could not be verified stopped.", "31")
            self._requested_exit_code = 1
        for thread in self._output_threads:
            thread.join(timeout=1.0)
        self.stop_request_path.unlink(missing_ok=True)
        self.release_instance_lock()

    def run(self) -> int:
        self.launch_started_at = time.monotonic()
        self.render_startup_banner()
        self.log("Launcher", "Initializing localhost-only Ultron services.", "35")
        self.progress(1, "Checking installation assets", "CHECKING")
        if not self.acquire_instance_lock():
            self.progress(1, "Checking installation assets", "FAILED", "31")
            self.log("Launcher", "Another Ultron launcher is already active.", "31")
            return 1
        try:
            self.install_signal_handlers()
            if not self.preflight_port_check():
                self.progress(1, "Checking installation assets", "FAILED", "31")
                return 1
            try:
                frontend_ready = self.prepare_frontend()
            except OSError as exc:
                self.progress(1, "Checking installation assets", "FAILED", "31")
                self.log("Launcher", f"Frontend preparation failed: {exc}", "31")
                return 1
            if not frontend_ready:
                return self._requested_exit_code if self.is_shutting_down else 1
            self.progress(1, "Checking installation assets", "READY", "32")
            self.progress(2, "Loading private configuration", "LOADED", "32")
            if self.is_shutting_down:
                return self._requested_exit_code
            self.progress(3, "Starting backend service", "STARTING")
            self.progress(4, "Starting dashboard service", "STARTING")
            try:
                self.start_services()
            except (OSError, subprocess.SubprocessError) as exc:
                self.log("Launcher", f"Service process failed to start: {exc}", "31")
                return 1

            self.progress(5, "AI Core", "CHECKING")
            if not self.wait_for_backend_health():
                if self.is_shutting_down:
                    return self._requested_exit_code
                self.progress(3, "Starting backend service", "FAILED", "31")
                self.log("Launcher", "Backend failed its startup health gate; browser will not open.", "31")
                return 1
            self.progress(
                3,
                "Starting backend service",
                f"CONNECTED  {self.host}:{self.backend_port}",
                "32",
            )
            if not self.wait_for_frontend_health():
                if self.is_shutting_down:
                    return self._requested_exit_code
                self.progress(4, "Starting dashboard service", "FAILED", "31")
                self.log("Launcher", "Frontend failed its startup health gate; browser will not open.", "31")
                return 1
            self.progress(
                4,
                "Starting dashboard service",
                f"CONNECTED  {self.host}:{self.frontend_port}",
                "32",
            )
            key_slots = self.configured_ai_key_slots()
            if key_slots:
                self.progress(5, "AI Core", f"CONFIGURED  {key_slots} key slot(s)", "36")
            else:
                self.progress(5, "AI Core", "LOCAL ONLY  providers not configured", "33")

            url = f"http://{self.host}:{self.frontend_port}"
            browser_disabled = os.getenv("ULTRON_NO_BROWSER", "").strip().lower() in {"1", "true", "yes"}
            if browser_disabled:
                dispatched = False
                self.log("Launcher", f"Both services healthy; browser launch intentionally skipped for {url}.", "33")
            else:
                try:
                    dispatched = bool(webbrowser.open(url))
                except Exception as exc:
                    dispatched = False
                    self.log("Launcher", f"Browser dispatch failed: {exc}", "33")
            if dispatched:
                self.log("Launcher", f"Both services healthy; browser launch dispatched for {url}.", "32")
            elif not browser_disabled:
                self.log("Launcher", f"Both services healthy. Open {url} manually.", "33")
            self.render_ready(url, dispatched, browser_disabled)
            return self.monitor_services()
        finally:
            self.shutdown()


def main() -> int:
    try:
        return ServiceLauncher().run()
    except LauncherError as exc:
        print(f"[Launcher] Configuration error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
