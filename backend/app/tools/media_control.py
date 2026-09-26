"""Control whatever is playing: YouTube or Spotify in Chrome/Firefox, the Spotify
app, Rhythmbox, VLC, mpv (with its MPRIS plugin)... (V2 Step C5).

Linux: the standard MPRIS D-Bus interface through `gdbus` (no extra packages).
Every action is checked afterwards (Paused / Playing / new title) so Ultron
never says "paused" when nothing changed. Windows: the system media keys (the
OS gives no way to read the state back, so the reply says the key was sent).
Never raises; plain dicts.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from typing import Any, Optional

IS_WINDOWS = os.name == "nt"
MPRIS = "org.mpris.MediaPlayer2"
_PATH = "/org/mpris/MediaPlayer2"
_METHODS = {"pause": "Pause", "play": "Play", "toggle": "PlayPause", "next": "Next",
            "previous": "Previous", "stop": "Stop"}
_WINDOWS_KEYS = {"pause": 0xB3, "play": 0xB3, "toggle": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2}


def _ok(**data) -> dict:
    return {"success": True, "data": data, "error": None}


def _fail(error: str, **data) -> dict:
    return {"success": False, "data": data, "error": error}


def _gdbus(*args: str, timeout: float = 4.0) -> tuple[int, str]:
    exe = shutil.which("gdbus")
    if not exe:
        return 127, ""
    try:
        done = subprocess.run([exe, "call", "--session", *args], capture_output=True, text=True,  # noqa: S603
                              timeout=timeout, check=False)
        return done.returncode, done.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def _prop(bus: str, name: str) -> str:
    _code, out = _gdbus("--dest", bus, "--object-path", _PATH, "--method",
                        "org.freedesktop.DBus.Properties.Get", f"{MPRIS}.Player", name)
    return out


def _status(bus: str) -> str:
    match = re.search(r"'(Playing|Paused|Stopped)'", _prop(bus, "PlaybackStatus"))
    return match.group(1) if match else "Unknown"


def _metadata(bus: str) -> dict[str, str]:
    out = _prop(bus, "Metadata")
    found = {}
    for key, field in (("title", "xesam:title"), ("url", "xesam:url")):
        match = re.search(rf"'{field}': <'((?:[^'\\]|\\.)*)'>", out)
        if match:
            found[key] = match.group(1)
    artist = re.search(r"'xesam:artist': <\['((?:[^'\\]|\\.)*)'", out)
    if artist:
        found["artist"] = artist.group(1)
    return found


def _label(bus: str, meta: dict[str, str]) -> str:
    short = bus[len(MPRIS) + 1:].split(".")[0].lower()
    app = {"chromium": "Chrome", "chrome": "Chrome", "firefox": "Firefox", "brave": "Brave", "spotify": "Spotify",
           "vlc": "VLC", "mpv": "mpv", "rhythmbox": "Rhythmbox"}.get(short, short.capitalize() or "Player")
    where = (meta.get("url") or "").lower()
    for site, name in (("youtube.", "YouTube"), ("spotify.", "Spotify"), ("music.youtube", "YouTube Music")):
        if site in where and app != name:
            return f"{name} in {app}"
    return app


def players() -> list[dict[str, Any]]:
    """Every media player on the session bus with its state and song."""
    code, out = _gdbus("--dest", "org.freedesktop.DBus", "--object-path", "/org/freedesktop/DBus",
                       "--method", "org.freedesktop.DBus.ListNames")
    if code != 0:
        return []
    found = []
    for bus in re.findall(r"'(org\.mpris\.MediaPlayer2\.[^']+)'", out):
        meta = _metadata(bus)
        found.append({"bus": bus, "status": _status(bus), "label": _label(bus, meta), **meta})
    return found


def _matches_hint(player: dict, hint: Optional[str]) -> bool:
    if not hint:
        return False
    text = " ".join(str(player.get(k) or "") for k in ("bus", "label", "url", "title")).lower()
    return hint.lower() in text


def pick(found: list[dict], action: str, hint: Optional[str] = None) -> Optional[dict]:
    """The player the owner means: the named one, else the one playing, else a paused one."""
    if not found:
        return None
    named = [p for p in found if _matches_hint(p, hint)]
    pool = named or found
    playing = [p for p in pool if p["status"] == "Playing"]
    paused = [p for p in pool if p["status"] == "Paused"]
    if action in {"play"}:
        return (paused or playing or pool)[0]
    return (playing or paused or pool)[0]


def control(action: str, hint: Optional[str] = None) -> dict:
    """pause | play | toggle | next | previous | stop -> checked result."""
    if action not in _METHODS:
        return _fail(f"Unknown media action '{action}'.")
    if IS_WINDOWS:
        return _windows_key(action)
    if not shutil.which("gdbus"):
        return _fail("gdbus is not installed, so I can't reach the media players.")
    found = players()
    player = pick(found, action, hint)
    if player is None:
        return _fail("Nothing is playing that I can control right now." +
                     (f" {hint.capitalize()} is not open." if hint else ""), players=0)
    if hint and not _matches_hint(player, hint) and action != "stop":
        note = f"{hint.capitalize()} is not playing; this is {player['label']}."
    else:
        note = None
    if action == "pause" and player["status"] == "Paused":
        return _ok(player=player["label"], status="Paused", title=player.get("title"), already=True, note=note)
    if action == "play" and player["status"] == "Playing":
        return _ok(player=player["label"], status="Playing", title=player.get("title"), already=True, note=note)
    before = player.get("title")
    code, _out = _gdbus("--dest", player["bus"], "--object-path", _PATH, "--method",
                        f"{MPRIS}.Player.{_METHODS[action]}")
    if code != 0:
        return _fail(f"{player['label']} did not accept {action}.", player=player["label"])
    want = {"pause": "Paused", "play": "Playing", "stop": "Stopped"}.get(action)
    status, title = player["status"], before
    for _ in range(8):  # check it really happened (up to ~1.6 s)
        time.sleep(0.2)
        status = _status(player["bus"])
        title = _metadata(player["bus"]).get("title") or before
        if (want and status == want) or (action == "toggle" and status != player["status"]) \
                or (action in {"next", "previous"} and title != before):
            break
    confirmed = (status == want) if want else (status != player["status"]) if action == "toggle" else (title != before)
    if want and not confirmed:
        return _fail(f"I asked {player['label']} to {action}, but it still says {status}.",
                     player=player["label"], status=status)
    return _ok(player=player["label"], status=status, title=title, confirmed=bool(confirmed), note=note)


def now_playing(hint: Optional[str] = None) -> dict:
    if IS_WINDOWS:
        return _fail("On Windows I can't read what is playing.")
    found = players()
    player = pick(found, "pause", hint)
    if player is None:
        return _fail("Nothing is playing right now.")
    return _ok(player=player["label"], status=player["status"], title=player.get("title"),
               artist=player.get("artist"))


def set_player_volume(level: int, hint: Optional[str] = None) -> dict:
    found = players()
    player = pick(found, "pause", hint)
    if player is None:
        return _fail("No media player is open.")
    value = max(0, min(100, int(level))) / 100
    code, _out = _gdbus("--dest", player["bus"], "--object-path", _PATH, "--method",
                        "org.freedesktop.DBus.Properties.Set", f"{MPRIS}.Player", "Volume", f"<{value:.2f}>")
    if code != 0:
        return _fail(f"{player['label']} does not let me set its own volume; use the system volume.")
    return _ok(player=player["label"], level=int(value * 100))


def _windows_key(action: str) -> dict:
    try:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        key = _WINDOWS_KEYS[action]
        user32.keybd_event(key, 0, 0, 0)
        user32.keybd_event(key, 0, 2, 0)  # key up
    except Exception as exc:
        return _fail(f"Could not send the media key: {exc}")
    return _ok(sent_key=action, confirmed=False,
               note="Windows does not report the player state; the media key was sent.")
