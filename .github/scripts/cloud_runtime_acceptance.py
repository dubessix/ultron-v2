"""Run a real isolated Ultron start/health/stop cycle on a cloud runner."""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[2]
BACKEND_URL = "http://127.0.0.1:8000/api/health"
FRONTEND_HEALTH_URL = "http://127.0.0.1:5173/healthz"
FRONTEND_URL = "http://127.0.0.1:5173/"
SENSITIVE_ENV_NAMES = (
    "GROQ_API_KEY_1",
    "GEMINI_API_KEY_1",
    "NVIDIA_API_KEY_1",
    "TAVILY_API_KEY",
    "GITHUB_TOKEN_1",
    "GITHUB_USERNAME_1",
    "GH_TOKEN",
    "GITHUB_TOKEN",
)


def run_checked(command: list[str], env: dict[str, str], log_path: Path, timeout: float = 180.0) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n$ {' '.join(command)}\n{result.stdout}")
    if result.returncode != 0:
        raise RuntimeError(f"Command failed with status {result.returncode}: {' '.join(command)}")
    return result.stdout


def wait_for_json(
    url: str,
    accepted: Callable[[dict], bool],
    process: subprocess.Popen,
    timeout: float = 150.0,
) -> dict:
    deadline = time.monotonic() + timeout
    last_error = "no response"
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(f"Ultron launcher exited before health passed (status {return_code}).")
        try:
            with urllib.request.urlopen(url, timeout=3.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, dict) and accepted(payload):
                return payload
            last_error = f"unexpected payload: {payload!r}"
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for {url}: {last_error}")


def wait_for_page(process: subprocess.Popen, timeout: float = 30.0) -> str:
    deadline = time.monotonic() + timeout
    last_error = "no response"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Ultron launcher exited before the frontend page loaded.")
        try:
            with urllib.request.urlopen(FRONTEND_URL, timeout=3.0) as response:
                page = response.read().decode("utf-8")
            if '<div id="root"></div>' in page and "ULTRON V1" in page:
                return page
            last_error = "root element or title was missing"
        except (OSError, UnicodeError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for the frontend page: {last_error}")


def port_is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                # Match the launcher: harmless TIME_WAIT connections must not be
                # mistaken for a still-running listener after clean shutdown.
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def wait_for_ports(timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_is_available(8000) and port_is_available(5173):
            return
        time.sleep(0.25)
    raise RuntimeError("Backend or frontend port remained occupied after Stop Ultron.")


def force_stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=20.0,
        )
    else:
        try:
            os.killpg(os.getpgid(process.pid), 15)
            process.wait(timeout=10.0)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(os.getpgid(process.pid), 9)
            except OSError:
                pass
    try:
        process.wait(timeout=10.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10.0)


def main() -> int:
    if (ROOT / "data").exists():
        raise RuntimeError("Refusing cloud acceptance: source production data/ already exists.")

    artifact_root = Path(
        os.environ.get("ULTRON_CLOUD_ARTIFACTS", Path(tempfile.gettempdir()) / "ultron-cloud-artifacts")
    ).resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    log_path = artifact_root / f"runtime-{platform.system().lower()}.log"
    report_path = artifact_root / f"runtime-{platform.system().lower()}.json"
    log_path.write_text("Ultron isolated cloud runtime acceptance\n", encoding="utf-8")

    runner_temp = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())).resolve()
    home = Path(tempfile.mkdtemp(prefix="ultron-cloud-home-", dir=runner_temp))
    process: subprocess.Popen | None = None
    env = os.environ.copy()
    for name in SENSITIVE_ENV_NAMES:
        env.pop(name, None)
    env.update(
        {
            "ULTRON_HOME": str(home),
            "ULTRON_NO_BROWSER": "1",
            "PYTHONUTF8": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )
    command_prefix = [sys.executable, "-m", "backend.app.cli"]

    try:
        run_checked(command_prefix + ["setup"], env, log_path)
        run_checked(command_prefix + ["doctor"], env, log_path)
        run_checked(command_prefix + ["start", "--check"], env, log_path)

        launch_log = log_path.open("a", encoding="utf-8")
        launch_options: dict = {
            "cwd": ROOT,
            "env": env,
            "stdout": launch_log,
            "stderr": subprocess.STDOUT,
            "text": True,
        }
        if os.name == "nt":
            launch_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            launch_options["start_new_session"] = True
        try:
            process = subprocess.Popen(command_prefix + ["start"], **launch_options)
        finally:
            launch_log.close()

        backend = wait_for_json(
            BACKEND_URL,
            lambda value: value.get("status") in {"healthy", "degraded"}
            and isinstance(value.get("system_metrics"), dict)
            and isinstance(value.get("models"), dict),
            process,
        )
        frontend = wait_for_json(
            FRONTEND_HEALTH_URL,
            lambda value: value.get("status") == "healthy" and value.get("service") == "ultron-frontend",
            process,
        )
        page = wait_for_page(process)

        stop_output = run_checked(command_prefix + ["stop"], env, log_path, timeout=45.0)
        return_code = process.wait(timeout=45.0)
        if return_code != 0:
            raise RuntimeError(f"Ultron launcher returned {return_code} after clean stop request.")
        wait_for_ports()
        if not (home / "data" / "memory").is_dir():
            raise RuntimeError("Isolated runtime data directory was not created.")
        if (ROOT / "data").exists():
            raise RuntimeError("Cloud runtime wrote into source production data/.")

        report = {
            "result": "verified_success",
            "platform": platform.platform(),
            "isolated_home": True,
            "backend_status": backend.get("status"),
            "frontend_status": frontend.get("status"),
            "frontend_root_loaded": '<div id="root"></div>' in page,
            "stop_verified": "stopped cleanly" in stop_output.lower(),
            "ports_released": True,
            "real_credentials_used": False,
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0
    except Exception:
        if log_path.is_file():
            print("\n--- cloud runtime log ---")
            print(log_path.read_text(encoding="utf-8", errors="replace"))
        raise
    finally:
        if process is not None:
            force_stop(process)
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
