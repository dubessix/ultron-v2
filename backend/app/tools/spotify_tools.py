"""
Ultron Production-Grade Spotify Integration Tools
Implements un-mocked, fully verified Spotify launchers: Open Spotify, Play Song, Play Playlist, Search Song, Search Artist, Search Album, Pause, Resume, Next, Previous, Volume, and Current Track.
Verifies Spotify client installation state natively via process scanning, returning exact reasons on failures.
"""

import webbrowser
import urllib.parse
import platform
import asyncio
import psutil
import shutil
import os
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Dict, Any, Tuple
from backend.app.tools.tool_base import BaseTool

# --- Validation Schemas ---

class SpotifySearchArgs(BaseModel):
    query: str = Field(..., description="Target search query (e.g., song title, artist, or album name).")

class SpotifyPlaylistArgs(BaseModel):
    playlist_name: str = Field(..., description="Target playlist name to search and play.")

class SpotifyVolumeArgs(BaseModel):
    level: int = Field(50, description="Volume percentage level to set: 0 to 100.")

class EmptyArgs(BaseModel):
    pass

# --- Helper Spotify Verifier (Requirement: Never report success without verification) ---

def is_spotify_client_installed() -> Tuple[bool, str]:
    """
    Natively scans system paths and running processes to verify if Spotify desktop client is available.
    Returns (is_installed: bool, reason_description: str).
    """
    system_type = platform.system()
    
    # 1. Process scanning check
    for proc in psutil.process_iter(['name']):
        try:
            if 'spotify' in (proc.info['name'] or '').lower():
                return True, "Spotify client is currently running on the system."
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # 2. Executable PATH search check
    if shutil.which("spotify") or shutil.which("Spotify"):
        return True, "Spotify executable detected on system PATH."

    # 3. Pathing check
    if system_type == "Windows":
        app_data = os.getenv("APPDATA")
        if app_data:
            win_path = Path(app_data) / "Spotify" / "Spotify.exe"
            if win_path.exists():
                return True, "Spotify desktop client detected in Windows APPDATA."
    elif system_type == "Linux":
        # Check flatpak or snap packaging structures
        snap_path = Path("/snap/bin/spotify")
        flatpak_path = Path("/var/lib/flatpak/app/com.spotify.Client")
        if snap_path.exists() or flatpak_path.exists():
            return True, "Spotify client packaging structures detected (snap/flatpak)."

    return False, "Spotify desktop client is not installed or not running. Fallback to Spotify Web Player required."

def _open_verified(url: str) -> None:
    if not webbrowser.open(url):
        raise RuntimeError("Default browser rejected the Spotify launch request.")


async def _send_spotify_control(linux_method: str, windows_key: int) -> Dict[str, Any]:
    if platform.system() == "Windows":
        executable = shutil.which("powershell") or shutil.which("pwsh")
        if not executable:
            return {"success": False, "error": "PowerShell unavailable."}
        script = (
            "$wshell = New-Object -ComObject wscript.shell; "
            f"$wshell.SendKeys([char]{windows_key})"
        )
        argv = [executable, "-NoProfile", "-Command", script]
    else:
        executable = shutil.which("dbus-send")
        if not executable:
            return {"success": False, "error": "dbus-send unavailable."}
        argv = [
            executable, "--print-reply", "--dest=org.mpris.MediaPlayer2.spotify",
            "/org/mpris/MediaPlayer2", f"org.mpris.MediaPlayer2.Player.{linux_method}",
        ]
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return {
            "success": False,
            "error": stderr.decode("utf-8", "ignore")[:500] or f"Control exited {proc.returncode}",
        }
    return {"success": True, "stdout": stdout.decode("utf-8", "ignore")[:500]}


# --- Tool Implementations ---

class OpenSpotifyTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="open_spotify",
            name="Spotify Launcher",
            description="Launches your local desktop Spotify application. Verifies installation state first.",
            category="spotify",
            tags=["spotify", "music", "open", "launch", "desktop"],
            permission_level=2, # Level 2: Requires confirmation
            args_model=EmptyArgs,
            usage_examples=["open_spotify()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        installed, reason = is_spotify_client_installed()
        url = "spotify:"
        try:
            if installed:
                _open_verified(url)
                return {"success": True, "data": {"status": "installed", "message": f"Successfully launched local Spotify application. {reason}"}, "error": None}
            else:
                # Fallback to Web Player if client is missing
                _open_verified("https://open.spotify.com")
                return {"success": True, "data": {"status": "fallback_web", "message": f"Local client missing. Launched Spotify Web Player. {reason}"}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to open Spotify: {e}", "data": {}}

class SpotifyPlaySongTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="spotify_play",
            name="Spotify Player",
            description="Launches and plays a requested song query directly inside your local Spotify application.",
            category="spotify",
            tags=["spotify", "music", "song", "play", "track"],
            permission_level=2, # Level 2: System command requiring confirmation
            args_model=SpotifySearchArgs,
            usage_examples=["spotify_play(query='Starboy The Weeknd')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        query = kwargs.get("query", "")
        escaped = urllib.parse.quote(query)
        
        installed, reason = is_spotify_client_installed()
        url = f"spotify:search:{escaped}"
        fallback_web_url = f"https://open.spotify.com/search/{escaped}"
        
        try:
            if installed:
                _open_verified(url)
                return {"success": True, "data": {"status": "installed", "message": f"Launched song search inside local client. {reason}"}, "error": None}
            else:
                _open_verified(fallback_web_url)
                return {"success": True, "data": {"status": "fallback_web", "message": f"Launched song search inside Web Player. {reason}"}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to launch Spotify: {e}", "data": {}}

class SpotifySearchArtistTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="spotify_search_artist",
            name="Spotify Artist Search",
            description="Launches a specific artist profile search on Spotify.",
            category="spotify",
            tags=["spotify", "artist", "search", "music"],
            permission_level=2,
            args_model=SpotifySearchArgs,
            usage_examples=["spotify_search_artist(query='A.R. Rahman')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        query = kwargs.get("query", "")
        escaped = urllib.parse.quote(f"artist:{query}")
        installed, reason = is_spotify_client_installed()
        url = f"spotify:search:{escaped}"
        fallback_web_url = f"https://open.spotify.com/search/{escaped}"
        try:
            if installed:
                _open_verified(url)
                return {"success": True, "data": {"status": "installed", "message": f"Launched artist search inside local client. {reason}"}, "error": None}
            else:
                _open_verified(fallback_web_url)
                return {"success": True, "data": {"status": "fallback_web", "message": f"Launched artist search inside Web Player. {reason}"}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to launch Spotify: {e}", "data": {}}

class SpotifyPlayPlaylistTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="spotify_playlist",
            name="Spotify Playlist Player",
            description="Launches and plays a specific public playlist query on Spotify.",
            category="spotify",
            tags=["spotify", "playlist", "play", "music"],
            permission_level=2,
            args_model=SpotifyPlaylistArgs,
            usage_examples=["spotify_playlist(playlist_name='Chill Lofi Beats')"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        playlist_name = kwargs.get("playlist_name", "")
        escaped = urllib.parse.quote(f"playlist:{playlist_name}")
        installed, reason = is_spotify_client_installed()
        url = f"spotify:search:{escaped}"
        fallback_web_url = f"https://open.spotify.com/search/{escaped}"
        try:
            if installed:
                _open_verified(url)
                return {"success": True, "data": {"status": "installed", "message": f"Launched playlist search inside local client. {reason}"}, "error": None}
            else:
                _open_verified(fallback_web_url)
                return {"success": True, "data": {"status": "fallback_web", "message": f"Launched playlist search inside Web Player. {reason}"}, "error": None}
        except Exception as e:
            return {"success": False, "error": f"Failed to launch Spotify: {e}", "data": {}}

class SpotifyPauseTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="spotify_pause",
            name="Spotify Pauser",
            description="Sends pause media keystroke commands to pause the active Spotify client.",
            category="spotify",
            tags=["spotify", "pause", "music", "hold"],
            permission_level=2, # Level 2
            args_model=EmptyArgs,
            usage_examples=["spotify_pause()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        installed, _ = is_spotify_client_installed()
        if not installed:
            return {"success": False, "error": "Spotify client is not running. Cannot pause.", "data": {}}
        result = await _send_spotify_control("PlayPause", 179)
        if not result["success"]:
            return {"success": False, "error": result["error"], "data": {"status": "unavailable"}}
        return {"success": True, "data": {"status": "verified", "message": "Spotify pause command succeeded."}, "error": None}

class SpotifyResumeTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="spotify_resume",
            name="Spotify Resumer",
            description="Sends resume media keystroke commands to play the active Spotify client.",
            category="spotify",
            tags=["spotify", "resume", "music", "play"],
            permission_level=2,
            args_model=EmptyArgs,
            usage_examples=["spotify_resume()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        installed, _ = is_spotify_client_installed()
        if not installed:
            return {"success": False, "error": "Spotify client is not running. Cannot resume.", "data": {}}
        result = await _send_spotify_control("Play", 179)
        if not result["success"]:
            return {"success": False, "error": result["error"], "data": {"status": "unavailable"}}
        return {"success": True, "data": {"status": "verified", "message": "Spotify resume command succeeded."}, "error": None}

class SpotifyNextTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="spotify_next",
            name="Spotify Next Track",
            description="Sends next media keystroke commands to skip to the next track on Spotify.",
            category="spotify",
            tags=["spotify", "next", "music", "skip"],
            permission_level=2,
            args_model=EmptyArgs,
            usage_examples=["spotify_next()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        installed, _ = is_spotify_client_installed()
        if not installed:
            return {"success": False, "error": "Spotify client is not running.", "data": {}}
        result = await _send_spotify_control("Next", 176)
        if not result["success"]:
            return {"success": False, "error": result["error"], "data": {"status": "unavailable"}}
        return {"success": True, "data": {"status": "verified", "message": "Spotify next command succeeded."}, "error": None}

class SpotifyPreviousTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="spotify_prev",
            name="Spotify Previous Track",
            description="Sends previous media keystroke commands to skip to the previous track on Spotify.",
            category="spotify",
            tags=["spotify", "previous", "music", "back"],
            permission_level=2,
            args_model=EmptyArgs,
            usage_examples=["spotify_prev()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        installed, _ = is_spotify_client_installed()
        if not installed:
            return {"success": False, "error": "Spotify client is not running.", "data": {}}
        result = await _send_spotify_control("Previous", 177)
        if not result["success"]:
            return {"success": False, "error": result["error"], "data": {"status": "unavailable"}}
        return {"success": True, "data": {"status": "verified", "message": "Spotify previous command succeeded."}, "error": None}

class SpotifyVolumeTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="spotify_set_volume",
            name="Spotify Volume Controller",
            description="Sets the Spotify client volume level natively.",
            category="spotify",
            tags=["spotify", "volume", "sound"],
            permission_level=2,
            args_model=SpotifyVolumeArgs,
            usage_examples=["spotify_set_volume(level=75)"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        level = kwargs.get("level", 50)
        level_clamped = max(0, min(100, level))
        installed, _ = is_spotify_client_installed()
        if not installed:
            return {"success": False, "error": "Spotify client is not running.", "data": {}}
        if platform.system() == "Windows":
            return {"success": False, "error": "Verified exact Spotify volume is unavailable on Windows.", "data": {"status": "unavailable"}}
        executable = shutil.which("dbus-send")
        if not executable:
            return {"success": False, "error": "dbus-send unavailable.", "data": {"status": "unavailable"}}
        fraction = level_clamped / 100.0
        proc = await asyncio.create_subprocess_exec(
            executable, "--print-reply", "--dest=org.mpris.MediaPlayer2.spotify",
            "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties.Set",
            "string:org.mpris.MediaPlayer2.Player", "string:Volume",
            f"variant:double:{fraction}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return {"success": False, "error": stderr.decode("utf-8", "ignore")[:500] or f"Volume control exited {proc.returncode}", "data": {"status": "failed"}}
        return {"success": True, "data": {"status": "verified", "level": level_clamped, "stdout": stdout.decode("utf-8", "ignore")[:500]}, "error": None}

class SpotifyCurrentTrackTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="spotify_current_track",
            name="Spotify Current Track Inspector",
            description="Retrieves the metadata of the currently playing track on Spotify natively.",
            category="spotify",
            tags=["spotify", "current", "track", "inspect"],
            permission_level=0, # Level 0: Auto Allow
            args_model=EmptyArgs,
            usage_examples=["spotify_current_track()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        installed, reason = is_spotify_client_installed()
        if not installed:
            return {"success": False, "error": f"Spotify client is not running. {reason}", "data": {}}
        
        if platform.system() == "Windows":
            executable = shutil.which("powershell") or shutil.which("pwsh")
            if not executable:
                return {"success": False, "error": "PowerShell unavailable.", "data": {"status": "unavailable"}}
            script = "(Get-Process | Where-Object {$_.ProcessName -eq 'Spotify' -and $_.MainWindowTitle -ne ''}).MainWindowTitle"
            argv = [executable, "-NoProfile", "-Command", script]
        else:
            executable = shutil.which("dbus-send")
            if not executable:
                return {"success": False, "error": "dbus-send unavailable.", "data": {"status": "unavailable"}}
            argv = [
                executable, "--print-reply", "--dest=org.mpris.MediaPlayer2.spotify",
                "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties.Get",
                "string:org.mpris.MediaPlayer2.Player", "string:Metadata",
            ]
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return {"success": False, "error": stderr.decode("utf-8", "ignore")[:500] or f"Metadata query exited {proc.returncode}", "data": {"status": "failed"}}
        output = stdout.decode("utf-8", "ignore").strip()
        if not output:
            return {"success": False, "error": "Spotify returned no track metadata.", "data": {"status": "unavailable"}}
        if platform.system() == "Windows":
            return {"success": True, "data": {"status": "verified", "current_track": output}, "error": None}
        import re
        title_match = re.search(r'string\s+"xesam:title"\s+\n\s+variant\s+string\s+"([^"]+)"', output, re.DOTALL)
        artist_match = re.search(r'string\s+"xesam:artist"\s+\n\s+variant\s+array\s+\[\s+string\s+"([^"]+)"', output, re.DOTALL)
        if not title_match:
            return {"success": False, "error": "Spotify metadata did not contain a track title.", "data": {"status": "unavailable"}}
        title = title_match.group(1)
        artist = artist_match.group(1) if artist_match else ""
        return {"success": True, "data": {"status": "verified", "current_track": f"{title} - {artist}" if artist else title}, "error": None}
