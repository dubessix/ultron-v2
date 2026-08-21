"""Verified local music controls using an owned player process when available."""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import signal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

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
        super().__init__("play_music", "Music Player", "Plays a local audio file through an owned controllable player.", "music", ["music", "play", "audio", "song", "mp3"], 2, PlayMusicArgs, ["play_music(filepath='music/song.mp3')"])

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
        super().__init__("pause_music", "Music Pauser", "Pauses the owned player process.", "music", ["music", "pause"], 1, EmptyArgs, ["pause_music()"])

    async def execute(self, **kwargs) -> Dict[str, Any]:
        result = await _player_controller.pause()
        return {"success": result["success"], "data": {"status": "paused"} if result["success"] else {"status": "unavailable"}, "error": result.get("error")}


class ResumeMusicTool(BaseTool):
    def __init__(self) -> None:
        super().__init__("resume_music", "Music Resumer", "Resumes the owned paused player.", "music", ["music", "resume"], 1, EmptyArgs, ["resume_music()"])

    async def execute(self, **kwargs) -> Dict[str, Any]:
        result = await _player_controller.resume()
        return {"success": result["success"], "data": {"status": "playing"} if result["success"] else {"status": "unavailable"}, "error": result.get("error")}


class NextTrackTool(BaseTool):
    def __init__(self) -> None:
        super().__init__("next_track", "Next Track", "Plays the next owned playlist track.", "music", ["music", "next"], 1, EmptyArgs, ["next_track()"])

    async def execute(self, **kwargs) -> Dict[str, Any]:
        result = await _player_controller.change_track(1)
        return {"success": result["success"], "data": {"current_track": _player_controller.get_current_track()} if result["success"] else {"status": "unavailable"}, "error": result.get("error")}


class PreviousTrackTool(BaseTool):
    def __init__(self) -> None:
        super().__init__("previous_track", "Previous Track", "Plays the previous owned playlist track.", "music", ["music", "previous"], 1, EmptyArgs, ["previous_track()"])

    async def execute(self, **kwargs) -> Dict[str, Any]:
        result = await _player_controller.change_track(-1)
        return {"success": result["success"], "data": {"current_track": _player_controller.get_current_track()} if result["success"] else {"status": "unavailable"}, "error": result.get("error")}


class StopMusicTool(BaseTool):
    def __init__(self) -> None:
        super().__init__("stop_music", "Music Stopper", "Stops the owned player process.", "music", ["music", "stop"], 1, EmptyArgs, ["stop_music()"])

    async def execute(self, **kwargs) -> Dict[str, Any]:
        result = await _player_controller.stop()
        return {"success": True, "data": {"status": "stopped", "was_playing": result["was_playing"]}, "error": None}


class CurrentTrackTool(BaseTool):
    def __init__(self) -> None:
        super().__init__("current_track", "Current Track Inspector", "Reports the verified owned player state.", "music", ["music", "current", "track"], 0, EmptyArgs, ["current_track()"])

    async def execute(self, **kwargs) -> Dict[str, Any]:
        track = _player_controller.get_current_track()
        if not track:
            return {"success": False, "data": {"status": "stopped"}, "error": "No owned music process is playing."}
        return {"success": True, "data": {"status": "paused" if _player_controller.is_paused else "playing", "current_track": track, "player": _player_controller.player}, "error": None}


class SetVolumeTool(BaseTool):
    def __init__(self) -> None:
        super().__init__("set_volume", "System Volume Controller", "Sets system volume when a verified mixer is available.", "music", ["music", "volume", "sound"], 2, VolumeArgs, ["set_volume(level=80)"])

    async def execute(self, **kwargs) -> Dict[str, Any]:
        level = max(0, min(100, int(kwargs.get("level", 50))))
        if platform.system() == "Windows":
            return {
                "success": False,
                "data": {"status": "unavailable"},
                "error": "Verified exact system-volume control is unavailable on Windows.",
            }
        else:
            executable = shutil.which("amixer")
            if not executable:
                return {"success": False, "data": {"status": "unavailable"}, "error": "amixer unavailable."}
            argv = [executable, "sset", "Master", f"{level}%"]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return {"success": False, "data": {"status": "failed", "stdout": stdout.decode("utf-8", "ignore")[:500]}, "error": stderr.decode("utf-8", "ignore")[:500] or f"Mixer exited {proc.returncode}"}
        return {"success": True, "data": {"status": "verified", "level": level, "mixer": executable}, "error": None}
