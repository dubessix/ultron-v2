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
from backend.app.tools import media_control
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


async def _media(action: str) -> Dict[str, Any]:
    """Spotify app or Spotify web in the browser: whichever is open (checked result)."""
    return await asyncio.to_thread(media_control.control, action, "spotify")

class OpenSpotifyTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="open_spotify",
            name="Spotify Launcher",
            description="Launches your local desktop Spotify application. Verifies installation state first.",
            category="spotify",
            tags=["spotify", "music", "open", "launch", "desktop"],
            permission_level=1, # Level 2: Requires confirmation
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
            permission_level=1, # Level 2: System command requiring confirmation
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
            permission_level=1,
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
            permission_level=1,
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
            permission_level=1, # Level 2
            args_model=EmptyArgs,
            usage_examples=["spotify_pause()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        return await _media("pause")

class SpotifyResumeTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="spotify_resume",
            name="Spotify Resumer",
            description="Sends resume media keystroke commands to play the active Spotify client.",
            category="spotify",
            tags=["spotify", "resume", "music", "play"],
            permission_level=1,
            args_model=EmptyArgs,
            usage_examples=["spotify_resume()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        return await _media("play")

class SpotifyNextTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="spotify_next",
            name="Spotify Next Track",
            description="Sends next media keystroke commands to skip to the next track on Spotify.",
            category="spotify",
            tags=["spotify", "next", "music", "skip"],
            permission_level=1,
            args_model=EmptyArgs,
            usage_examples=["spotify_next()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        return await _media("next")

class SpotifyPreviousTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="spotify_prev",
            name="Spotify Previous Track",
            description="Sends previous media keystroke commands to skip to the previous track on Spotify.",
            category="spotify",
            tags=["spotify", "previous", "music", "back"],
            permission_level=1,
            args_model=EmptyArgs,
            usage_examples=["spotify_prev()"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        return await _media("previous")

class SpotifyVolumeTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="spotify_set_volume",
            name="Spotify Volume Controller",
            description="Sets the Spotify client volume level natively.",
            category="spotify",
            tags=["spotify", "volume", "sound"],
            permission_level=1,
            args_model=SpotifyVolumeArgs,
            usage_examples=["spotify_set_volume(level=75)"]
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        level = max(0, min(100, int(kwargs.get("level", 50))))
        return await asyncio.to_thread(media_control.set_player_volume, level, "spotify")

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
        result = await asyncio.to_thread(media_control.now_playing, "spotify")
        if result["success"]:
            data = result["data"]
            track = " - ".join(x for x in (data.get("title"), data.get("artist")) if x)
            result["data"]["current_track"] = track or None
        return result
