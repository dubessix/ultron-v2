"""PC facts for the brain: what this machine is and what is installed (V2 Step B6).

One line, cached in memory and on disk, refreshed once a day. It sits in the
static (cached) prompt prefix, so it costs no counted tokens per order. Only
program names and versions - no personal data. Never raises.
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import shutil
from pathlib import Path
from typing import Optional

# friendly name -> commands that provide it (first found wins)
PROGRAMS: dict[str, tuple[str, ...]] = {
    "python": ("python3", "python", "py"),
    "node": ("node",),
    "npm": ("npm",),
    "git": ("git",),
    "vscode": ("code", "code-oss", "codium"),
    "chrome": ("google-chrome", "google-chrome-stable", "chrome", "chromium", "chromium-browser"),
    "firefox": ("firefox",),
    "mpv": ("mpv",),
    "vlc": ("vlc",),
    "ffmpeg": ("ffmpeg",),
    "libreoffice": ("libreoffice", "soffice"),
    "pandoc": ("pandoc",),
    "docker": ("docker",),
    "playerctl": ("playerctl",),
    "wmctrl": ("wmctrl",),
    "xdotool": ("xdotool",),
    "ydotool": ("ydotool",),
    "snap": ("snap",),
    "flatpak": ("flatpak",),
    "apt": ("apt",),
    "winget": ("winget",),
    "spotify": ("spotify",),
}
# Windows programs that are usually not on PATH
_WINDOWS_PATHS: dict[str, tuple[str, ...]] = {
    "chrome": (r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
               r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
               r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    "firefox": (r"%ProgramFiles%\Mozilla Firefox\firefox.exe",),
    "vlc": (r"%ProgramFiles%\VideoLAN\VLC\vlc.exe",),
    "vscode": (r"%LocalAppData%\Programs\Microsoft VS Code\Code.exe",),
    "libreoffice": (r"%ProgramFiles%\LibreOffice\program\soffice.exe",),
    "spotify": (r"%AppData%\Spotify\Spotify.exe",),
}
_ONLY_ON = {"apt": "Linux", "snap": "Linux", "flatpak": "Linux", "wmctrl": "Linux", "xdotool": "Linux",
            "ydotool": "Linux", "playerctl": "Linux", "winget": "Windows"}

_memory: dict = {}


def _cache_file() -> Path:
    from backend.app.runtime_paths import runtime_data_path

    return runtime_data_path("pc_facts.json")


def _os_name() -> str:
    system = platform.system() or "Unknown"
    if system == "Linux":
        try:
            info = platform.freedesktop_os_release()
            return info.get("PRETTY_NAME") or info.get("NAME") or "Linux"
        except (OSError, AttributeError):
            return "Linux"
    if system == "Windows":
        return f"Windows {platform.release()}"
    if system == "Darwin":
        return f"macOS {platform.mac_ver()[0]}"
    return system


def _desktop() -> Optional[str]:
    if platform.system() != "Linux":
        return None
    session = (os.environ.get("XDG_SESSION_TYPE") or "").strip()
    if not session:
        session = "Wayland" if os.environ.get("WAYLAND_DISPLAY") else ("X11" if os.environ.get("DISPLAY") else "")
    desk = (os.environ.get("XDG_CURRENT_DESKTOP") or "").split(":")[-1].strip()
    text = " ".join(part for part in (desk, session.capitalize() if session.islower() else session) if part)
    return text or None


def _ram_gb() -> Optional[float]:
    try:
        import psutil

        return round(psutil.virtual_memory().total / 1024 ** 3, 1)
    except Exception:
        return None


def _installed() -> tuple[list[str], list[str]]:
    system = platform.system()
    have, missing = [], []
    for name, commands in PROGRAMS.items():
        only = _ONLY_ON.get(name)
        if only and only != system:
            continue
        found = any(shutil.which(cmd) for cmd in commands)
        if not found and system == "Windows":
            found = any(Path(os.path.expandvars(p)).is_file() for p in _WINDOWS_PATHS.get(name, ()))
        (have if found else missing).append(name)
    return have, missing


def collect() -> dict:
    have, missing = _installed()
    return {
        "day": datetime.date.today().isoformat(),
        "os": _os_name(),
        "desktop": _desktop(),
        "cores": os.cpu_count(),
        "ram_gb": _ram_gb(),
        "have": have,
        "missing": missing,
    }


def facts(refresh: bool = False) -> dict:
    """Today's facts: memory -> disk -> fresh scan (about 20 ms)."""
    today = datetime.date.today().isoformat()
    if not refresh and _memory.get("day") == today:
        return dict(_memory)
    data: dict = {}
    if not refresh:
        try:
            data = json.loads(_cache_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    if data.get("day") != today:
        try:
            data = collect()
        except Exception:
            data = {"day": today, "os": platform.system() or "Unknown", "have": [], "missing": []}
        try:
            path = _cache_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass
    _memory.clear()
    _memory.update(data)
    return dict(data)


def facts_line() -> str:
    """'PC: Ubuntu 24.04.5 LTS, GNOME Wayland, 2 cores, 7.7 GB RAM. Installed: ... Not installed: ...'"""
    data = facts()
    head = [data.get("os") or "Unknown"]
    if data.get("desktop"):
        head.append(str(data["desktop"]))
    if data.get("cores"):
        head.append(f"{data['cores']} cores")
    if data.get("ram_gb"):
        head.append(f"{data['ram_gb']} GB RAM")
    line = "PC: " + ", ".join(head) + "."
    if data.get("have"):
        line += " Installed: " + ", ".join(data["have"]) + "."
    if data.get("missing"):
        line += " Not installed: " + ", ".join(data["missing"]) + "."
    return line
