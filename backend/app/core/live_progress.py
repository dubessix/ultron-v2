"""Ultron talks while he works (V2 Step C7), like IRIS / Stonic.

Every tool step is shown at once on the screen as one short line ("Opening
Downloads"). It is spoken only when it matters:
  * the brain wrote its own short line with the tool call -> spoken if the step
    is still going after PREAMBLE_SECONDS, or
  * the step is still running after SLOW_SECONDS (so long jobs are never silent).
Quick jobs and "ask first" steps stay quiet until the one answer: no chatter,
no delay, never "Closing Chrome" before "Should I close Chrome?".
Lines are built from the tool and its arguments: zero extra tokens, no extra
AI call. Plain words only (the voice never reads symbols). Never raises.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

SLOW_SECONDS = 2.5
PREAMBLE_SECONDS = 1.0
_manager: Any = None


def set_manager(manager: Any) -> None:
    """main.py hands over its WebSocket manager at import time."""
    global _manager
    _manager = manager


async def publish(event: dict) -> None:
    if _manager is None:
        return
    try:
        await _manager.broadcast("events", event)
    except Exception:
        pass


def _plain(value: Any, limit: int = 40) -> str:
    """Speakable words: last part of a path, no symbols, short."""
    text = str(value or "").strip()
    if re.search(r"[\\/]", text) and " " not in text.strip("\\/"):
        text = re.split(r"[\\/]+", text.rstrip("\\/"))[-1] or text
    text = re.sub(r"https?://(www\.)?", "", text)
    text = re.sub(r"[^\w\s.,'-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .,-")
    return text[:limit].rsplit(" ", 1)[0] if len(text) > limit else text


def line_for(tool_id: str, args: Optional[dict] = None) -> str:
    """One short line saying what Ultron is doing right now."""
    a = args or {}
    name = _plain(a.get("name") or a.get("which") or "")
    action = str(a.get("action") or "")
    lines = {
        "apps": {"open": f"Opening {name or 'the app'}", "close": f"Closing {name or 'the app'}",
                 "running": "Checking what is running"}.get(action, "Working with your apps"),
        "terminal_run": {"status": "Checking the job", "stop": "Stopping the job"}.get(
            str(a.get("mode") or ""), f"Running {_plain(a.get('command'), 36) or 'the command'}"),
        "find_files": f"Looking for {_plain(a.get('pattern')) or 'the files'}",
        "locate_path": f"Finding the {_plain(a.get('name')) or 'folder'} folder",
        "list_contents": f"Looking inside {_plain(a.get('folderpath')) or 'the folder'}",
        "file_read": f"Reading {_plain(a.get('filepath') or a.get('path')) or 'the file'}",
        "file_write": f"Writing {_plain(a.get('filepath') or a.get('path')) or 'the file'}",
        "file_actions": f"Opening {_plain(a.get('path')) or 'the file'}" if action == "open" else "Checking your files",
        "google_search": f"Searching the web for {_plain(a.get('query')) or 'that'}",
        "tavily_research": f"Researching {_plain(a.get('query')) or 'that'}",
        "news_search": "Getting the latest news",
        "weather_tool": "Checking the weather",
        "system_metrics": "Checking your PC",
        "open_url": f"Opening {_plain(a.get('url'), 30) or 'the page'}",
        "open_new_tab": f"Opening {_plain(a.get('url'), 30) or 'a new tab'}",
        "close_tab": f"Closing the {name} tab" if name and name != "current" else "Closing the tab",
        "browser_tabs": {"switch": f"Switching to {name}", "mute": "Muting the tab",
                         "unmute": "Unmuting the tab", "sleep": "Putting tabs to sleep to free memory",
                         "reopen": "Reopening the tab", "dedupe": "Closing duplicate tabs",
                         "history": f"Searching your history for {name}" if name and name != "current"
                         else "Searching your history"}.get(action, "Checking your tabs"),
        "read_current_page": "Reading the page",
        "browser_page": {"look": "Looking at the page", "scroll": "Scrolling",
                         "type": "Typing it in", "click": "Clicking it"}.get(action, "Working on the page"),
        "close_browser": "Closing the browser tabs",
        "download_file": f"Downloading {_plain(a.get('save_path')) or 'the file'}",
        "git_clone": "Cloning the repository",
        "git_status": "Checking git",
        "pause_music": "Pausing", "resume_music": "Resuming", "next_track": "Next track",
        "spotify_pause": "Pausing Spotify", "spotify_resume": "Resuming Spotify",
        "spotify_play": f"Playing {_plain(a.get('query')) or 'it'} on Spotify",
        "manage_reminder": "Setting the reminder" if action == "create" else "Checking your reminders",
        "manage_task": "Updating your tasks", "manage_calendar": "Checking your calendar",
        "pc_control": f"Setting {action}" if action else "Adjusting your PC",
        "screenshot": "Taking a screenshot",
        "routine": f"Starting {_plain(a.get('name')) or 'the routine'}" if action != "list" else "Checking your routines",
        "create_folder": f"Creating {_plain(a.get('folderpath')) or 'the folder'}",
    }
    return lines.get(tool_id) or f"Working on it with {tool_id.replace('_', ' ')}"


def spoken_preamble(content: Any) -> Optional[str]:
    """The brain's own short words next to a tool call, if it wrote any."""
    text = re.sub(r"\s+", " ", str(content or "")).strip()
    if not text or len(text) > 160 or re.search(r"[{}\[\]<>`|\\/*#=_~]|https?:|www\.", text):
        return None  # paths, links, code or markup: the built plain line is used instead
    return text


class Step:
    """One live step: shown now, spoken now (preamble) or when slow."""

    def __init__(self, tool_id: str, args: Optional[dict], session_id: str, preamble: Optional[str] = None):
        self.text = line_for(tool_id, args)
        self.tool_id, self.session_id, self.preamble = tool_id, session_id, preamble
        self._timer: Optional[asyncio.Task] = None

    async def start(self) -> "Step":
        await publish(self._event(self.preamble or self.text, speak=False))
        self._timer = asyncio.create_task(self._speak_if_still_going())
        return self

    async def _speak_if_still_going(self) -> None:
        try:
            await asyncio.sleep(PREAMBLE_SECONDS if self.preamble else SLOW_SECONDS)
            await publish(self._event(self.preamble or self.text, speak=True))
        except asyncio.CancelledError:
            pass

    def done(self) -> None:
        if self._timer is not None and not self._timer.done():
            self._timer.cancel()

    def _event(self, text: str, speak: bool) -> dict:
        return {"type": "ultron_progress", "text": text, "speak": speak,
                "tool": self.tool_id, "session_id": self.session_id}
