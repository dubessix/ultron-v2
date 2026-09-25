"""Jarvis approval rules: understand yes/no, ask only when it matters, ask like a human.

Personal (non-coding) turns:
  * normal jobs run at once (the owner said it, Ultron does it);
  * Ultron asks only before truly risky steps (see needs_ask);
  * one yes is enough: if Ultron asked "Should I...?" and the owner answers yes,
    that turn's actions run without a second question (level 3 still asks).
Coding turns keep their exact-confirmation workflow unchanged.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------- yes / no
_FILLER = re.compile(r"\b(ultron|zora|sir|please|pls|plz|bhai|boss|jarvis|dear|then|now|ji)\b")
_YES_START = {
    "yes", "yeah", "yep", "yup", "ya", "yea", "ok", "okay", "okey", "k", "sure", "fine", "alright",
    "go", "do", "proceed", "confirm", "confirmed", "approve", "approved", "right", "correct", "absolutely",
    "haan", "han", "ha", "haa", "theek", "thik", "thick", "karo", "kar", "kardo", "chalo",
    "hya", "hyan", "hae", "ho", "koro", "kor", "done", "definitely", "course", "please",
}
_NO_WORDS = {
    "no", "nope", "nah", "cancel", "stop", "dont", "don't", "not", "never", "nahi", "nahin", "mat",
    "rehne", "rehnedo", "leave", "skip", "wait", "hold", "abort", "na", "naa", "thak", "koro-na", "later",
}
_GENERIC = {
    "it", "that", "this", "them", "those", "do", "does", "go", "ahead", "now", "same", "one", "then", "again",
    "create", "make", "open", "run", "write", "save", "start", "play", "send", "move", "copy", "rename",
    "close", "delete", "remove", "install", "download", "apply", "continue", "finish", "all", "both",
    "karo", "kar", "kardo", "do", "de", "dijiye", "dijye", "diya", "dao", "diye", "koro", "kore", "kor",
    "banao", "bana", "kholo", "khol", "chalao", "chala", "hai", "hain", "ji", "bhai", "haan", "yes", "ok",
    "okay", "sure", "go", "yeah", "please", "right", "away", "fine", "i", "want", "you", "can", "yup",
}
_ALWAYS = {"always", "hamesha", "every time", "sob somoy", "always allow", "allow always"}


def _clean(text: str) -> list[str]:
    low = str(text or "").lower().replace("’", "'")
    low = re.sub(r"[.,!?।;:\"()]+", " ", low)
    low = _FILLER.sub(" ", low)
    return [w for w in low.split() if w]


def reply_intent(text: str) -> Optional[str]:
    """'yes' | 'no' | 'always' | None (None = a real request, send it to the brain).

    Short replies only (<= 6 meaningful words): "ok do", "yes open it", "haan kar do",
    "hya koro", "no", "cancel it". "No, open the other folder" is a new request -> None.
    """
    words = _clean(text)
    if not words or len(words) > 6:
        return None
    phrase = " ".join(words)
    if any(item in phrase for item in _ALWAYS) and not (set(words) & {"no", "not", "never", "dont", "don't"}):
        return "always"
    if words[0] in _NO_WORDS or phrase in {"mat karo", "rehne do", "not now", "no thanks"}:
        return "no" if len(words) <= 3 else None
    if set(words) & (_NO_WORDS - {"na", "wait"}):
        return None  # mixed ("yes but don't...") -> let the brain read it
    if words[0] in _YES_START or phrase in {"go ahead", "do it", "of course", "kar do", "kore dao", "why not"}:
        # "ok close YouTube" is a NEW command, not a yes: after the yes word only
        # general words may follow ("ok do", "yes create it", "haan kar do").
        if all(w in _YES_START or w in _GENERIC for w in words[1:]):
            return "yes"
    return None


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


def needs_ask(tool_id: str, arguments: dict, level: int) -> bool:
    """Personal turn: must the owner approve this exact step first?"""
    args = arguments or {}
    if level >= 3 or tool_id in ALWAYS_ASK_TOOLS:
        return True
    action = str(args.get("action") or "").lower()
    if tool_id == "apps" and action == "close":
        return True  # unsaved work may be lost
    if tool_id == "pc_control" and action in {"sleep", "restart", "shutdown"}:
        return True
    if tool_id == "terminal_run":
        return bool(RISKY_COMMAND.search(str(args.get("command") or "")))
    if tool_id == "file_write":
        target = str(args.get("filepath") or "")
        return bool(target) and Path(os.path.expanduser(target)).exists()  # replacing a file
    if tool_id == "manage_memory" and action in {"restore", "forget", "correct", "reembed"}:
        return True
    if tool_id == "optimize_code" and args.get("apply_changes"):
        return True
    return False


# ------------------------------------------------------------ how to ask
def _name(value: Any) -> str:
    text = str(value or "").rstrip("/\\")
    if not text:
        return "it"
    if text.startswith(("http://", "https://")):
        return re.sub(r"^https?://(www\.)?", "", text).split("/")[0]
    return Path(text).name or text


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
