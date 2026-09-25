"""Jarvis auto-find: turn "my Projects folder" into a real path on this PC.

Search order (first hit wins, shallow before deep):
  1. exact path as given (absolute, ~, or relative to the active root)
  2. the owner's everyday folders: Desktop, Documents, Downloads, Pictures,
     Music, Videos (+ OneDrive variants on Windows), home itself
  3. every drive root (Windows) / home + /mnt + /media (POSIX)

Bounded on purpose so a voice command never freezes the assistant:
depth <= 4, <= 25k directories visited, <= 2.5 s wall time, hidden/system/
dependency folders skipped. Matching is case-insensitive and ignores
spaces, dashes and underscores ("my projects" == "My_Projects").
Results never bypass security: callers still pass every path to check_path.
"""

from __future__ import annotations

import os
import re
import string
import time
from collections import deque
from pathlib import Path
from typing import Iterable, Optional

MAX_DEPTH = 4
MAX_DIRS = 25_000
MAX_SECONDS = 2.5
_CACHE_TTL = 120.0

_SKIP_NAMES = {
    "node_modules", "__pycache__", ".git", ".venv", "venv", "env", "site-packages",
    "appdata", "application data", "$recycle.bin", "system volume information",
    "windows", "program files", "program files (x86)", "programdata", "recovery",
    "library", "proc", "sys", "dev", "snap", "cache", ".cache", "temp", "tmp",
}
_FOLDER_WORDS = ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")
_FILLER = re.compile(r"\b(my|the|folder|directory|dir|file)\b", re.IGNORECASE)

_cache: dict[tuple[str, str], tuple[float, list[str]]] = {}


def _key(name: str) -> str:
    return re.sub(r"[\s_\-.]+", "", name.lower())


def clean_name(spoken: str) -> str:
    """'my Projects folder' -> 'Projects'."""
    text = _FILLER.sub(" ", str(spoken or ""))
    return " ".join(text.split()).strip(" /\\")


def home_folder(word: str) -> Optional[Path]:
    """Resolve Desktop/Documents/... including OneDrive-redirected Windows folders."""
    canonical = next((w for w in _FOLDER_WORDS if w.lower() == word.lower()), None)
    if canonical is None:
        return None
    home = Path.home()
    for candidate in (
        home / canonical,
        home / "OneDrive" / canonical,
        *(p / canonical for p in home.glob("OneDrive*") if p.is_dir()),
    ):
        if candidate.is_dir():
            return candidate
    return home / canonical


def search_roots(extra: Iterable[Path] = ()) -> list[Path]:
    roots: list[Path] = []
    for path in list(extra):
        roots.append(Path(path))
    for word in _FOLDER_WORDS:
        folder = home_folder(word)
        if folder is not None:
            roots.append(folder)
    roots.append(Path.home())
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            if drive.exists():
                roots.append(drive)
    else:
        roots.extend(Path(p) for p in ("/mnt", "/media", "/Volumes") if Path(p).is_dir())
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        norm = os.path.normcase(str(root))
        if norm not in seen and root.is_dir():
            seen.add(norm)
            unique.append(root)
    return unique


def locate(
    spoken: str,
    *,
    kind: str = "folder",
    limit: int = 10,
    extra_roots: Iterable[Path] = (),
) -> list[str]:
    """Return up to `limit` matching paths, best first. kind: folder | file | any."""
    name = clean_name(spoken)
    if not name:
        return []
    target = _key(Path(name).name)
    cache_id = (target + "|" + os.path.normcase(str(Path(name).parent)), kind)
    cached = _cache.get(cache_id)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL:
        return [p for p in cached[1] if Path(p).exists()][:limit]

    # Direct hit on a known home-folder word.
    direct = home_folder(name) if os.sep not in name and "/" not in name else None
    if direct is not None and direct.is_dir() and kind in ("folder", "any"):
        _cache[cache_id] = (time.monotonic(), [str(direct)])
        return [str(direct)]

    parent_hint = _key(str(Path(name).parent)) if str(Path(name).parent) not in ("", ".") else ""
    started = time.monotonic()
    visited = 0
    exact: list[tuple[int, str]] = []
    partial: list[tuple[int, str]] = []
    seen: set[str] = set()

    for root_rank, root in enumerate(search_roots(extra_roots)):
        queue: deque[tuple[Path, int]] = deque([(root, 0)])
        while queue:
            if visited >= MAX_DIRS or time.monotonic() - started > MAX_SECONDS:
                queue.clear()
                break
            current, depth = queue.popleft()
            visited += 1
            try:
                entries = list(os.scandir(current))
            except (OSError, PermissionError):
                continue
            for entry in entries:
                entry_name = entry.name
                if entry_name.startswith(".") or entry_name.lower() in _SKIP_NAMES:
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                wanted = (
                    (kind == "folder" and is_dir)
                    or (kind == "file" and not is_dir)
                    or kind == "any"
                )
                entry_key = _key(entry_name)
                stem_key = _key(Path(entry_name).stem)
                if wanted and (entry_key == target or stem_key == target):
                    if not parent_hint or parent_hint in _key(str(Path(entry.path).parent)):
                        norm = os.path.normcase(entry.path)
                        if norm not in seen:
                            seen.add(norm)
                            exact.append((root_rank * 100 + depth, entry.path))
                elif wanted and len(target) >= 4 and target in entry_key:
                    norm = os.path.normcase(entry.path)
                    if norm not in seen:
                        seen.add(norm)
                        partial.append((root_rank * 100 + depth + 50, entry.path))
                if is_dir and depth + 1 <= MAX_DEPTH:
                    queue.append((Path(entry.path), depth + 1))
        if len(exact) >= limit:
            break

    ranked = [p for _, p in sorted(exact)] + [p for _, p in sorted(partial)]
    _cache[cache_id] = (time.monotonic(), ranked[:25])
    return ranked[:limit]


def auto_resolve(value: str, root: Path, *, kind: str = "any") -> Optional[Path]:
    """Best single match for a path that does not exist as typed, else None."""
    matches = locate(value, kind=kind, limit=1, extra_roots=[root])
    return Path(matches[0]) if matches else None
