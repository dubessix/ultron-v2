"""Verified local music controls using an owned player process when available."""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import signal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.app.tools import media_control
from backend.app.tools.tool_base import BaseTool


class PlayMusicArgs(BaseModel):
    filepath: str = Field(..., description="Approved MP3/WAV/OGG path to play.")


class EmptyArgs(BaseModel):
    pass


class VolumeArgs(BaseModel):
    level: int = Field(50, ge=0, le=100)


class LocalMusicPlayerController:
    def __init__(self) -> None:
        self.playlist: List[str] = []
        self.current_idx = 0
        self.is_playing = False
        self.is_paused = False
        self.proc: Optional[Any] = None
        self.player: Optional[str] = None

    def add_track(self, filepath: str) -> None:
        if filepath not in self.playlist:
            self.playlist.append(filepath)
        self.current_idx = self.playlist.index(filepath)

    def owns_playing(self) -> bool:
        return bool(self.proc and self.proc.returncode is None and self.is_playing and not self.is_paused)

    def owns_paused(self) -> bool:
        return bool(self.proc and self.proc.returncode is None and self.is_paused)

    def get_current_track(self) -> Optional[str]:
        if not self.playlist or not self.is_playing:
            return None
        return os.path.basename(self.playlist[self.current_idx])

    @staticmethod
    def _player_command(filepath: str):
        candidates = [
            ("mpv", ["--no-video", "--really-quiet", filepath]),
            ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet", filepath]),
            ("cvlc", ["--play-and-exit", "--intf", "dummy", filepath]),
            ("vlc", ["--play-and-exit", "--intf", "dummy", filepath]),
        ]
        for name, args in candidates:
            executable = shutil.which(name)
            if executable:
                return executable, args
        return None, None

    async def play(self, filepath: str) -> Dict[str, Any]:
        executable, args = self._player_command(filepath)
        if not executable:
            return {"success": False, "error": "No controllable player found (mpv/ffplay/vlc)."}
        await self.stop()
        try:
            self.proc = await asyncio.create_subprocess_exec(
                executable,
                *args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
            await asyncio.sleep(0.1)
            if self.proc.returncode not in (None, 0):
                exit_code = self.proc.returncode
                self.proc = None
                return {"success": False, "error": f"Player exited with code {exit_code}"}
            self.add_track(filepath)
            self.player = executable
            self.is_playing = True
            self.is_paused = False
            return {"success": True, "player": executable, "pid": self.proc.pid}
        except OSError as exc:
            self.proc = None
            return {"success": False, "error": f"Player start failed: {exc}"}

    async def stop(self) -> Dict[str, Any]:
        if self.proc and self.proc.returncode is None:
            try:
                if os.name != "nt":
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
                else:
                    self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=3.0)
            except (OSError, asyncio.TimeoutError):
                try:
                    self.proc.kill()
                    await self.proc.wait()
                except (OSError, ProcessLookupError):
                    pass
        was_playing = self.is_playing
        self.proc = None
        self.is_playing = False
        self.is_paused = False
        return {"success": True, "was_playing": was_playing}

    async def pause(self) -> Dict[str, Any]:
        if not self.proc or self.proc.returncode is not None or not self.is_playing:
            return {"success": False, "error": "No owned music process is playing."}
        if os.name == "nt":
            return {"success": False, "error": "Verified pause is unavailable for this player on Windows."}
        try:
            os.kill(self.proc.pid, signal.SIGSTOP)
            self.is_paused = True
            return {"success": True}
        except OSError as exc:
            return {"success": False, "error": f"Pause failed: {exc}"}

    async def resume(self) -> Dict[str, Any]:
        if not self.proc or self.proc.returncode is not None or not self.is_paused:
            return {"success": False, "error": "No owned paused music process exists."}
        if os.name == "nt":
            return {"success": False, "error": "Verified resume is unavailable for this player on Windows."}
        try:
            os.kill(self.proc.pid, signal.SIGCONT)
            self.is_paused = False
            return {"success": True}
        except OSError as exc:
            return {"success": False, "error": f"Resume failed: {exc}"}

    async def change_track(self, offset: int) -> Dict[str, Any]:
        if not self.playlist:
            return {"success": False, "error": "Playlist is empty."}
        self.current_idx = (self.current_idx + offset) % len(self.playlist)
        return await self.play(self.playlist[self.current_idx])


_player_controller = LocalMusicPlayerController()


class PlayMusicTool(BaseTool):
    def __init__(self) -> None:
        super().__init__("play_music", "Music Player", "Plays a local audio file through an owned controllable player.", "music", ["music", "play", "audio", "song", "mp3"], 1, PlayMusicArgs, ["play_music(filepath='music/song.mp3')"])

    async def execute(self, **kwargs) -> Dict[str, Any]:
        filepath = kwargs.get("filepath", "")
        from backend.app.security.path_guard import check_path
        decision = check_path(filepath)
        if not decision["safe"]:
            return {"success": False, "error": f"Audio path blocked ({decision['reason']}): {filepath}", "data": {}}
        if not os.path.isfile(filepath):
            return {"success": False, "error": f"Audio file does not exist: {filepath}", "data": {}}
        result = await _player_controller.play(filepath)
        if not result["success"]:
            return {"success": False, "error": result["error"], "data": {"status": "unavailable"}}
        return {"success": True, "data": {"status": "playing", "current_track": _player_controller.get_current_track(), "player": result["player"], "pid": result["pid"]}, "error": None}


class PauseMusicTool(BaseTool):
    def __init__(self) -> None:
        super().__init__("pause_music", "Music Pauser", "Pauses whatever is playing (YouTube/Spotify in the browser, any player) and checks it paused.", "music", ["music", "pause"], 1, EmptyArgs, ["pause_music()"])

    async def execute(self, **kwargs) -> Dict[str, Any]:
        if _player_controller.owns_playing():
            result = await _player_controller.pause()
            return {"success": result["success"], "data": {"status": "paused", "player": "Ultron"} if result["success"] else {}, "error": result.get("error")}
        return await asyncio.to_thread(media_control.control, "pause")

class ResumeMusicTool(BaseTool):
    def __init__(self) -> None:
        super().__init__("resume_music", "Music Resumer", "Resumes the paused player (browser, Spotify, any player).", "music", ["music", "resume"], 1, EmptyArgs, ["resume_music()"])

    async def execute(self, **kwargs) -> Dict[str, Any]:
        if _player_controller.owns_paused():
            result = await _player_controller.resume()
            return {"success": result["success"], "data": {"status": "playing", "player": "Ultron"} if result["success"] else {}, "error": result.get("error")}
        return await asyncio.to_thread(media_control.control, "play")

class NextTrackTool(BaseTool):
    def __init__(self) -> None:
        super().__init__("next_track", "Next Track", "Next track/video in whatever is playing.", "music", ["music", "next"], 1, EmptyArgs, ["next_track()"])

    async def execute(self, **kwargs) -> Dict[str, Any]:
        if _player_controller.owns_playing() and len(_player_controller.playlist) > 1:
            result = await _player_controller.change_track(1)
            return {"success": result["success"], "data": {"current_track": _player_controller.get_current_track()} if result["success"] else {}, "error": result.get("error")}
        return await asyncio.to_thread(media_control.control, "next")

class PreviousTrackTool(BaseTool):
    def __init__(self) -> None:
        super().__init__("previous_track", "Previous Track", "Previous track in whatever is playing.", "music", ["music", "previous"], 1, EmptyArgs, ["previous_track()"])

    async def execute(self, **kwargs) -> Dict[str, Any]:
        if _player_controller.owns_playing() and len(_player_controller.playlist) > 1:
            result = await _player_controller.change_track(-1)
            return {"success": result["success"], "data": {"current_track": _player_controller.get_current_track()} if result["success"] else {}, "error": result.get("error")}
        return await asyncio.to_thread(media_control.control, "previous")

class StopMusicTool(BaseTool):
    def __init__(self) -> None:
        super().__init__("stop_music", "Music Stopper", "Stops the owned player process.", "music", ["music", "stop"], 1, EmptyArgs, ["stop_music()"])

    async def execute(self, **kwargs) -> Dict[str, Any]:
        if _player_controller.owns_playing() or _player_controller.owns_paused():
            result = await _player_controller.stop()
            return {"success": True, "data": {"status": "stopped", "was_playing": result["was_playing"]}, "error": None}
        result = await asyncio.to_thread(media_control.control, "pause")
        if not result["success"] and ("players" in (result.get("data") or {}) or "gdbus" in str(result.get("error"))):
            return {"success": True, "data": {"status": "stopped", "was_playing": False}, "error": None}
        return result

class CurrentTrackTool(BaseTool):
    def __init__(self) -> None:
        super().__init__("current_track", "Current Track Inspector", "What is playing now (any player).", "music", ["music", "current", "track"], 0, EmptyArgs, ["current_track()"])

    async def execute(self, **kwargs) -> Dict[str, Any]:
        track = _player_controller.get_current_track()
        if track and (_player_controller.owns_playing() or _player_controller.owns_paused()):
            return {"success": True, "data": {"status": "paused" if _player_controller.is_paused else "playing", "current_track": track, "player": "Ultron"}, "error": None}
        return await asyncio.to_thread(media_control.now_playing)

class SetVolumeTool(BaseTool):
    def __init__(self) -> None:
        super().__init__("set_volume", "System Volume Controller", "Sets system volume when a verified mixer is available.", "music", ["music", "volume", "sound"], 1, VolumeArgs, ["set_volume(level=80)"])

    async def execute(self, **kwargs) -> Dict[str, Any]:
        level = max(0, min(100, int(kwargs.get("level", 50))))
        if platform.system() == "Windows":
            return {"success": False, "data": {"status": "unavailable"}, "error": "Use pc_control volume on Windows."}
        options = [
            ("wpctl", ["set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{level / 100:.2f}"]),
            ("pactl", ["set-sink-volume", "@DEFAULT_SINK@", f"{level}%"]),
            ("amixer", ["-q", "sset", "Master", f"{level}%"]),
        ]
        last_error, tried = "No volume mixer found (wpctl, pactl or amixer).", False
        for name, args in options:
            executable = shutil.which(name)
            if not executable:
                continue
            tried = True
            try:
                proc = await asyncio.create_subprocess_exec(executable, *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
                _out, err = await asyncio.wait_for(proc.communicate(), timeout=5)
            except (OSError, asyncio.TimeoutError) as exc:
                last_error = f"{name} failed: {exc}"
                continue
            if proc.returncode == 0:
                return {"success": True, "data": {"status": "verified", "level": level, "mixer": name}, "error": None}
            last_error = err.decode("utf-8", "ignore")[:300] or f"{name} exited {proc.returncode}"
        return {"success": False, "data": {"status": "failed" if tried else "unavailable"}, "error": last_error}
