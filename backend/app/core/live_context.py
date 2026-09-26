"""One short live line per turn, like IRIS: time, place, open apps, RAM, folder.

~40 tokens. It goes at the END of the system prompt, so the static cached prefix
stays byte-identical. Cheap: the process scan is cached for a few seconds and
never raises. Names only; no window titles, no file contents.
"""

from __future__ import annotations

import datetime
import os
import threading
import time
from pathlib import Path
from typing import Optional

# process name (lower, without .exe) -> friendly app name
_KNOWN_APPS: dict[str, str] = {
    "chrome": "Chrome", "google-chrome": "Chrome", "chromium": "Chromium", "chromium-browser": "Chromium",
    "firefox": "Firefox", "firefox-bin": "Firefox", "brave": "Brave", "msedge": "Edge",
    "code": "VS Code", "code-oss": "VS Code", "codium": "VS Code",
    "mpv": "mpv", "vlc": "VLC", "totem": "Videos", "spotify": "Spotify", "rhythmbox": "Rhythmbox",
    "nautilus": "Files", "explorer": "File Explorer",
    "gnome-terminal-server": "Terminal", "kgx": "Terminal", "ptyxis": "Terminal", "konsole": "Terminal",
    "windowsterminal": "Terminal",
    "soffice.bin": "LibreOffice", "libreoffice": "LibreOffice", "winword": "Word", "excel": "Excel",
    "powerpnt": "PowerPoint", "telegram-desktop": "Telegram", "telegram": "Telegram", "discord": "Discord",
    "whatsapp": "WhatsApp", "obs": "OBS", "gimp": "GIMP", "gimp-2.10": "GIMP", "evince": "Documents",
    "eog": "Image Viewer", "gnome-text-editor": "Text Editor", "gedit": "Text Editor", "notepad": "Notepad",
    "postman": "Postman", "zoom": "Zoom", "steam": "Steam",
}
_CACHE_SECONDS = 8.0
_cache_lock = threading.Lock()
_cache: dict = {"at": 0.0, "apps": [], "ram": None}


def _scan() -> tuple[list[str], Optional[int]]:
    apps: list[str] = []
    ram: Optional[int] = None
    try:
        import psutil

        ram = int(round(psutil.virtual_memory().percent))
        seen: set[str] = set()
        for proc in psutil.process_iter(["name"]):
            name = str(proc.info.get("name") or "").lower()
            if name.endswith(".exe"):
                name = name[:-4]
            friendly = _KNOWN_APPS.get(name)
            if friendly and friendly not in seen:
                seen.add(friendly)
                apps.append(friendly)
    except Exception:
        pass
    return apps[:8], ram


def _apps_and_ram() -> tuple[list[str], Optional[int]]:
    now = time.monotonic()
    with _cache_lock:
        if now - _cache["at"] < _CACHE_SECONDS:
            return list(_cache["apps"]), _cache["ram"]
    apps, ram = _scan()
    with _cache_lock:
        _cache.update(at=time.monotonic(), apps=apps, ram=ram)
    return apps, ram


def _folder_label() -> Optional[str]:
    try:
        from backend.app.core import recent_folders

        folder = recent_folders.last()
    except Exception:
        return None
    if not folder:
        return None
    try:
        home = Path.home()
        path = Path(folder)
        return "~/" + str(path.relative_to(home)).replace("\\", "/") if path != home else "~"
    except ValueError:
        return folder


def live_line(now: Optional[datetime.datetime] = None) -> str:
    """'[Now] Fri 26 Sep 2026 21:40 IST · Kolkata · open: Chrome, VS Code · RAM 58% · folder: ~/Desktop'"""
    try:
        current = (now or datetime.datetime.now()).astimezone()
        parts = [current.strftime("%a %d %b %Y %H:%M ") + (current.tzname() or "")]
    except Exception:
        parts = []
    city = os.getenv("ULTRON_HOME_CITY", "").strip()
    if city:
        parts.append(city[:40])
    apps, ram = _apps_and_ram()
    parts.append("open: " + (", ".join(apps) if apps else "none seen"))
    if ram is not None:
        parts.append(f"RAM {ram}%")
    folder = _folder_label()
    if folder:
        parts.append(f"folder: {folder[:80]}")
    return "[Now] " + " · ".join(part.strip() for part in parts if part.strip())
