"""Cloud soak check: start Ultron, sit idle, prove it is light and never stuck.

Fails when:
- /api/health is not 200 within 60 s
- idle RAM is above ULTRON_SOAK_MAX_MB (default 250 MB)
- idle CPU is above ULTRON_SOAK_MAX_CPU percent (default 5 %) -> a busy/infinite loop
- the thread count keeps growing (a leak)
- the server does not stop within 15 s
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[2]
MAX_MB = int(os.getenv("ULTRON_SOAK_MAX_MB", "250"))
MAX_CPU = float(os.getenv("ULTRON_SOAK_MAX_CPU", "5"))
IDLE_SECONDS = int(os.getenv("ULTRON_SOAK_SECONDS", "60"))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_health(port: int, deadline: float) -> bool:
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3) as res:
                if res.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(1)
    return False


def main() -> int:
    port = free_port()
    home = tempfile.mkdtemp(prefix="ultron-soak-")
    env = dict(os.environ, ULTRON_HOME=home, ULTRON_FOLDER_INDEX="0", ULTRON_NO_BROWSER="1",
               PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    failures: list[str] = []
    try:
        if not wait_health(port, time.time() + 60):
            failures.append("health endpoint never answered 200 within 60 s")
            return report(proc, failures)
        server = psutil.Process(proc.pid)
        server.cpu_percent(None)
        threads_start = server.num_threads()
        time.sleep(IDLE_SECONDS)
        cpu = server.cpu_percent(None)
        rss_mb = server.memory_info().rss / 2**20
        threads_end = server.num_threads()
        print(f"idle {IDLE_SECONDS}s: RSS {rss_mb:.0f} MB, CPU {cpu:.1f} %, threads {threads_start}->{threads_end}")
        if rss_mb > MAX_MB:
            failures.append(f"idle RAM {rss_mb:.0f} MB > {MAX_MB} MB")
        if cpu > MAX_CPU:
            failures.append(f"idle CPU {cpu:.1f} % > {MAX_CPU} % (busy or infinite loop)")
        if threads_end > threads_start + 4:
            failures.append(f"threads grew {threads_start}->{threads_end} while idle (leak)")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            failures.append("server did not stop within 15 s (stuck shutdown)")
            proc.kill()
    return report(proc, failures)


def report(proc: subprocess.Popen, failures: list[str]) -> int:
    log = proc.stdout.read() if proc.stdout and proc.poll() is not None else ""
    if "Traceback" in log:
        failures.append("server log contains a Traceback")
    if failures:
        print("SOAK FAILED:\n- " + "\n- ".join(failures))
        print("---- server log tail ----\n" + "\n".join(log.splitlines()[-40:]))
        return 1
    print("SOAK PASSED: light, idle and stops cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
