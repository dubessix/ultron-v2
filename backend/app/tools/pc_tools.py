"""V2 Step 6 - Jarvis PC tools: apps, PC control, files, clipboard, screenshot, notify.

Ubuntu first, Windows supported. Only built-in OS commands (no new packages,
nothing running in the background). Risky actions (close an app, sleep,
restart, shutdown) go through the normal approval gate via
permission_for_arguments. Every tool reports honestly when the OS command is
missing instead of pretending it worked.
"""

from __future__ import annotations

import asyncio
import datetime
import difflib
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

from backend.app.tools.tool_base import BaseTool

IS_WINDOWS = os.name == "nt"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


async def _run(argv: list[str], timeout: float = 15.0, stdin: Optional[str] = None) -> tuple[int, str, str]:
    """Run an OS command without a shell; returns (code, stdout, stderr)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(
            proc.communicate(stdin.encode("utf-8") if stdin is not None else None), timeout
        )
        return proc.returncode or 0, out.decode("utf-8", "ignore"), err.decode("utf-8", "ignore")
    except (OSError, asyncio.TimeoutError) as exc:
        return 127, "", str(exc)


def _spawn(argv: list[str]) -> None:
    """Start a GUI program detached from Ultron (it keeps running if Ultron stops)."""
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if IS_WINDOWS:
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(argv, **kwargs)  # noqa: S603 - argv list, never a shell


def _powershell(script: str) -> list[str]:
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]


def _ok(**data) -> Dict[str, Any]:
    return {"success": True, "data": data, "error": None}


def _fail(error: str, **data) -> Dict[str, Any]:
    return {"success": False, "data": data, "error": error}


# ---------------------------------------------------------------------------
# Apps: open any installed app by name, close one, list heavy apps
# ---------------------------------------------------------------------------
_PROTECTED_PROCESSES = {
    "systemd", "init", "kthreadd", "xorg", "xwayland", "gnome-shell", "gdm", "gdm3", "sddm", "lightdm",
    "pulseaudio", "pipewire", "wireplumber", "dbus-daemon", "networkmanager", "sshd", "login",
    "explorer.exe", "csrss.exe", "winlogon.exe", "wininit.exe", "services.exe", "lsass.exe",
    "smss.exe", "dwm.exe", "svchost.exe", "system", "registry", "fontdrvhost.exe",
}
_APP_ALIASES = {
    "browser": "chrome", "google chrome": "chrome", "vs code": "code", "vscode": "code",
    "visual studio code": "code", "files": "nautilus", "file manager": "nautilus",
    "terminal": "gnome-terminal", "settings": "gnome-control-center", "calculator": "calculator",
    "word": "winword", "excel": "excel", "powerpoint": "powerpnt", "notepad": "notepad",
}


def _desktop_dirs() -> list[Path]:
    home = Path.home()
    data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
    dirs = [home / ".local/share/applications", *(Path(d) / "applications" for d in data_dirs if d),
            Path("/var/lib/snapd/desktop/applications"), Path("/var/lib/flatpak/exports/share/applications"),
            home / ".local/share/flatpak/exports/share/applications"]
    return [d for d in dict.fromkeys(dirs) if d.is_dir()]


def _linux_apps() -> dict[str, tuple[str, str]]:
    """normalized name -> (desktop id, Exec line)."""
    apps: dict[str, tuple[str, str]] = {}
    for folder in _desktop_dirs():
        for entry in folder.glob("*.desktop"):
            try:
                text = entry.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if re.search(r"^NoDisplay=true", text, re.M):
                continue
            name = re.search(r"^Name=(.+)$", text, re.M)
            exec_line = re.search(r"^Exec=(.+)$", text, re.M)
            if not exec_line:
                continue
            value = (entry.stem, exec_line.group(1).strip())
            for label in {entry.stem, entry.stem.split(".")[-1], name.group(1) if name else ""}:
                if label:
                    apps.setdefault(_norm(label), value)
    return apps


def _windows_shortcuts() -> dict[str, Path]:
    roots = [Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
             Path(os.environ.get("APPDATA", str(Path.home()))) / r"Microsoft\Windows\Start Menu\Programs",
             Path.home() / "Desktop"]
    found: dict[str, Path] = {}
    for root in roots:
        if root.is_dir():
            for link in root.rglob("*.lnk"):
                found.setdefault(_norm(link.stem), link)
    return found


def _best(target: str, names: list[str]) -> Optional[str]:
    if target in names:
        return target
    starts = sorted((n for n in names if n.startswith(target) or target in n), key=len)
    if starts and len(target) >= 3:
        return starts[0]
    close = difflib.get_close_matches(target, names, n=1, cutoff=0.75)
    return close[0] if close else None


class AppsArgs(BaseModel):
    action: Literal["open", "close", "running"] = Field("open", description="open an app, close it, or list heavy running apps.")
    name: Optional[str] = Field(None, max_length=120, description="App name as said, e.g. 'WhatsApp', 'VLC', 'Word'.")
    pid: Optional[int] = Field(None, ge=1, description="Exact process id to close (from action=running).")
    force: bool = Field(False, description="close only: end it even if it did not close gently (unsaved work is lost). Only after the owner says so.")
    limit: int = Field(8, ge=1, le=25)


class AppsTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="apps",
            name="App Control",
            description="Open any installed app by name, close an app (asks first), or list what is slowing the PC.",
            category="system",
            tags=["open app", "launch", "close app", "kill", "processes", "slow pc", "task manager"],
            permission_level=1,
            args_model=AppsArgs,
            usage_examples=["apps(action='open', name='WhatsApp')", "apps(action='running')", "apps(action='close', name='chrome')"],
        )

    def permission_for_arguments(self, arguments: Dict[str, Any]) -> int:
        return 2 if arguments.get("action") == "close" else self.permission_level

    async def execute(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action") or "open"
        if action == "running":
            return await asyncio.to_thread(self._running, int(kwargs.get("limit") or 8))
        if action == "close":
            return await asyncio.to_thread(self._close, kwargs.get("name"), kwargs.get("pid"), bool(kwargs.get("force")))
        name = str(kwargs.get("name") or "").strip()
        if not name:
            return _fail("Say which app to open.")
        return await asyncio.to_thread(self._open, name)

    @staticmethod
    def _open(name: str) -> Dict[str, Any]:
        spoken = _APP_ALIASES.get(name.lower().strip(), name)
        target = _norm(spoken)
        try:
            if IS_WINDOWS:
                links = _windows_shortcuts()
                hit = _best(target, list(links))
                if hit:
                    os.startfile(str(links[hit]))  # type: ignore[attr-defined]
                    return _ok(opened=links[hit].stem, via="start menu")
                # Store apps (WhatsApp, Spotify...) have no .lnk: ask the Start menu.
                listing = subprocess.run(
                    _powershell("Get-StartApps | ForEach-Object { $_.Name + '|' + $_.AppID }"),
                    capture_output=True, text=True, timeout=15,
                ).stdout
                apps = dict(line.split("|", 1) for line in listing.splitlines() if "|" in line)
                hit = _best(target, [_norm(k) for k in apps])
                if hit:
                    label = next(k for k in apps if _norm(k) == hit)
                    _spawn(["explorer.exe", f"shell:AppsFolder\\{apps[label]}"])
                    return _ok(opened=label, via="start apps")
            else:
                apps = _linux_apps()
                hit = _best(target, list(apps))
                if hit:
                    desktop_id, exec_line = apps[hit]
                    if shutil.which("gtk-launch"):
                        _spawn(["gtk-launch", desktop_id])
                    else:
                        argv = [part for part in shlex.split(exec_line) if not part.startswith("%")]
                        _spawn(argv)
                    return _ok(opened=desktop_id, via="applications menu")
            executable = shutil.which(spoken) or shutil.which(target)
            if executable:
                _spawn([executable])
                return _ok(opened=Path(executable).name, via="command")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return _fail(f"Could not open {name}: {exc}")
        return _fail(f"No installed app called '{name}' was found. Ask the owner for the exact name.")

    @staticmethod
    def _running(limit: int) -> Dict[str, Any]:
        import psutil

        for proc in psutil.process_iter():
            try:
                proc.cpu_percent(None)
            except (psutil.Error, OSError):
                pass
        time.sleep(0.5)
        groups: dict[str, dict[str, Any]] = {}
        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                name = (proc.info["name"] or "").strip()
                if not name or name.lower() in _PROTECTED_PROCESSES:
                    continue
                entry = groups.setdefault(name, {"name": name, "ram_mb": 0.0, "cpu": 0.0, "pids": []})
                entry["ram_mb"] += (proc.info["memory_info"].rss if proc.info["memory_info"] else 0) / 1_048_576
                entry["cpu"] += proc.cpu_percent(None)
                entry["pids"].append(proc.info["pid"])
            except (psutil.Error, OSError):
                continue
        heavy = sorted(groups.values(), key=lambda g: (g["cpu"] * 20 + g["ram_mb"]), reverse=True)[:limit]
        for entry in heavy:
            entry["ram_mb"] = round(entry["ram_mb"])
            entry["cpu"] = round(entry["cpu"], 1)
            entry["pids"] = entry["pids"][:5]
        memory = psutil.virtual_memory()
        return _ok(apps=heavy, ram_used_percent=memory.percent, ram_free_gb=round(memory.available / 1e9, 1))

    @staticmethod
    def _close(name: Optional[str], pid: Optional[int], force: bool = False) -> Dict[str, Any]:
        """Close gently -> check it is really gone -> report the truth. Force only on request."""
        import psutil

        keys = _target_keys(name)
        attrs = ["pid", "name", "username", "exe", "cmdline", "create_time"]
        targets = [proc for proc in psutil.process_iter(attrs) if _closable(proc, name, pid, keys)]
        label = str(name or pid)
        if not targets:
            protected = sorted({str(proc.info.get("name")) for proc in psutil.process_iter(["name"])
                                if name and _is_protected(str(proc.info.get("name") or ""))
                                and _matches(_process_keys(proc), keys, name)})
            if protected:
                return _fail(f"{protected[0]} is part of the system (the desktop itself). "
                             "Closing it would break the screen, so I will not.", protected=protected)
            return _fail(f"'{label}' is not running.", running=False)

        names = sorted({str(proc.info.get("name")) for proc in targets})
        if force:
            for proc in targets:
                try:
                    proc.kill()
                except (psutil.Error, OSError):
                    pass
            _gone, alive = psutil.wait_procs(targets, timeout=5)
        else:
            _close_gently(targets, name)
            _gone, alive = psutil.wait_procs(targets, timeout=6)
        alive = [proc for proc in alive if _still_same(proc)]
        if alive:
            left = sorted({str(proc.info.get("name")) for proc in alive})
            return _fail(
                f"{', '.join(left)} is still running"
                + (" even after force." if force else
                   " (it may be asking to save work). Tell the owner; force close only if he says so."),
                still_running=left, pids=[proc.pid for proc in alive][:10], closed=False)
        return _ok(closed=names, processes=len(targets), verified_gone=True)

_PROTECTED_PREFIXES = ("systemd", "kworker", "gnome-shell", "gnome-session", "gnome-keyring", "gnome-settings",
                       "gnome-remote-desktop", "gsd-", "goa-", "evolution-", "tracker-", "xdg-", "dbus", "polkit",
                       "gvfs", "at-spi", "ibus", "pipewire", "wireplumber", "pulseaudio", "xorg", "xwayland",
                       "mutter", "kwin", "plasmashell", "sddm", "lightdm", "gdm", "networkmanager", "wpa_supplicant",
                       "snapd", "svchost", "csrss", "wininit", "winlogon", "lsass", "services", "smss", "dwm",
                       "explorer", "sihost", "ctfmon", "runtimebroker", "searchhost", "startmenuexperiencehost",
                       "shellexperiencehost", "textinputhost", "fontdrvhost", "msmpeng", "securityhealth")
_VENDOR_PREFIXES = ("gnome", "google", "org", "kde", "com", "io", "snap")


def _current_user() -> str:
    import getpass

    try:
        return getpass.getuser().lower()
    except Exception:
        return ""


def _is_protected(process_name: str) -> bool:
    low = process_name.lower()
    return low in _PROTECTED_PROCESSES or low.startswith(_PROTECTED_PREFIXES)


def _strip_vendor(key: str) -> str:
    for prefix in _VENDOR_PREFIXES:
        if key.startswith(prefix) and len(key) > len(prefix) + 2:
            return key[len(prefix):]
    return key


def _process_keys(proc) -> set[str]:
    """Names a running process goes by: its name, its program file, its first argument."""
    info = getattr(proc, "info", {}) or {}
    raw = [str(info.get("name") or "")]
    for value in (info.get("exe"), (info.get("cmdline") or [None])[0]):
        if value:
            raw.append(re.split(r"[\\/]", str(value))[-1])
    keys = set()
    for item in raw:
        key = _norm(re.sub(r"\.exe$", "", item, flags=re.I))
        if key:
            keys.update({key, _strip_vendor(key)})
    return keys


def _target_keys(name: Optional[str]) -> dict[str, set[str]]:
    """spoken: what the owner said (+ alias); launcher: the app's own program / window class."""
    spoken_text = _APP_ALIASES.get(str(name or "").lower().strip(), name or "")
    spoken = {k for k in {_norm(spoken_text), _strip_vendor(_norm(spoken_text))} if k}
    launcher: set[str] = set()
    if name and not IS_WINDOWS:
        try:
            apps = _linux_apps()
            hit = _best(_norm(spoken_text), list(apps))
            if hit:
                desktop_id, exec_line = apps[hit]
                words = [w for w in shlex.split(exec_line) if not w.startswith("%")]
                program = next((w for w in words if not w.startswith("-") and w not in {"env", "flatpak", "run"}
                                and "=" not in w), "")
                for raw in (program.split("/")[-1], desktop_id.split(".")[-1]):
                    key = _norm(raw)
                    if len(key) >= 3:
                        launcher.update({key, _strip_vendor(key)})
        except (OSError, ValueError):
            pass
    return {"spoken": spoken, "launcher": launcher}


def _matches(process_keys: set[str], keys: dict[str, set[str]], name: Optional[str]) -> bool:
    for pk in process_keys:
        for tk in keys.get("spoken", ()):
            if len(tk) >= 3 and pk.startswith(tk):
                return True
        for tk in keys.get("launcher", ()):
            if (len(tk) >= 3 and pk.startswith(tk)) or (len(pk) >= 4 and tk.startswith(pk)):
                return True
    return False


def _is_ultron(proc) -> bool:
    """Ultron himself, his launcher and his own python/node servers are never closed."""
    info = getattr(proc, "info", {}) or {}
    if info.get("pid") in {os.getpid(), os.getppid()}:
        return True
    name = str(info.get("name") or "").lower()
    if not name.startswith(("python", "node", "uvicorn", "npm")):
        return False  # e.g. VS Code with the Ultron folder open is still closable
    try:
        from backend.app.install_paths import ASSET_ROOT

        home = str(ASSET_ROOT)
        cmd = " ".join(str(part) for part in (info.get("cmdline") or []))
        return len(home) > 3 and home in cmd
    except Exception:
        return False


def _closable(proc, name: Optional[str], pid: Optional[int], keys: Optional[dict] = None) -> bool:
    """Only the owner's own, non-system apps that match by name (or exact pid)."""
    try:
        info = proc.info
        pname = str(info.get("name") or "")
        if _is_ultron(proc) or _is_protected(pname):
            return False
        owner = str(info.get("username") or "").lower().split("\\")[-1]
        me = _current_user()
        if not me or owner != me:
            return False  # root/SYSTEM services and other users are never touched
        if pid:
            return info.get("pid") == pid
        return _matches(_process_keys(proc), keys if keys is not None else _target_keys(name), name)
    except Exception:
        return False


def _close_gently(targets: list, name: Optional[str]) -> None:
    """Like clicking X: apps get the chance to save. Windows: WM_CLOSE; Linux: app quit, else SIGTERM."""
    import psutil

    pids = [proc.pid for proc in targets]
    if IS_WINDOWS:
        argv = ["taskkill"]
        for pid in pids[:40]:
            argv += ["/PID", str(pid)]
        try:
            subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)  # noqa: S603
        except (OSError, subprocess.SubprocessError):
            pass
        return
    for proc in targets:
        try:
            proc.terminate()  # SIGTERM: Chrome, VS Code, mpv save state and exit
        except (psutil.Error, OSError):
            pass


def _still_same(proc) -> bool:
    try:
        return proc.is_running() and proc.status() != "zombie"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# PC control: lock, sleep, restart, shutdown, volume, brightness, status
# ---------------------------------------------------------------------------
class PcControlArgs(BaseModel):
    action: Literal["lock", "sleep", "restart", "shutdown", "cancel_shutdown", "volume", "mute", "unmute",
                    "brightness", "status"] = Field(..., description="What to do with the PC.")
    level: Optional[int] = Field(None, ge=0, le=100, description="Percent for volume or brightness.")


class PcControlTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="pc_control",
            name="PC Control",
            description="Lock, sleep, restart or shut down the PC (asks first), set volume/brightness, battery and Wi-Fi status.",
            category="system",
            tags=["lock", "sleep", "shutdown", "restart", "volume", "mute", "brightness", "battery", "wifi"],
            permission_level=1,
            args_model=PcControlArgs,
            usage_examples=["pc_control(action='lock')", "pc_control(action='volume', level=40)", "pc_control(action='status')"],
        )

    def permission_for_arguments(self, arguments: Dict[str, Any]) -> int:
        if arguments.get("action") in {"sleep", "restart", "shutdown"}:
            return 2
        return 0 if arguments.get("action") == "status" else 1

    async def execute(self, **kwargs) -> Dict[str, Any]:
        action = kwargs["action"]
        level = kwargs.get("level")
        if action == "status":
            return await self._status()
        if action in {"volume", "brightness"} and level is None:
            return _fail(f"Say the {action} level from 0 to 100.")
        plans = self._plans(action, level)
        if not plans:
            return _fail(f"'{action}' is not supported on this PC.")
        errors = []
        for argv in plans:
            if not shutil.which(argv[0]):
                continue
            code, out, err = await _run(argv)
            if code == 0:
                data: dict[str, Any] = {"action": action}
                if level is not None:
                    data["level"] = level
                if action in {"restart", "shutdown"}:
                    data["in_seconds"] = 60
                    data["cancel"] = "pc_control(action='cancel_shutdown')"
                return _ok(**data)
            errors.append((err or out).strip()[:200] or f"{argv[0]} exited {code}")
        if not errors:
            return _fail(f"No command for '{action}' is installed on this PC.")
        return _fail(f"'{action}' failed: {errors[-1]}")

    @staticmethod
    def _plans(action: str, level: Optional[int]) -> list[list[str]]:
        if IS_WINDOWS:
            steps = int(level or 0) // 2
            keys = {
                "volume": f"$w=New-Object -ComObject WScript.Shell;1..50|%{{$w.SendKeys([char]174)}};1..{steps}|%{{$w.SendKeys([char]175)}}",
                "mute": "(New-Object -ComObject WScript.Shell).SendKeys([char]173)",
                "unmute": "(New-Object -ComObject WScript.Shell).SendKeys([char]173)",
                "brightness": f"(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods).WmiSetBrightness(1,{level})",
            }
            table = {
                "lock": [["rundll32.exe", "user32.dll,LockWorkStation"]],
                "sleep": [["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]],
                "restart": [["shutdown", "/r", "/t", "60"]],
                "shutdown": [["shutdown", "/s", "/t", "60"]],
                "cancel_shutdown": [["shutdown", "/a"]],
            }
            if action in keys:
                return [_powershell(keys[action])]
            return table.get(action, [])
        pct = f"{level}%"
        return {
            "lock": [["loginctl", "lock-session"], ["xdg-screensaver", "lock"], ["gnome-screensaver-command", "-l"]],
            "sleep": [["systemctl", "suspend"]],
            "restart": [["shutdown", "-r", "+1"], ["systemctl", "reboot"]],
            "shutdown": [["shutdown", "-h", "+1"], ["systemctl", "poweroff"]],
            "cancel_shutdown": [["shutdown", "-c"]],
            "volume": [["pactl", "set-sink-volume", "@DEFAULT_SINK@", pct], ["amixer", "-q", "sset", "Master", pct]],
            "mute": [["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"], ["amixer", "-q", "sset", "Master", "mute"]],
            "unmute": [["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], ["amixer", "-q", "sset", "Master", "unmute"]],
            "brightness": [
                ["brightnessctl", "-q", "set", pct],
                ["gdbus", "call", "--session", "--dest", "org.gnome.SettingsDaemon.Power", "--object-path",
                 "/org/gnome/SettingsDaemon/Power", "--method", "org.freedesktop.DBus.Properties.Set",
                 "org.gnome.SettingsDaemon.Power.Screen", "Brightness", f"<int32 {level}>"],
            ],
        }.get(action, [])

    @staticmethod
    async def _status() -> Dict[str, Any]:
        import psutil

        data: dict[str, Any] = {}
        battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if battery:
            data["battery_percent"] = round(battery.percent)
            data["charging"] = bool(battery.power_plugged)
        else:
            data["battery"] = "no battery (desktop PC)"
        if IS_WINDOWS:
            code, out, _ = await _run(["netsh", "wlan", "show", "interfaces"])
            ssid = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.M) if code == 0 else None
            signal = re.search(r"^\s*Signal\s*:\s*(\d+)%", out, re.M) if code == 0 else None
            data["wifi"] = {"connected": bool(ssid), "name": ssid.group(1).strip() if ssid else None,
                            "signal": int(signal.group(1)) if signal else None}
        elif shutil.which("nmcli"):
            code, out, _ = await _run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"])
            active = next((line.split(":") for line in out.splitlines() if line.startswith("yes:")), None)
            data["wifi"] = {"connected": bool(active), "name": active[1] if active else None,
                            "signal": int(active[2]) if active and active[2].isdigit() else None}
        net = psutil.net_if_stats()
        data["online_interfaces"] = sorted(name for name, st in net.items() if st.isup and not name.lower().startswith("lo"))[:4]
        return _ok(**data)


# ---------------------------------------------------------------------------
# Files: open, show in folder, biggest, recent / by type
# ---------------------------------------------------------------------------
class FileActionsArgs(BaseModel):
    action: Literal["open", "reveal", "biggest", "recent"] = Field(..., description="open a file/folder in its app, reveal it in the file manager, biggest files, or recent files.")
    path: Optional[str] = Field(None, max_length=1000, description="File or folder (name or path). Default for biggest/recent: home.")
    ext: Optional[str] = Field(None, max_length=20, description="Only this type for recent/biggest, e.g. 'pdf'.")
    days: int = Field(7, ge=1, le=3650, description="recent: modified within this many days.")
    limit: int = Field(10, ge=1, le=50)


class FileActionsTool(BaseTool):
    SKIP = {"node_modules", "__pycache__", ".git", ".venv", "venv", "site-packages", "appdata",
            "$recycle.bin", "windows", "program files", "program files (x86)", "programdata", "proc", "sys",
            "snap", ".cache", "cache", "temp", "tmp"}

    def __init__(self) -> None:
        super().__init__(
            tool_id="file_actions",
            name="File Actions",
            description="Open a file or folder in its default app, show it in the file manager, find the biggest or recent files (by type).",
            category="filesystem",
            tags=["open file", "show in folder", "biggest files", "large files", "recent files", "pdf from last week"],
            permission_level=1,
            args_model=FileActionsArgs,
            usage_examples=["file_actions(action='open', path='resume.pdf')", "file_actions(action='recent', ext='pdf', days=7)"],
        )

    def permission_for_arguments(self, arguments: Dict[str, Any]) -> int:
        return 0 if arguments.get("action") in {"biggest", "recent"} else 1

    async def execute(self, **kwargs) -> Dict[str, Any]:
        action = kwargs["action"]
        raw = str(kwargs.get("path") or "").strip()
        path = Path(os.path.expandvars(raw)).expanduser() if raw else Path.home()
        if action in {"open", "reveal"}:
            if not raw:
                return _fail("Say which file or folder.")
            if not path.exists():
                return _fail(f"'{raw}' was not found. Use locate_path first.")
            return await asyncio.to_thread(self._open, path, action == "reveal")
        if not path.is_dir():
            return _fail(f"'{raw}' is not a folder.")
        ext = str(kwargs.get("ext") or "").lower().lstrip(".") or None
        return await asyncio.to_thread(self._scan, path, action, ext, int(kwargs.get("days") or 7), int(kwargs.get("limit") or 10))

    @staticmethod
    def _open(path: Path, reveal: bool) -> Dict[str, Any]:
        try:
            if IS_WINDOWS:
                if reveal:
                    _spawn(["explorer.exe", f"/select,{path}"])
                else:
                    os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                opener = shutil.which("xdg-open") or shutil.which("open")
                if not opener:
                    return _fail("xdg-open is not installed.")
                if reveal and shutil.which("nautilus") and path.is_file():
                    _spawn(["nautilus", "--select", str(path)])
                else:
                    _spawn([opener, str(path.parent if reveal and path.is_file() else path)])
        except OSError as exc:
            return _fail(f"Could not open {path.name}: {exc}")
        return _ok(opened=str(path), revealed=reveal)

    def _scan(self, root: Path, action: str, ext: Optional[str], days: int, limit: int) -> Dict[str, Any]:
        started, seen = time.monotonic(), 0
        since = time.time() - days * 86400
        found: list[tuple[float, str, int, float]] = []
        stack = [root]
        while stack and time.monotonic() - started < 5.0 and seen < 300_000:
            current = stack.pop()
            try:
                entries = list(os.scandir(current))
            except OSError:
                continue
            for entry in entries:
                if entry.name.startswith(".") or entry.name.lower() in self.SKIP:
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                        continue
                    if ext and not entry.name.lower().endswith("." + ext):
                        continue
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                seen += 1
                if action == "recent" and info.st_mtime < since:
                    continue
                score = info.st_size if action == "biggest" else info.st_mtime
                found.append((score, entry.path, info.st_size, info.st_mtime))
        found.sort(reverse=True)
        files = [
            {"path": p, "size_mb": round(size / 1_048_576, 1),
             "modified": datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")}
            for _, p, size, mtime in found[:limit]
        ]
        return _ok(folder=str(root), files=files, scanned=seen, complete=not stack)


# ---------------------------------------------------------------------------
# Clipboard
# ---------------------------------------------------------------------------
class ClipboardArgs(BaseModel):
    action: Literal["read", "write", "save"] = Field("read", description="read what was copied, write text to the clipboard, or save the clipboard into a note file.")
    text: Optional[str] = Field(None, max_length=20000, description="Text to copy (write).")


def _clip_commands(write: bool) -> list[list[str]]:
    if IS_WINDOWS:
        return [_powershell("$input | Set-Clipboard" if write else "Get-Clipboard -Raw")]
    if write:
        return [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
    return [["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "--clipboard", "--output"]]


class ClipboardTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="clipboard",
            name="Clipboard",
            description="Read what the owner copied, copy text for them, or save the clipboard into Documents/Ultron/clipboard-notes.md.",
            category="system",
            tags=["clipboard", "copy", "paste", "what did i copy"],
            permission_level=0,
            args_model=ClipboardArgs,
            usage_examples=["clipboard(action='read')", "clipboard(action='write', text='hello')"],
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action") or "read"
        write = action == "write"
        if write and not kwargs.get("text"):
            return _fail("Give the text to copy.")
        for argv in _clip_commands(write):
            if not shutil.which(argv[0]):
                continue
            code, out, err = await _run(argv, stdin=kwargs.get("text") if write else None)
            if code != 0:
                continue
            if write:
                return _ok(copied_chars=len(kwargs["text"]))
            text = out.strip("\r\n")
            if action == "save":
                from backend.app.security.path_locator import home_folder

                note = (home_folder("Documents") or Path.home()) / "Ultron" / "clipboard-notes.md"
                note.parent.mkdir(parents=True, exist_ok=True)
                stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                with note.open("a", encoding="utf-8") as handle:
                    handle.write(f"\n## {stamp}\n\n{text}\n")
                return _ok(saved_to=str(note), chars=len(text))
            return _ok(text=text[:4000], chars=len(text), truncated=len(text) > 4000)
        tip = "" if IS_WINDOWS else " Install wl-clipboard (Wayland) or xclip."
        return _fail("Clipboard is not reachable on this PC." + tip)


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------
class ScreenshotArgs(BaseModel):
    open_after: bool = Field(False, description="Open the picture after saving.")
    question: str = Field("", description="Look and answer, e.g. 'read the error'. Empty = only save.")
    image_path: str = Field("", description="Look at this image file instead of taking a screenshot.")


class ScreenshotTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="screenshot",
            name="Screenshot",
            description=("Take a screenshot (saved to Pictures/Ultron) and, with a question, LOOK at it: "
                         "read errors, explain what is on screen. Also looks at any image file."),
            category="system",
            tags=["screenshot", "screen shot", "capture screen", "snap", "what's on my screen", "see",
                  "look", "read this error", "vision", "image"],
            permission_level=1,
            args_model=ScreenshotArgs,
            usage_examples=["screenshot()", "screenshot(question='read the error on screen')",
                            "screenshot(image_path='~/Pictures/photo.jpg', question='what is this?')"],
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        question = str(kwargs.get("question") or "").strip()
        image_path = str(kwargs.get("image_path") or "").strip()
        if image_path:
            return await self._look_at_file(image_path, question)
        shot = await self._capture(bool(kwargs.get("open_after")))
        if not shot["success"] or not question:
            return shot
        return await self._look(Path(shot["data"]["saved_to"]), question, shot["data"])

    _MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
             ".gif": "image/gif", ".bmp": "image/bmp", ".heic": "image/heic"}

    async def _look_at_file(self, raw: str, question: str) -> Dict[str, Any]:
        path = Path(os.path.expandvars(raw)).expanduser()
        if not path.is_file():
            return _fail(f"No image file at {path}.")
        if path.suffix.lower() not in self._MIME:
            return _fail(f"{path.name} is not a picture I can look at (png, jpg, webp, gif, bmp).")
        return await self._look(path, question or "What is in this picture?", {"image": str(path)})

    async def _look(self, path: Path, question: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Send the picture to the vision model; the saved file is kept either way."""
        from backend.app.router import get_orchestrator

        try:
            image = await asyncio.to_thread(path.read_bytes)
            answer = await get_orchestrator().router.look_at_image(
                image, self._MIME.get(path.suffix.lower(), "image/png"), question)
        except Exception as exc:  # no key, offline, busy: say it plainly
            return _fail(f"I have the picture but could not look at it: {exc}", **data)
        return _ok(**data, question=question, seen=answer)

    async def _capture(self, open_after: bool) -> Dict[str, Any]:
        from backend.app.security.path_locator import home_folder

        folder = (home_folder("Pictures") or Path.home() / "Pictures") / "Ultron"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"screenshot-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        if IS_WINDOWS:
            script = (
                "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
                "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;"
                "$i=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
                "$g=[System.Drawing.Graphics]::FromImage($i);$g.CopyFromScreen($b.Left,$b.Top,0,0,$i.Size);"
                f"$i.Save('{target}');"
            )
            plans = [_powershell(script)]
        else:
            t = str(target)
            plans = [["gnome-screenshot", "-f", t], ["spectacle", "-b", "-n", "-o", t], ["grim", t],
                     ["scrot", t], ["import", "-window", "root", t]]
        for argv in plans:
            if not shutil.which(argv[0]):
                continue
            code, _out, err = await _run(argv, timeout=20)
            if code == 0 and target.exists() and target.stat().st_size > 0:
                if open_after:
                    await asyncio.to_thread(FileActionsTool._open, target, False)
                return _ok(saved_to=str(target), size_kb=round(target.stat().st_size / 1024))
        return _fail("No screenshot program worked. On Ubuntu install gnome-screenshot.")


# ---------------------------------------------------------------------------
# Desktop notification
# ---------------------------------------------------------------------------
class NotifyArgs(BaseModel):
    title: str = Field("Ultron", max_length=80)
    message: str = Field(..., min_length=1, max_length=400)


class NotifyTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="notify",
            name="Desktop Notification",
            description="Show a desktop pop-up notification.",
            category="system",
            tags=["notify", "notification", "popup", "alert me"],
            permission_level=0,
            args_model=NotifyArgs,
            usage_examples=["notify(message='Build finished')"],
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        title, message = str(kwargs.get("title") or "Ultron"), str(kwargs["message"])
        if IS_WINDOWS:
            safe = lambda s: s.replace("'", "''").replace("<", " ").replace(">", " ")  # noqa: E731
            script = (
                "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]>$null;"
                "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(1);"
                f"$x=$t.GetElementsByTagName('text');$x.Item(0).AppendChild($t.CreateTextNode('{safe(title)}: {safe(message)}'))>$null;"
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Ultron').Show("
                "[Windows.UI.Notifications.ToastNotification]::new($t))"
            )
            argv = _powershell(script)
        else:
            argv = ["notify-send", "-a", "Ultron", title, message]
        if not shutil.which(argv[0]):
            return _fail("Desktop notifications are not available (install libnotify-bin).")
        code, out, err = await _run(argv)
        return _ok(shown=True) if code == 0 else _fail((err or out).strip()[:200] or "notification failed")
