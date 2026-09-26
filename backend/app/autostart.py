"""V2 Step E6: start Ultron at login and bring him back if he crashes.

Ubuntu: a systemd USER service (no root, no sudo) tied to the desktop session.
  Restart=on-failure restarts him after a crash; a normal stop (exit 0) stays
  stopped. StartLimitBurst stops an endless crash loop (5 tries in 5 minutes).
Windows: a small .cmd in the user's Startup folder that starts Ultron minimized
  and restarts it after a crash, at most 5 times.

`ultron autostart on|off|status` uses these functions. Nothing here needs admin
rights and nothing touches system folders.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Optional

from backend.app.install_paths import APPLICATION_HOME, ASSET_ROOT

SERVICE_NAME = "ultron.service"
MAX_RESTARTS = 5


def _python() -> str:
    """pythonw on Windows (no console window), the running python elsewhere."""
    exe = Path(sys.executable)
    if platform.system() == "Windows":
        candidate = exe.with_name("pythonw.exe")
        if candidate.is_file():
            return str(candidate)
    return str(exe)


# ------------------------------------------------------------------- Linux
def linux_unit_path(home: Optional[Path] = None) -> Path:
    base = os.getenv("XDG_CONFIG_HOME") or str((home or Path.home()) / ".config")
    return Path(base) / "systemd" / "user" / SERVICE_NAME


def linux_unit_text(python: Optional[str] = None) -> str:
    python = python or _python()
    return f"""[Unit]
Description=Ultron personal assistant
Documentation=https://github.com/dubessix/ultron-v2
After=graphical-session.target network-online.target
PartOf=graphical-session.target
StartLimitIntervalSec=300
StartLimitBurst={MAX_RESTARTS}

[Service]
Type=simple
WorkingDirectory={ASSET_ROOT}
Environment="ULTRON_HOME={APPLICATION_HOME}"
Environment="ULTRON_AUTOSTART=1"
Environment="PYTHONUNBUFFERED=1"
ExecStart="{python}" -m backend.app.cli start
Restart=on-failure
RestartSec=5
TimeoutStopSec=20

[Install]
WantedBy=graphical-session.target
"""


def _systemctl(*args: str) -> tuple[bool, str]:
    tool = shutil.which("systemctl")
    if not tool:
        return False, "systemctl is not available on this PC"
    try:
        done = subprocess.run(  # nosec B603
            [tool, "--user", *args], capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    return done.returncode == 0, (done.stdout + done.stderr).strip()


# ----------------------------------------------------------------- Windows
def windows_startup_dir() -> Path:
    appdata = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def windows_entry_path() -> Path:
    return windows_startup_dir() / "Ultron.cmd"


def windows_runner_path() -> Path:
    return APPLICATION_HOME / "data" / "autostart" / "run_ultron.cmd"


def windows_runner_text(python: Optional[str] = None) -> str:
    python = python or str(Path(sys.executable))
    return (
        "@echo off\r\n"
        "rem Ultron autostart: restarts after a crash, at most "
        f"{MAX_RESTARTS} times.\r\n"
        f'cd /d "{ASSET_ROOT}"\r\n'
        f'set "ULTRON_HOME={APPLICATION_HOME}"\r\n'
        "set ULTRON_AUTOSTART=1\r\n"
        "set /a tries=0\r\n"
        ":again\r\n"
        f'"{python}" -m backend.app.cli start\r\n'
        "if %errorlevel%==0 goto :eof\r\n"
        "set /a tries+=1\r\n"
        f"if %tries% geq {MAX_RESTARTS} goto :eof\r\n"
        "timeout /t 5 /nobreak >nul\r\n"
        "goto again\r\n"
    )


def windows_entry_text() -> str:
    return f'@echo off\r\nstart "Ultron" /min cmd /c "{windows_runner_path()}"\r\n'


# -------------------------------------------------------------- public API
def status() -> dict:
    """{'enabled': bool, 'how': str, 'detail': str} in plain words."""
    system = platform.system()
    if system == "Windows":
        on = windows_entry_path().is_file()
        return {"enabled": on, "how": "Windows Startup folder",
                "detail": str(windows_entry_path()) if on else "not set"}
    if system == "Linux":
        unit = linux_unit_path()
        if not unit.is_file():
            return {"enabled": False, "how": "systemd user service", "detail": "not set"}
        ok, out = _systemctl("is-enabled", SERVICE_NAME)
        return {"enabled": ok and "enabled" in out, "how": "systemd user service",
                "detail": out or str(unit)}
    return {"enabled": False, "how": "unsupported", "detail": f"{system} is not supported"}


def enable() -> dict:
    system = platform.system()
    if system == "Windows":
        runner = windows_runner_path()
        runner.parent.mkdir(parents=True, exist_ok=True)
        runner.write_text(windows_runner_text(), encoding="utf-8")
        entry = windows_entry_path()
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text(windows_entry_text(), encoding="utf-8")
        return {"success": True, "message": "Ultron will start when you log in to Windows."}
    if system == "Linux":
        unit = linux_unit_path()
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text(linux_unit_text(), encoding="utf-8")
        ok, out = _systemctl("daemon-reload")
        if ok:
            ok, out = _systemctl("enable", SERVICE_NAME)
        if not ok:
            return {"success": False,
                    "message": f"Saved {unit}, but systemd said: {out or 'no answer'}"}
        return {"success": True,
                "message": "Ultron will start when you log in, and restart if he crashes."}
    return {"success": False, "message": f"Autostart is not supported on {system}."}


def disable() -> dict:
    system = platform.system()
    if system == "Windows":
        for path in (windows_entry_path(), windows_runner_path()):
            path.unlink(missing_ok=True)
        return {"success": True, "message": "Ultron will no longer start at login."}
    if system == "Linux":
        _systemctl("disable", SERVICE_NAME)
        linux_unit_path().unlink(missing_ok=True)
        _systemctl("daemon-reload")
        return {"success": True, "message": "Ultron will no longer start at login."}
    return {"success": False, "message": f"Autostart is not supported on {system}."}
