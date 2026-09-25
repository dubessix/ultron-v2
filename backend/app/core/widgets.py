"""Which widget (panel) the screen shows - decided by the AI, not letter matching.

Priority (orchestrator step 12):
  1. The AI called show_widget(...)                -> exactly that.
  2. A tool ran whose result has a panel          -> open it (refresh=True when
     the tool changed data, so an open panel reloads).
  3. Fallback without tools: the owner explicitly asked ("show my calendar",
     "open downloads") -> whole-word match only. Old substring guessing opened
     the calendar for "explain" and the system panel for "program".
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

# id -> short purpose (also the AI's menu for show_widget)
WIDGETS: dict[str, str] = {
    "todo": "tasks and to-do list",
    "calendar": "calendar and schedule",
    "reminder": "reminders and alarms",
    "file_explorer": "files and folders",
    "system": "CPU, RAM, disk, battery",
    "weather": "weather forecast",
    "music": "music player",
    "terminal": "terminal output",
    "memory": "long-term memory",
    "notification": "notifications",
    "daily_briefing": "daily briefing",
    "universal_search": "search results",
    "deep_research": "research results",
    "world_monitor": "world news and events",
    "market": "stocks and crypto prices",
    "git": "git status",
    "git_clone": "clone a repository",
    "github_search": "GitHub search",
    "coding": "coding workspace",
    "code_optimizer": "code quality review",
    "semantic_code_graph": "code graph",
    "security_guardian": "security scan",
}

# tool id -> widget that shows its result
TOOL_WIDGETS: dict[str, str] = {
    "find_files": "file_explorer", "locate_path": "file_explorer", "list_contents": "file_explorer",
    "create_folder": "file_explorer", "rename_folder": "file_explorer", "delete_folder": "file_explorer",
    "copy_folder": "file_explorer", "move_folder": "file_explorer", "compress_folder": "file_explorer",
    "extract_zip": "file_explorer", "organize_folder": "file_explorer",
    "manage_task": "todo", "manage_calendar": "calendar", "manage_reminder": "reminder",
    "manage_memory": "memory", "daily_briefing": "daily_briefing",
    "security_scan": "security_guardian", "optimize_code": "code_optimizer",
    "semantic_code_graph": "semantic_code_graph", "git_status": "git", "github_integration": "git",
    "git_clone": "git_clone", "github_search": "github_search",
    "system_metrics": "system", "weather_tool": "weather", "terminal_run": "terminal",
    "universal_search": "universal_search", "tavily_research": "deep_research",
    "world_monitor": "world_monitor",
    "play_music": "music", "pause_music": "music", "resume_music": "music", "next_track": "music",
    "previous_track": "music", "stop_music": "music", "current_track": "music",
    "spotify_play": "music", "spotify_playlist": "music", "spotify_search_artist": "music",
    "spotify_pause": "music", "spotify_resume": "music", "spotify_next": "music",
    "spotify_prev": "music", "spotify_current_track": "music", "open_spotify": "music",
}

# Actions that change stored data -> an already-open panel must reload.
_CHANGING_ACTIONS = {"create", "update", "update_status", "update_priority", "delete",
                     "snooze", "dismiss", "remember", "forget", "correct", "smart_schedule"}
_ALWAYS_REFRESH = {"create_folder", "rename_folder", "delete_folder", "copy_folder", "move_folder",
                   "compress_folder", "extract_zip", "organize_folder", "git_clone", "github_integration",
                   "list_contents", "locate_path"}  # File Explorer follows where Ultron works

# Fallback words (whole words only) -> widget
_WORDS: tuple[tuple[str, str], ...] = (
    (r"to-?dos?|todo list|tasks?", "todo"),
    (r"reminders?|alarms?|timers?|remind", "reminder"),
    (r"calendar|schedule|agenda", "calendar"),
    (r"git|branch(?:es)?", "git"),
    (r"[a-z] drive|drive|downloads|documents|desktop|explorer|folders?|files", "file_explorer"),
    (r"research", "deep_research"),
    (r"search", "universal_search"),
    (r"weather|forecast", "weather"),
    (r"stocks?|bitcoin|crypto|market|share prices?", "market"),
    (r"terminal|console", "terminal"),
    (r"memory|memories", "memory"),
    (r"notifications?|alerts?", "notification"),
    (r"system|cpu|ram|hardware|battery", "system"),
    (r"music|player|songs?", "music"),
    (r"world monitor|world news", "world_monitor"),
    (r"security", "security_guardian"),
    (r"briefing", "daily_briefing"),
)
_SHOW = re.compile(r"\b(show|open|display|pull up|bring up|launch|view|see|dikhao|kholo|dekhao)\b", re.I)


def _entry(action: str, widget_id: Optional[str] = None, refresh: bool = False) -> dict:
    result: dict = {"action": action}
    if widget_id:
        result["widget_id"] = widget_id
    if refresh:
        result["refresh"] = True
    return result


def explicit_request(prompt: str) -> dict:
    """Fallback when no tool ran: only an explicit, whole-word panel request."""
    text = " ".join(str(prompt or "").lower().split())
    if not text:
        return _entry("none")
    has_show = bool(_SHOW.search(text))
    first_word = text.split(" ", 1)[0].strip(",.!?")
    for pattern, widget in _WORDS:
        match = re.search(rf"\b(?:{pattern})\b", text)
        if not match:
            continue
        if has_show or re.fullmatch(rf"(?:{pattern})", first_word):
            return _entry("open_widget", widget)
    return _entry("none")


def from_tool_results(tool_results: Iterable[dict]) -> Optional[dict]:
    """1. AI's own show_widget choice (last one wins); 2. panel of the last useful tool."""
    results = [item for item in tool_results or [] if isinstance(item, dict)]
    for item in reversed(results):
        if item.get("tool") == "show_widget" and item.get("success"):
            data = item.get("result") or {}
            action = data.get("action") or "open_widget"
            return _entry(action, data.get("widget_id"), bool(data.get("refresh")))
    for item in reversed(results):
        tool = str(item.get("tool") or "")
        widget = TOOL_WIDGETS.get(tool)
        if not widget or not item.get("success"):
            continue
        args = item.get("args") or {}
        changed = tool in _ALWAYS_REFRESH or str(args.get("action") or "").lower() in _CHANGING_ACTIONS
        return _entry("open_widget", widget, changed)
    return None


def from_tool_ids(called_tool_ids: Iterable[str]) -> Optional[dict]:
    """Older paths only know tool ids (no results)."""
    for tool in called_tool_ids or []:
        if tool in TOOL_WIDGETS:
            return _entry("open_widget", TOOL_WIDGETS[tool])
    return None
