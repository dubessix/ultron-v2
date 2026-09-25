"""Recent folders - Jarvis remembers "that folder" (V2 Step 5).

A tiny JSON list (max 30 paths) under the data dir. Used to:
  * resolve "that folder" / "same folder" / "wahi folder" / "last folder"
  * break ties when two folders share a name (the recently used one wins)
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

MAX_ITEMS = 30
_lock = threading.Lock()

# Spoken references to the last folder used.
_REFERENCE = re.compile(
    r"^(?:(?:that|this|the|same|last|previous|wahi|wohi|oi|sei|same wala)\s+)+"
    r"(?:folder|directory|dir|jagah|place|one)?$|^(?:there|wahan|wahin|last|it|oikhane)$",
    re.IGNORECASE,
)


def _store() -> Path:
    from backend.app.runtime_paths import runtime_data_path

    return runtime_data_path("recent_folders.json")


def _key(name: str) -> str:
    return re.sub(r"[\s_\-.]+", "", str(name).lower())


def _load() -> list[dict]:
    try:
        data = json.loads(_store().read_text(encoding="utf-8"))
        return [item for item in data if isinstance(item, dict) and item.get("path")]
    except (OSError, ValueError):
        return []


def remember(path: str | os.PathLike) -> None:
    """Record a folder the owner just used (files record their parent folder)."""
    try:
        target = Path(path)
        if target.is_file():
            target = target.parent
        if not target.is_dir():
            return
        text = str(target)
    except OSError:
        return
    norm = os.path.normcase(text)
    with _lock:
        items = [item for item in _load() if os.path.normcase(item["path"]) != norm]
        items.insert(0, {"path": text, "key": _key(target.name), "used_at": time.time()})
        store = _store()
        try:
            store.parent.mkdir(parents=True, exist_ok=True)
            tmp = store.with_suffix(".tmp")
            tmp.write_text(json.dumps(items[:MAX_ITEMS], indent=1), encoding="utf-8")
            os.replace(tmp, store)
        except OSError:
            pass


def recent(limit: int = MAX_ITEMS) -> list[str]:
    return [item["path"] for item in _load() if Path(item["path"]).is_dir()][:limit]


def last() -> Optional[str]:
    items = recent(1)
    return items[0] if items else None


def is_reference(spoken: str) -> bool:
    """True for 'that folder', 'same folder', 'wahi folder', 'last folder', 'there'."""
    return bool(_REFERENCE.match(" ".join(str(spoken or "").split())))


def rank_of(path: str) -> Optional[int]:
    """0 = most recent; None = not recent."""
    norm = os.path.normcase(str(path))
    for index, item in enumerate(recent()):
        if os.path.normcase(item) == norm:
            return index
    return None


def clear() -> None:
    with _lock:
        try:
            _store().unlink()
        except OSError:
            pass
