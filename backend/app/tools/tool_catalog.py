"""Jarvis Core tool menu: every tool, one short line, zero tool imports.

Why this exists
---------------
Sending every tool's full JSON schema on every turn costs ~7.7K tokens, which
is the whole Groq free-tier per-minute budget (8K TPM). Keyword pre-selection
(the old approach) was cheap but left the model with one or two tools, so
multi-step jobs ("clean my desktop and zip the screenshots") were impossible.

The menu below lists ALL tools as compact one-liners (~1K tokens). The model
reads it, decides on its own, and calls any tool through the single universal
``use_tool`` function. Full schemas are only sent for the few tools the
prompt obviously needs; after the first ``use_tool`` call of a tool, its full
schema is attached for the rest of the job.

Rule: this module must stay import-free of tool modules (plain chat and
prompt assembly must not load tool code). A test checks every registered
tool id has exactly one menu line.
"""

from __future__ import annotations

import json
from typing import Iterable

# (group, [(tool_id, "args: purpose"), ...]). "?" marks an optional argument.
TOOL_MENU: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Files and folders (locate_path turns a name into a path)",
        (
            ("locate_path", "name ('that folder'=last used), ?kind: find a FOLDER by name; choices -> ask which"),
            ("list_contents", "folderpath: list files and subfolders"),
            ("find_files", "pattern, ?search_root, ?file_type, ?sort: find FILES by name (movie, pdf, song)"),
            ("search_inside_documents", "search_query, ?file_extensions: text inside files"),
            ("file_read", "filepath: read a text file"),
            ("file_write", "filepath, content: write or patch a file"),
            ("create_folder", "folderpath: make a folder"),
            ("rename_folder", "old_path, new_path: rename a folder"),
            ("copy_folder", "source_path, destination_path: copy a folder"),
            ("move_folder", "source_path, destination_path: move a folder"),
            ("delete_folder", "folderpath: delete a folder (needs approval)"),
            ("organize_folder", "folderpath: sort files into subfolders by type"),
            ("compress_folder", "folderpath, ?archive_format=zip|tar|gztar: zip a folder"),
            ("extract_zip", "zippath, extract_to: unzip an archive"),
            ("convert_file_format", "source_filepath, destination_filepath: JSON<->CSV"),
            ("download_file", "url, save_path: download a file"),
            ("universal_search", "query: files, tasks, reminders, memories"),
        ),
    ),
    (
        "PC and apps",
        (
            ("apps", "action=open|close|running, ?name, ?pid, ?force: installed APPS by name"),
            ("pc_control", "action=lock|sleep|restart|shutdown|cancel_shutdown|volume|mute|unmute|brightness|status, ?level"),
            ("file_actions", "action=open|reveal|biggest|recent, ?path, ?ext, ?days: open a FILE/video"),
            ("clipboard", "action=read|write|save, ?text"),
            ("screenshot", "(none): save the screen to Pictures/Ultron"),
            ("notify", "message, ?title: desktop pop-up"),
            ("routine", "name ('coding mode'), ?action=list: saved steps"),
            ("jarvis_actions", "action=log|undo|undo_list|trusted|revoke, ?day, ?id"),
            ("terminal_run", "command, ?cwd, ?mode=wait|background|status|stop, ?job_id: shell"),
            ("system_metrics", "(none): CPU, RAM, disk, uptime"),
            ("set_volume", "?level"),
            ("open_calculator", "(none)"),
            ("open_chrome", "(none)"),
            ("open_vscode", "?path"),
            ("show_widget", "widget_id, ?action=open|close|close_all, ?refresh: screen panel (todo, calendar, file_explorer, weather...)"),
        ),
    ),
    (
        "Day planning",
        (
            ("manage_reminder", "action=create|list|snooze|dismiss|delete, ?title, ?target_time +10m or ISO, ?reminder_id"),
            ("manage_task", "action=create|list|update_status|update_priority|delete, ?title, ?priority, ?status, ?due_date, ?task_id"),
            ("manage_calendar", "action=create|plan|mark|shift|list|delete, ?title, ?start_time, ?end_time, ?blocks, ?minutes, ?event_id"),
            ("daily_briefing", "(none): weather, tasks, schedule, news"),
            ("manage_memory", "action=search|remember|list|forget|correct, ?content, ?memory_id: past chats, owner facts"),
            ("weather_tool", "?city: live weather and forecast"),
        ),
    ),
    (
        "Web",
        (
            ("google_search", "query: live web results to answer from"),
            ("news_search", "?query, ?count<=10: current headlines"),
            ("tavily_research", "query: deeper multi-source research"),
            ("read_current_page", "?url, ?which: text of open tab or url"),
            ("open_url", "url: open a website"),
            ("open_new_tab", "url"),
            ("refresh_page", "(none)"),
            ("browser_back", "(none)"),
            ("browser_forward", "(none)"),
            ("close_tab", "?which: tab in front or by name"),
            ("close_browser", "(none): all tabs"),
            ("browser_tabs", "?action=list|switch|mute|unmute|sleep|reopen|dedupe|history, ?which"),
            ("image_search", "query: open an image search"),
            ("video_search", "query: open a YouTube search"),
            ("reddit_search", "query"),
            ("stackoverflow_search", "query"),
            ("github_search", "query: open a GitHub search"),
            ("world_monitor", "endpoint=list_earthquakes|list_market_quotes|get_fear_greed_index|get_country_risk|get_internet_outages|get_oil_opec_prices|list_protests|list_military_flights"),
        ),
    ),
    (
        "Music",
        (
            ("spotify_play", "query: play a song on Spotify"),
            ("spotify_playlist", "playlist_name: play a Spotify playlist"),
            ("spotify_search_artist", "query: open an artist on Spotify"),
            ("spotify_pause", "(none)"),
            ("spotify_resume", "(none)"),
            ("spotify_next", "(none)"),
            ("spotify_prev", "(none)"),
            ("spotify_set_volume", "?level 0-100"),
            ("spotify_current_track", "(none)"),
            ("open_spotify", "(none): open the Spotify app"),
            ("play_music", "filepath: play a local audio file"),
            ("pause_music", "(none): pause any player, browser too"),
            ("resume_music", "(none)"),
            ("next_track", "(none)"),
            ("previous_track", "(none)"),
            ("stop_music", "(none)"),
            ("current_track", "(none)"),
        ),
    ),
    (
        "Code and developer",
        (
            ("git_status", "?directory: branch and changed files"),
            ("git_clone", "url, ?directory: clone a repository"),
            ("github_integration", "action=commit_push|create_repo|create_pr|list_issues|search_code, ?repo_name, ?commit_message"),
            ("optimize_code", "filepath: review and improve a source file"),
            ("semantic_code_graph", "?query_type=build|search|callers|dependencies|summary, ?target_symbol"),
            ("security_scan", "scan for leaked secrets and risky processes"),
            ("database_restore", "backup_path: restore Ultron's database"),
        ),
    ),
)

USE_TOOL_ID = "use_tool"


def menu_tool_ids() -> list[str]:
    return [tool_id for _, items in TOOL_MENU for tool_id, _ in items]


def build_tool_menu(registered_ids: Iterable[str], exclude: Iterable[str] = ()) -> str:
    """Compact text menu of every registered tool not already declared natively.

    Unknown / custom tools registered at runtime still appear (without a hint),
    so nothing the registry can run is ever invisible to the model.
    """
    registered = list(dict.fromkeys(registered_ids))
    registered_set = set(registered)
    skip = set(exclude)
    lines: list[str] = []
    listed: set[str] = set()
    for group, items in TOOL_MENU:
        entries = [
            f"{tool_id}({hint})" if not hint.startswith("(") else f"{tool_id}{hint}"
            for tool_id, hint in items
            if tool_id in registered_set and tool_id not in skip
        ]
        listed.update(tool_id for tool_id, _ in items)
        if entries:
            lines.append(f"# {group}\n" + "\n".join(entries))
    extras = [tool_id for tool_id in registered if tool_id not in listed and tool_id not in skip]
    if extras:
        lines.append("# Other\n" + "\n".join(extras))
    return "\n".join(lines)


def use_tool_metadata(registered_ids: Iterable[str]) -> dict:
    """Metadata for the universal meta-tool, in the orchestrator tool format.

    ``arguments_json`` is a JSON *string* (not a free object) because Gemini
    rejects OBJECT parameters without declared properties; every provider
    handles a string reliably.
    """
    del registered_ids  # kept for API symmetry; ids live in the menu
    return {
        "tool_id": USE_TOOL_ID,
        "description": (
            "Run ANY tool from the TOOL MENU in the system prompt. Put the tool id in "
            "'tool' and its arguments as a JSON object string in 'arguments_json', "
            "e.g. tool='compress_folder', arguments_json='{\"folderpath\": \"/home/me/Desktop/shots\"}'. "
            "If arguments are wrong, the result shows the exact schema; fix and retry."
        ),
        "permission_level": 0,
        "input_schema": {
            "type": "object",
            "properties": {
                # No enum: the id list is already in the cached menu, and an
                # unknown id gets a did-you-mean reply. Saves ~350 tokens/call.
                "tool": {"type": "string", "description": "Tool id from the TOOL MENU."},
                "arguments_json": {
                    "type": "string",
                    "description": "Arguments as a JSON object string. Use '{}' when the tool takes none.",
                },
            },
            "required": ["tool", "arguments_json"],
        },
    }


def parse_use_tool_call(arguments: dict) -> tuple[str, dict, str | None]:
    """Unwrap a use_tool call -> (real_tool_id, real_arguments, error).

    Tolerates the common model variants: a dict under ``arguments``/``args``,
    a JSON string, or the tool's arguments flattened next to ``tool``.
    """
    if not isinstance(arguments, dict):
        return "", {}, "use_tool arguments must be an object with 'tool' and 'arguments_json'."
    tool_id = str(arguments.get("tool") or arguments.get("tool_id") or arguments.get("name") or "").strip()
    if not tool_id:
        return "", {}, "use_tool needs 'tool': the tool id from the menu."
    raw = None
    for key in ("arguments_json", "arguments", "args", "parameters"):
        if key in arguments:
            raw = arguments[key]
            break
    if raw is None:
        flattened = {
            key: value
            for key, value in arguments.items()
            if key not in {"tool", "tool_id", "name"}
        }
        return tool_id, flattened, None
    if isinstance(raw, dict):
        return tool_id, raw, None
    if raw in ("", None):
        return tool_id, {}, None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            return tool_id, {}, f"arguments_json is not valid JSON ({exc.msg}). Send a JSON object string."
        if isinstance(parsed, dict):
            return tool_id, parsed, None
    return tool_id, {}, "arguments_json must be a JSON object, e.g. '{\"query\": \"...\"}'."
