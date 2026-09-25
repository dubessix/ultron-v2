"""Folder-name index - "find my X folder" answers instantly at any depth (V2 Step 5).

* Stores folder NAMES + paths only (never file contents) in a small SQLite file.
* Built in a low-priority background thread only when the PC is idle
  (CPU < 50 %), a few minutes after start, and refreshed every 12 hours.
* Bounded: depth <= 12, <= 400k folders, short sleeps between batches so the
  8 GB laptop never notices. Queries never block on a build (atomic swap).
* The live bounded walk in path_locator stays as the fallback.
"""

from __future__ import annotations

import difflib
import os
import re
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path
from typing import Iterable, Optional

MAX_DEPTH = 12
MAX_FOLDERS = 400_000
REFRESH_SECONDS = 12 * 3600
START_DELAY_SECONDS = 120

_build_lock = threading.Lock()
_thread: Optional[threading.Thread] = None


def _key(name: str) -> str:
    return re.sub(r"[\s_\-.]+", "", str(name).lower())


def db_path() -> Path:
    from backend.app.runtime_paths import runtime_data_path

    return runtime_data_path("folder_index.db")


def _connect(path: Optional[Path] = None) -> sqlite3.Connection:
    target = path or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=5)
    conn.execute("CREATE TABLE IF NOT EXISTS folders (key TEXT NOT NULL, path TEXT PRIMARY KEY, depth INTEGER)")
    conn.execute("CREATE INDEX IF NOT EXISTS folders_key ON folders(key)")
    conn.execute("CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT)")
    return conn


def build(roots: Iterable[Path], *, path: Optional[Path] = None, pause: float = 0.0) -> int:
    """Walk roots and replace the index atomically. Returns folders indexed."""
    from backend.app.security.path_locator import _SKIP_NAMES

    with _build_lock:
        conn = _connect(path)
        try:
            conn.execute("DROP TABLE IF EXISTS folders_new")
            conn.execute("CREATE TABLE folders_new (key TEXT NOT NULL, path TEXT PRIMARY KEY, depth INTEGER)")
            batch: list[tuple[str, str, int]] = []
            count = 0
            seen_roots: set[str] = set()
            for root in roots:
                root = Path(root)
                norm = os.path.normcase(str(root))
                if norm in seen_roots or not root.is_dir():
                    continue
                seen_roots.add(norm)
                queue: deque[tuple[str, int]] = deque([(str(root), 0)])
                while queue and count < MAX_FOLDERS:
                    current, depth = queue.popleft()
                    try:
                        with os.scandir(current) as entries:
                            children = [
                                entry for entry in entries
                                if not entry.name.startswith(".")
                                and entry.name.lower() not in _SKIP_NAMES
                                and entry.is_dir(follow_symlinks=False)
                            ]
                    except OSError:
                        continue
                    for entry in children:
                        batch.append((_key(entry.name), entry.path, depth + 1))
                        count += 1
                        if depth + 1 < MAX_DEPTH:
                            queue.append((entry.path, depth + 1))
                    if len(batch) >= 2000:
                        conn.executemany("INSERT OR IGNORE INTO folders_new VALUES (?, ?, ?)", batch)
                        batch.clear()
                        if pause:
                            time.sleep(pause)
            if batch:
                conn.executemany("INSERT OR IGNORE INTO folders_new VALUES (?, ?, ?)", batch)
            conn.execute("DROP TABLE IF EXISTS folders")
            conn.execute("ALTER TABLE folders_new RENAME TO folders")
            conn.execute("CREATE INDEX IF NOT EXISTS folders_key ON folders(key)")
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('built_at', ?)", (str(time.time()),))
            conn.commit()
            return count
        finally:
            conn.close()


def built_at(path: Optional[Path] = None) -> float:
    target = path or db_path()
    if not target.exists():
        return 0.0
    try:
        conn = _connect(target)
        try:
            row = conn.execute("SELECT value FROM meta WHERE name='built_at'").fetchone()
            return float(row[0]) if row else 0.0
        finally:
            conn.close()
    except (sqlite3.Error, ValueError):
        return 0.0


def lookup(name: str, *, path: Optional[Path] = None, limit: int = 25) -> dict:
    """{'exact': [...], 'partial': [...], 'fuzzy': [...]} - only paths that still exist."""
    empty = {"exact": [], "partial": [], "fuzzy": []}
    target = _key(name)
    db = path or db_path()
    if not target or not db.exists():
        return empty
    try:
        conn = _connect(db)
    except sqlite3.Error:
        return empty
    try:
        exact = [row[0] for row in conn.execute(
            "SELECT path FROM folders WHERE key = ? ORDER BY depth LIMIT ?", (target, limit))]
        partial: list[str] = []
        fuzzy: list[str] = []
        if not exact and len(target) >= 4:
            partial = [row[0] for row in conn.execute(
                "SELECT path FROM folders WHERE instr(key, ?) > 0 ORDER BY depth, length(key) LIMIT ?",
                (target, limit))]
        if not exact and not partial and len(target) >= 4:
            # Spelling mistakes ("dowloads", "colege"): compare against similar-length names only.
            low, high = max(1, int(len(target) * 0.75)), int(len(target) * 1.3) + 1
            keys = [row[0] for row in conn.execute(
                "SELECT DISTINCT key FROM folders WHERE length(key) BETWEEN ? AND ? LIMIT 60000", (low, high))]
            close = difflib.get_close_matches(target, keys, n=3, cutoff=0.8)
            for key in close:
                fuzzy.extend(row[0] for row in conn.execute(
                    "SELECT path FROM folders WHERE key = ? ORDER BY depth LIMIT 5", (key,)))
        alive = lambda items: [item for item in items if os.path.isdir(item)]  # noqa: E731
        return {"exact": alive(exact), "partial": alive(partial), "fuzzy": alive(fuzzy)}
    except sqlite3.Error:
        return empty
    finally:
        conn.close()


def _pc_is_idle() -> bool:
    try:
        import psutil

        return psutil.cpu_percent(interval=1.0) < 50.0
    except Exception:
        return True


def _background_loop() -> None:
    from backend.app.security.path_locator import search_roots

    if hasattr(os, "nice"):
        try:
            os.nice(10)  # this thread only on Linux; keeps the UI and voice smooth
        except OSError:
            pass
    time.sleep(START_DELAY_SECONDS)
    while True:
        try:
            if time.time() - built_at() > REFRESH_SECONDS and _pc_is_idle():
                build(search_roots(), pause=0.01)
        except Exception as exc:  # never crash the app for an index
            print(f"[FOLDER_INDEX] build skipped: {exc}")
        time.sleep(3600)


def start_background_indexer() -> None:
    global _thread
    from backend.app.runtime_paths import TEST_MODE

    if TEST_MODE or os.getenv("ULTRON_FOLDER_INDEX", "1") == "0":
        return
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_background_loop, name="folder-index", daemon=True)
    _thread.start()
