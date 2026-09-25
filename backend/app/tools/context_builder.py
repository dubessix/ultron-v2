"""Prompt-scoped tool selection without importing the complete tool catalogue."""

from __future__ import annotations

import json
import re
from typing import ClassVar, Iterable, List, TYPE_CHECKING

from backend.app.tools.tool_base import BaseTool

if TYPE_CHECKING:
    from backend.app.tools.tool_registry import ToolRegistry


class ToolContextBuilder:
    """Choose a small relevant tool slice before any tool module is imported."""

    MAX_RELEVANT_TOOLS = 12

    # Jarvis never goes empty-handed: when keyword scoring finds nothing for an
    # action-style prompt, these universally useful tools are attached so the
    # LLM itself decides (native function calling) instead of being disarmed.
    DEFAULT_UTILITY_IDS: ClassVar[tuple[str, ...]] = (
        "weather_tool",
        "system_metrics",
        "find_files",
        "list_contents",
        "google_search",
        "news_search",
        "play_music",
        "open_url",
        "manage_reminder",
        "manage_task",
        "manage_calendar",
        "locate_path",
    )

    # Lightweight match hints intentionally live outside tool classes. Reading
    # them does not import Pydantic schemas, subprocess helpers, or integrations.
    # Every registered ID is also matched automatically as words (underscores
    # become spaces), so no tool becomes unreachable when wording is explicit.
    _TOOL_MATCH_TERMS: ClassVar[dict[str, tuple[str, ...]]] = {
        "file_read": (
            "read",
            "load",
            "load config",
            "config file",
            "view file",
            "open file",
            "file contents",
        ),
        "file_write": ("write file", "save file", "edit file", "update file", "fix code"),
        "locate_path": (
            "where is", "locate", "find folder", "find my folder", "which folder",
            "folder", "directory", "path of",
        ),
        "find_files": (
            "find file", "find files", "locate file", "glob", "file search",
            "find all", "pdf", "documents",
        ),
        "terminal_run": ("run", "terminal", "shell command", "command line", "pytest"),
        "open_calculator": ("calculator", "calculate", "do the math"),
        "open_chrome": ("open chrome", "launch chrome", "start browser"),
        "open_vscode": ("open vscode", "visual studio code", "launch editor", "open ide"),
        "weather_tool": ("weather", "forecast", "temperature", "rain", "climate"),
        "tavily_research": ("research", "deep research", "web research", "source summary"),
        "git_status": ("git status", "working tree", "uncommitted", "current branch"),
        "git_clone": ("git clone", "clone repo", "clone repository"),
        "system_metrics": ("system metrics", "cpu", "ram", "memory usage", "disk usage", "battery"),
        "create_folder": ("create folder", "make folder", "new directory", "mkdir"),
        "rename_folder": ("rename folder", "rename directory"),
        "delete_folder": ("delete folder", "remove folder", "delete directory", "rmdir"),
        "copy_folder": ("copy folder", "copy directory", "duplicate folder"),
        "move_folder": ("move folder", "move directory"),
        "list_contents": ("list folder", "list directory", "folder contents", "directory contents"),
        "compress_folder": ("compress folder", "zip folder", "archive folder", "tar folder"),
        "extract_zip": ("extract zip", "unzip", "extract archive"),
        "organize_folder": (
            "organize folder", "organise folder", "sort files", "clean folder",
            "organize", "organise", "desktop", "tidy",
        ),
        "open_url": ("open url", "open website", "open web page"),
        "open_new_tab": ("new tab", "open tab"),
        "close_tab": ("close tab",),
        "refresh_page": ("refresh page", "reload page"),
        "browser_back": ("browser back", "previous page", "go back page"),
        "browser_forward": ("browser forward", "next page", "go forward page"),
        "close_browser": ("close browser", "quit browser"),
        "download_file": ("download file", "download url", "fetch file"),
        "read_current_page": ("read page", "read url", "scrape page", "page contents"),
        "google_search": ("google search", "search google", "web search"),
        "github_search": ("github search", "search github", "search repository"),
        "stackoverflow_search": ("stackoverflow", "stack overflow", "coding answer"),
        "reddit_search": ("reddit search", "search reddit", "reddit discussion"),
        "image_search": ("image search", "search images", "find image", "find icon"),
        "news_search": (
            "news search", "latest news", "world news", "news",
            "read the news", "headlines",
        ),
        "video_search": ("video search", "youtube search", "find tutorial", "find video"),
        "play_music": ("play music", "play local song", "play audio file"),
        "pause_music": ("pause music", "pause local music"),
        "resume_music": ("resume music", "resume local music"),
        "next_track": ("next track", "next local song"),
        "previous_track": ("previous track", "previous local song", "previous song", "last song"),
        "stop_music": ("stop music", "stop local music"),
        "set_volume": (
            "set volume", "system volume", "change volume", "volume",
            "increase volume", "lower volume", "louder", "quieter",
        ),
        "current_track": ("current track", "local track", "what is playing locally"),
        "open_spotify": ("open spotify", "launch spotify"),
        "spotify_play": ("spotify play", "play on spotify", "spotify song"),
        "spotify_search_artist": ("spotify artist", "search artist on spotify"),
        "spotify_playlist": ("spotify playlist", "play playlist on spotify"),
        "spotify_pause": ("pause spotify", "spotify pause"),
        "spotify_resume": ("resume spotify", "spotify resume"),
        "spotify_next": ("next spotify track", "spotify next", "skip on spotify"),
        "spotify_prev": ("previous spotify track", "spotify previous"),
        "spotify_set_volume": ("spotify volume", "set spotify volume"),
        "spotify_current_track": ("spotify current track", "what is playing on spotify"),
        "optimize_code": ("optimize code", "optimise code", "refactor code", "code quality"),
        "semantic_code_graph": ("semantic graph", "code graph", "callers", "dependencies", "ast graph"),
        "manage_reminder": ("reminder", "alarm", "remind me", "snooze reminder"),
        "apps": ("open app", "launch", "open whatsapp", "close app", "kill", "slowing", "slow pc", "running apps", "task manager", "kholo", "band karo"),
        "pc_control": ("lock", "sleep", "shutdown", "shut down", "restart", "reboot", "brightness", "mute", "battery", "wifi", "wi-fi"),
        "file_actions": ("open file", "show in folder", "biggest files", "large files", "recent files", "last week", "space"),
        "clipboard": ("clipboard", "copy this", "what did i copy", "paste"),
        "screenshot": ("screenshot", "screen shot", "capture screen", "screen capture"),
        "jarvis_actions": ("what did you do", "undo", "undo that", "wapas karo", "action log", "always allow", "trust rules", "aaj kya kiya"),
        "notify": ("notify", "pop up", "popup", "notification"),
        "show_widget": ("widget", "panel", "on screen", "on my screen", "close all", "clear the screen", "show my", "pull up", "bring up"),
        "manage_task": ("task", "todo", "backlog", "subtask", "task priority"),
        "manage_calendar": ("calendar", "meeting", "time slot", "day planner", "schedule event"),
        "security_scan": ("security scan", "secret scan", "dependency audit", "vulnerability scan"),
        "daily_briefing": ("daily briefing", "morning briefing", "today summary"),
        "manage_memory": ("remember", "forget memory", "correct memory", "memory export", "recall memory"),
        "search_inside_documents": (
            "search inside file",
            "search documents",
            "find text",
            "grep",
            "search source",
        ),
        "convert_file_format": ("convert file", "json to csv", "csv to json", "change file format"),
        "world_monitor": ("world monitor", "earthquake", "geopolitics", "global outage", "world risk"),
        "github_integration": (
            "git commit",
            "git push",
            "pull request",
            "github issue",
            "create repository",
        ),
        "database_restore": ("restore database", "database backup", "restore backup", "database restore"),
        "universal_search": (
            "universal search",
            "search my files tasks reminders",
            "search everything",
            "local search",
        ),
    }

    _CODING_DEFAULTS = (
        "file_read",
        "find_files",
        "file_write",
        "terminal_run",
        "git_status",
    )

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))

    @classmethod
    def _contains_phrase(cls, normalized_prompt: str, phrase: str) -> bool:
        normalized_phrase = cls._normalize(phrase)
        if not normalized_phrase:
            return False
        return f" {normalized_phrase} " in f" {normalized_prompt} "

    @classmethod
    def _prompt_tokens(cls, normalized_prompt: str) -> set[str]:
        """Word tokens PLUS glued adjacent pairs.

        The glue makes natural wording match compact tool vocabulary:
        "open VS Code" -> {open, vs, code, openvs, vscode} hits `open_vscode`;
        "git  status"  -> {gitstatus} hits phrase-style ids too.
        """
        words = normalized_prompt.split()
        tokens = set(words)
        tokens.update(a + b for a, b in zip(words, words[1:]))
        return tokens

    @classmethod
    def select_relevant_tool_ids(
        cls,
        user_prompt: str,
        registered_ids: Iterable[str],
        *,
        coding_turn: bool = False,
        limit: int = MAX_RELEVANT_TOOLS,
    ) -> list[str]:
        """Rank registered IDs with phrase + token evidence, capped at twelve.

        Scoring layers (strongest first):
          1. exact phrase of the tool id                (+100)
          2. every tool-id word present, any order       (+40)
          3. exact phrase of a match term        (+10 + 4/word)
          4. every term word present, any order   (+8 + 3/word)
        Token layers make natural phrasing work: "play some music",
        "search the web", "delete my downloads folder", "open VS Code".
        """
        prompt = cls._normalize(user_prompt)
        if not prompt:
            return []

        ordered_ids = list(dict.fromkeys(registered_ids))
        prompt_tokens = cls._prompt_tokens(prompt)
        scores: dict[str, int] = {}

        for tool_id in ordered_ids:
            id_phrase = tool_id.replace("_", " ")
            id_words = id_phrase.split()
            score = 0
            if cls._contains_phrase(prompt, id_phrase):
                score += 100
            elif len(id_words) > 1 and set(id_words) <= prompt_tokens:
                score += 40
            for term in cls._TOOL_MATCH_TERMS.get(tool_id, ()):
                term_words = cls._normalize(term).split()
                if not term_words:
                    continue
                if cls._contains_phrase(prompt, term):
                    score += 10 + (len(term_words) * 4)
                elif set(term_words) <= prompt_tokens:
                    score += 8 + (len(term_words) * 3)
            if score:
                scores[tool_id] = score

        if coding_turn:
            for tool_id in cls._CODING_DEFAULTS:
                if tool_id in set(ordered_ids):
                    scores[tool_id] = scores.get(tool_id, 0) + 1

        bounded_limit = min(cls.MAX_RELEVANT_TOOLS, max(1, int(limit)))
        order = {tool_id: index for index, tool_id in enumerate(ordered_ids)}
        ranked = sorted(scores, key=lambda tool_id: (-scores[tool_id], order[tool_id]))
        return ranked[:bounded_limit]

    @classmethod
    def default_utility_ids(cls, registered_ids: Iterable[str]) -> list[str]:
        """Registered subset of the always-useful utility belt (bounded)."""
        registered = set(registered_ids)
        return [
            tool_id
            for tool_id in cls.DEFAULT_UTILITY_IDS
            if tool_id in registered
        ][: cls.MAX_RELEVANT_TOOLS]

    def load_relevant_tools(
        self,
        user_prompt: str,
        registry: "ToolRegistry",
        *,
        coding_turn: bool = False,
        limit: int = MAX_RELEVANT_TOOLS,
        allow_defaults: bool = True,
    ) -> list[BaseTool]:
        """JIT-load only the selected tool classes and their argument schemas.

        Jarvis rule: an action-style turn never reaches the LLM with zero tools.
        When scoring selects nothing, the bounded default utility belt is
        attached so the model itself decides whether to call one.
        """
        selected_ids = self.select_relevant_tool_ids(
            user_prompt,
            registry.get_registered_ids(),
            coding_turn=coding_turn,
            limit=limit,
        )
        if not selected_ids and allow_defaults and not coding_turn:
            selected_ids = self.default_utility_ids(registry.get_registered_ids())
        tools = []
        for tool_id in selected_ids:
            tool = registry.get_tool(tool_id)
            if tool is not None:
                tools.append(tool)
        return tools

    def filter_relevant_tools(
        self,
        user_prompt: str,
        registered_tools: List[BaseTool],
    ) -> List[BaseTool]:
        """Compatibility helper for already-loaded custom/test tool collections."""
        selected_ids = self.select_relevant_tool_ids(
            user_prompt,
            (tool.id for tool in registered_tools),
        )
        by_id = {tool.id: tool for tool in registered_tools}
        return [by_id[tool_id] for tool_id in selected_ids if tool_id in by_id]

    def build_system_prompt_fragment(self, relevant_tools: List[BaseTool]) -> str:
        """Assemble a structured fragment from selected tools only."""
        if not relevant_tools:
            return "No local tools are required for this exchange."

        metadata = []
        for tool in relevant_tools:
            item = tool.get_metadata()
            metadata.append(
                {
                    "tool_id": item["id"],
                    "description": item["description"],
                    "permission_level": item["permission_level"],
                    "input_schema": item["input_schema"],
                }
            )
        return json.dumps(metadata, separators=(",", ":"), ensure_ascii=True)
