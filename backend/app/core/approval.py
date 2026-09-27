"""Jarvis approval rules: ask only when it matters, ask like a human, stay honest.

Personal (non-coding) turns:
  * normal jobs run at once (the owner said it, Ultron does it);
  * Ultron asks only before truly risky steps (see needs_ask);
  * one yes is enough: the AI calls owner_reply(yes) when the owner answers his
    question; that turn's actions then run without a second question (level 3 still asks).
Coding turns keep their exact-confirmation workflow unchanged.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable

# ------------------------------------------------------------ owner answers
# There is no yes/no word list here any more: the AI itself decides whether the
# owner's message answers a question and calls owner_reply (core/control_tools).


def asked_question(last_ai_reply: str) -> bool:
    """Did Ultron's last reply end with a question to the owner?"""
    tail = str(last_ai_reply or "").strip()[-240:]
    return "?" in tail


# ------------------------------------------------------------ when to ask
ALWAYS_ASK_TOOLS = {"delete_folder", "close_browser", "database_restore", "github_integration"}
# Commands that delete, overwrite, install, kill or need admin rights.
RISKY_COMMAND = re.compile(
    r"(^|[\s;&|(])(rm|rmdir|shred|dd|mkfs\S*|fdisk|parted|sudo|su|doas|pkexec|chmod|chown|chgrp|kill|pkill|killall|"
    r"shutdown|reboot|poweroff|halt|systemctl|service|apt|apt-get|dpkg|snap|flatpak|dnf|yum|pacman|"
    r"truncate|mv|format|del|erase|rd|remove-item|stop-process|taskkill|reg|diskpart|crontab)(\s|$)"
    r"|pip3?\s+uninstall|npm\s+(uninstall|rm)\b|git\s+(push|reset\s+--hard|clean|checkout\s+--|branch\s+-D)"
    r"|(^|[^>])>(?!>)\s*[^&\s]",
    re.IGNORECASE,
)


# Apps that hold nothing to save: players, viewers, monitors. Closing them needs no "yes".
NOTHING_TO_SAVE_APPS = frozenset({
    "mpv", "vlc", "totem", "celluloid", "smplayer", "mplayer", "haruna", "videos",
    "rhythmbox", "spotify", "audacious", "lollypop", "amberol", "music",
    "eog", "loupe", "shotwell", "gwenview", "image viewer", "evince", "papers", "okular",
    "document viewer", "gnome-calculator", "calculator", "gnome-system-monitor",
    "system monitor", "nautilus", "files", "gnome-clocks", "clocks", "gnome-weather",
    "weather", "cheese", "snapshot", "camera", "gnome-calendar", "calendar",
})


def _nothing_to_save(app_name: Any) -> bool:
    name = str(app_name or "").strip().lower().replace("\\", "/").rsplit("/", 1)[-1]
    name = name.removesuffix(".desktop").removesuffix(".exe")
    name = name.rsplit(".", 1)[-1] if name.startswith(("org.", "io.", "com.")) else name
    return name in NOTHING_TO_SAVE_APPS


def needs_ask(tool_id: str, arguments: dict, level: int) -> bool:
    """Personal turn: must the owner approve this exact step first?"""
    args = arguments or {}
    if level >= 3 or tool_id in ALWAYS_ASK_TOOLS:
        return True
    action = str(args.get("action") or "").lower()
    if tool_id == "apps" and action == "close":
        return not _nothing_to_save(args.get("name"))  # editors etc. may hold unsaved work
    if tool_id == "pc_control" and action in {"sleep", "restart", "shutdown"}:
        return True
    if tool_id == "terminal_run":
        return bool(RISKY_COMMAND.search(str(args.get("command") or "")))
    if tool_id == "file_write":
        if args.get("content") is None and args.get("search_text"):
            return False  # one exact edit, backed up and undoable
        target = str(args.get("filepath") or "")
        return bool(target) and Path(os.path.expanduser(target)).exists()  # replacing a whole file
    if tool_id == "manage_memory" and action in {"restore", "forget", "correct", "reembed"}:
        return True
    if tool_id == "optimize_code" and args.get("apply_changes"):
        return True
    if tool_id == "browser_page":
        return bool(args.get("confirmed"))  # a send, post, buy or delete: always one yes
    return False


# ------------------------------------------------------------ how to ask
def _name(value: Any) -> str:
    text = str(value or "").rstrip("/\\")
    if not text:
        return "it"
    if text.startswith(("http://", "https://")):
        return re.sub(r"^https?://(www\.)?", "", text).split("/")[0]
    return Path(text).name or text


def _plain_words(value: Any, limit: int = 80) -> str:
    """Words only (voice never reads symbols), cut short."""
    return " ".join(re.sub(r"[^\w\s'.,?!-]", " ", str(value or "")).split())[:limit] or "that"


def describe(tool_id: str, arguments: dict) -> str:
    """One short spoken question, no tool ids or symbols: 'Should I create notes.txt, Sir?'"""
    a = arguments or {}
    action = str(a.get("action") or "").lower()
    if tool_id == "terminal_run":
        command = " ".join(str(a.get("command") or "").split())[:120]
        question = f"Should I run this command: {command}"
    elif tool_id == "file_write":
        target = str(a.get("filepath") or "")
        verb = "replace" if target and Path(os.path.expanduser(target)).exists() else "create"
        question = f"Should I {verb} {_name(target)}"
    elif tool_id == "file_read":
        question = f"Should I read {_name(a.get('filepath'))}"
    elif tool_id == "delete_folder":
        question = f"Should I delete {_name(a.get('folderpath'))}? It goes to the Trash, so you can undo it"
    elif tool_id in {"move_folder", "copy_folder"}:
        verb = "move" if tool_id == "move_folder" else "copy"
        question = f"Should I {verb} {_name(a.get('source_path'))} to {_name(a.get('destination_path'))}"
    elif tool_id == "rename_folder":
        question = f"Should I rename {_name(a.get('old_path'))} to {_name(a.get('new_path'))}"
    elif tool_id == "organize_folder":
        question = f"Should I organize {_name(a.get('folderpath'))}"
    elif tool_id == "extract_zip":
        question = f"Should I unzip {_name(a.get('zippath'))}"
    elif tool_id == "download_file":
        question = f"Should I download the file from {_name(a.get('url'))}"
    elif tool_id == "git_clone":
        question = f"Should I clone {_name(a.get('repo_url') or a.get('url'))}"
    elif tool_id == "convert_file_format":
        question = f"Should I convert {_name(a.get('source_filepath'))}"
    elif tool_id == "optimize_code":
        question = f"Should I apply the code changes to {_name(a.get('filepath'))}"
    elif tool_id == "apps":
        question = f"Should I close {a.get('name') or 'that app'}? Unsaved work there may be lost"
    elif tool_id == "pc_control":
        question = f"Should I {action or 'change'} the PC"
    elif tool_id == "browser_page":
        from backend.app.tools.browser_tools import pending_label

        if action == "type" and a.get("submit"):
            question = f"Should I send this: {_plain_words(a.get('text'))}"
        else:
            label = pending_label(str(a.get("target") or "")) or str(a.get("target") or "that button")
            question = f"Should I press {_plain_words(label)}"
    elif tool_id == "close_browser":
        question = "Should I close the whole browser"
    elif tool_id == "github_integration":
        question = f"Should I {action.replace('_', ' ') or 'make that change'} on GitHub"
    elif tool_id == "database_restore":
        question = "Should I restore my database from the backup"
    elif tool_id == "manage_memory":
        question = f"Should I {action or 'change'} that memory"
    else:
        question = "Should I go ahead with that"
    question = question.rstrip("?")
    return f"{question}, Sir? Say yes or no." if "?" not in question else f"{question}. Say yes or no."


# ------------------------------------------------------------ honesty
_CLAIM = re.compile(
    r"\b(done|closed|opened|created|moved|deleted|written|saved|launched|started|finished|completed|"
    r"renamed|copied|installed|downloaded|sent|played|set|turned|killed|kar diya|ho gaya|hoye geche)\b",
    re.IGNORECASE,
)
_ADMITS = re.compile(r"\b(couldn'?t|could not|can'?t|cannot|failed|unable|not|error|didn'?t|sorry)\b", re.I)


def honest_reply(content: str, tool_results: Iterable[dict]) -> str:
    """Never say 'done' when every tool this turn failed."""
    results = [r for r in tool_results or [] if isinstance(r, dict) and r.get("status") != "PENDING_CONFIRMATION"]
    if not results or any(r.get("success") for r in results):
        return content
    text = str(content or "")
    if text and (_ADMITS.search(text) or not _CLAIM.search(text)):
        return text
    error = ""
    for item in reversed(results):
        error = str(item.get("error") or (item.get("result") or {}).get("error") or "").strip()
        if error:
            break
    error = re.sub(r"\s+", " ", error)[:160].rstrip(".")
    return f"That did not work, Sir. {error}." if error else "That did not work, Sir."
