"""Undo journal - "Ultron, undo that" (V2 Step 7).

Reversible file actions (delete to trash, move, rename, organize, create,
copy) record exactly what changed. undo_last() reverses the newest one that
is not undone yet. Small JSON file (last 50 actions) under the data dir.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

MAX_ITEMS = 50
_lock = threading.Lock()


def _store() -> Path:
    from backend.app.runtime_paths import runtime_data_path

    return runtime_data_path("undo_journal.json")


def _load() -> list[dict]:
    try:
        data = json.loads(_store().read_text(encoding="utf-8"))
        return [item for item in data if isinstance(item, dict)]
    except (OSError, ValueError):
        return []


def _save(items: list[dict]) -> None:
    store = _store()
    store.parent.mkdir(parents=True, exist_ok=True)
    tmp = store.with_suffix(".tmp")
    tmp.write_text(json.dumps(items[:MAX_ITEMS], indent=1), encoding="utf-8")
    os.replace(tmp, store)


def record(kind: str, summary: str, **details) -> dict:
    """kind: trash | move | rename | organize | create | copy."""
    entry = {"id": uuid.uuid4().hex[:10], "kind": kind, "summary": summary, "at": time.time(),
             "undone": False, **details}
    with _lock:
        items = _load()
        items.insert(0, entry)
        try:
            _save(items)
        except OSError:
            pass
    return entry


def recent(limit: int = 10) -> list[dict]:
    return _load()[:limit]


def _reverse(entry: dict) -> str:
    from backend.app.core import trash

    kind = entry["kind"]
    if kind == "trash":
        return f"Restored {trash.restore(entry['trash'])}"
    if kind in {"move", "rename"}:
        src, dst = Path(entry["to"]), Path(entry["from"])
        if not src.exists():
            raise FileNotFoundError(f"{src} is not there any more")
        if dst.exists():
            raise FileExistsError(f"{dst} already exists")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return f"Moved {src.name} back to {dst.parent}"
    if kind == "organize":
        moved = 0
        for pair in reversed(entry.get("moves") or []):
            now, before = Path(pair[1]), Path(pair[0])
            if now.exists() and not before.exists():
                shutil.move(str(now), str(before))
                moved += 1
        for folder in entry.get("created_dirs") or []:
            try:
                Path(folder).rmdir()  # only if it is empty again
            except OSError:
                pass
        return f"Put {moved} files back where they were"
    if kind in {"create", "copy"}:
        target = Path(entry["path"])
        if not target.exists():
            return f"{target.name} is already gone"
        record_ = trash.send_to_trash(target)
        return f"Moved {target.name} to the Trash ({'restorable' if record_ else ''})".replace(" ()", "")
    raise ValueError(f"Cannot undo '{kind}'")


def undo_last(entry_id: Optional[str] = None) -> dict:
    with _lock:
        items = _load()
        target = next(
            (item for item in items if not item.get("undone") and (entry_id is None or item["id"] == entry_id)),
            None,
        )
        if target is None:
            return {"success": False, "error": "There is nothing to undo."}
        try:
            message = _reverse(target)
        except Exception as exc:
            return {"success": False, "error": f"Could not undo '{target['summary']}': {exc}"}
        target["undone"] = True
        target["undone_at"] = time.time()
        try:
            _save(items)
        except OSError:
            pass
    return {"success": True, "undone": target["summary"], "message": message}


def clear() -> None:
    with _lock:
        try:
            _store().unlink()
        except OSError:
            pass
