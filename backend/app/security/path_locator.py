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

V2 Step 5: real Desktop/Documents/... come from Windows settings (OneDrive
redirect) or XDG user-dirs (Ubuntu); the folder-name index answers first at
any depth; recently used folders win ties; two exact same-name folders are
reported as ambiguous so Jarvis asks instead of guessing.
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
_FILLER = re.compile(
    r"\b(my|the|folder|folders|directory|dir|file|wala|wali|waala|waali|vala|ka|ki|ke|mera|meri|mere|"
    r"amar|called|named|inside|jo|hai)\b",
    re.IGNORECASE,
)
_WINDOWS_SHELL_NAMES = {
    "Desktop": "Desktop", "Documents": "Personal", "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "Pictures": "My Pictures", "Music": "My Music", "Videos": "My Video",
}
_XDG_NAMES = {
    "Desktop": "XDG_DESKTOP_DIR", "Documents": "XDG_DOCUMENTS_DIR", "Downloads": "XDG_DOWNLOAD_DIR",
    "Pictures": "XDG_PICTURES_DIR", "Music": "XDG_MUSIC_DIR", "Videos": "XDG_VIDEOS_DIR",
}


class AmbiguousPath(Exception):
    """Two or more folders share the spoken name; the owner must choose."""

    def __init__(self, name: str, choices: list[str]):
        self.name = name
        self.choices = choices
        listed = "; ".join(f"{i}) {path}" for i, path in enumerate(choices, 1))
        super().__init__(f"{len(choices)} places are named '{name}': {listed}. Ask the owner which one.")

_cache: dict[tuple[str, str], tuple[float, list[str]]] = {}


def _key(name: str) -> str:
    return re.sub(r"[\s_\-.]+", "", name.lower())


def clean_name(spoken: str) -> str:
    """'my Projects folder' -> 'Projects'."""
    text = _FILLER.sub(" ", str(spoken or ""))
    return " ".join(text.split()).strip(" /\\")


def _windows_shell_folder(canonical: str) -> Optional[Path]:
    """The real folder Windows uses (OneDrive backup moves Desktop/Documents)."""
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            value, _ = winreg.QueryValueEx(key, _WINDOWS_SHELL_NAMES[canonical])
        folder = Path(os.path.expandvars(str(value)))
        return folder if folder.is_dir() else None
    except (OSError, KeyError, ImportError):
        return None


def _xdg_folder(canonical: str) -> Optional[Path]:
    """Ubuntu/Linux user dirs (~/.config/user-dirs.dirs), incl. translated names."""
    if os.name == "nt":
        return None
    config = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "user-dirs.dirs"
    try:
        text = config.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(rf'^{_XDG_NAMES[canonical]}="([^"]+)"', text, re.MULTILINE)
    if not match:
        return None
    folder = Path(match.group(1).replace("$HOME", str(Path.home())))
    if os.path.normcase(str(folder)) == os.path.normcase(str(Path.home())):
        return None  # XDG sets unused dirs to $HOME
    return folder if folder.is_dir() else None


def _has_entries(folder: Path) -> bool:
    try:
        with os.scandir(folder) as entries:
            return any(True for _ in entries)
    except OSError:
        return False


def home_folder(word: str) -> Optional[Path]:
    """Resolve Desktop/Documents/... to the folder the OS really uses.

    Order: Windows settings / XDG user-dirs -> OneDrive or home copy that has
    files -> any existing copy. (Old order picked an empty C:\\Users\\X\\Desktop
    while Windows 11 kept the real Desktop in OneDrive.)
    """
    canonical = next((w for w in _FOLDER_WORDS if w.lower() == str(word).lower()), None)
    if canonical is None:
        return None
    system = _windows_shell_folder(canonical) or _xdg_folder(canonical)
    if system is not None:
        return system
    home = Path.home()
    candidates = [
        *(p / canonical for p in sorted(home.glob("OneDrive*")) if p.is_dir()),
        home / canonical,
    ]
    existing = [c for c in candidates if c.is_dir()]
    for candidate in existing:
        if _has_entries(candidate):
            return candidate
    if existing:
        return existing[-1] if (home / canonical).is_dir() else existing[0]
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


def _walk(
    name: str,
    *,
    kind: str,
    limit: int,
    extra_roots: Iterable[Path] = (),
) -> tuple[list[str], list[str], dict[str, str]]:
    """Bounded live search -> (exact, partial, folder names seen for fuzzy)."""
    target = _key(Path(name).name)
    cache_id = (target + "|" + os.path.normcase(str(Path(name).parent)), kind)
    cached = _cache.get(cache_id)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL:
        alive = lambda items: [p for p in items if Path(p).exists()]  # noqa: E731
        return alive(cached[1][0]), alive(cached[1][1]), {}

    parent_hint = _key(str(Path(name).parent)) if str(Path(name).parent) not in ("", ".") else ""
    started = time.monotonic()
    visited = 0
    exact: list[tuple[int, str]] = []
    partial: list[tuple[int, str]] = []
    seen: set[str] = set()
    names_seen: dict[str, str] = {}

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
                if is_dir and len(names_seen) < 30_000:
                    names_seen.setdefault(entry_key, entry.path)
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

    exact_paths = [p for _, p in sorted(exact)][:25]
    partial_paths = [p for _, p in sorted(partial)][:25]
    _cache[cache_id] = (time.monotonic(), (exact_paths, partial_paths))
    return exact_paths, partial_paths, names_seen


def _dedupe(paths: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for path in paths:
        norm = os.path.normcase(os.path.normpath(str(path)))
        if norm not in seen:
            seen.add(norm)
            out.append(str(path))
    return out


def _recent_first(paths: list[str]) -> list[str]:
    from backend.app.core import recent_folders

    ranked = sorted(
        enumerate(paths),
        key=lambda pair: (
            recent_folders.rank_of(pair[1]) if recent_folders.rank_of(pair[1]) is not None else 10_000,
            pair[0],
        ),
    )
    return [path for _, path in ranked]


def locate_detailed(
    spoken: str,
    *,
    kind: str = "folder",
    limit: int = 10,
    extra_roots: Iterable[Path] = (),
) -> dict:
    """{'matches': best-first paths, 'ambiguous': bool, 'exact': [...], 'how': str}."""
    from backend.app.core import folder_index, recent_folders

    none = {"matches": [], "exact": [], "ambiguous": False, "how": "none"}
    if recent_folders.is_reference(spoken):
        last = recent_folders.last()
        return {"matches": [last], "exact": [last], "ambiguous": False, "how": "recent"} if last else none
    name = clean_name(spoken)
    if not name:
        return none
    plain = os.sep not in name and "/" not in name
    direct = home_folder(name) if plain else None
    if direct is not None and direct.is_dir() and kind in ("folder", "any"):
        return {"matches": [str(direct)], "exact": [str(direct)], "ambiguous": False, "how": "home"}

    indexed = folder_index.lookup(Path(name).name) if (plain and kind in ("folder", "any")) else None
    exact: list[str] = list(indexed["exact"]) if indexed else []
    partial: list[str] = []
    how = "index" if exact else "search"
    names_seen: dict[str, str] = {}
    if not exact or kind == "any":
        walked_exact, partial, names_seen = _walk(name, kind=kind, limit=limit, extra_roots=extra_roots)
        exact = _dedupe([*walked_exact, *exact])
    if not exact and indexed:
        partial = _dedupe([*partial, *indexed["partial"]])
    fuzzy: list[str] = []
    if not exact and not partial:
        fuzzy = list(indexed["fuzzy"]) if indexed else []
        target = _key(Path(name).name)
        if not fuzzy and names_seen and len(target) >= 4:
            import difflib

            fuzzy = [names_seen[k] for k in difflib.get_close_matches(target, list(names_seen), n=3, cutoff=0.8)]
        how = "fuzzy" if fuzzy else how

    exact = _recent_first(exact)
    ambiguous = len(exact) > 1 and recent_folders.rank_of(exact[0]) is None
    matches = _dedupe([*exact, *_recent_first(partial), *fuzzy])[:limit]
    return {"matches": matches, "exact": exact[:limit], "ambiguous": ambiguous, "how": how}


def locate(
    spoken: str,
    *,
    kind: str = "folder",
    limit: int = 10,
    extra_roots: Iterable[Path] = (),
) -> list[str]:
    """Return up to `limit` matching paths, best first. kind: folder | file | any."""
    return locate_detailed(spoken, kind=kind, limit=limit, extra_roots=extra_roots)["matches"]


def auto_resolve(value: str, root: Path, *, kind: str = "any") -> Optional[Path]:
    """Best single match for a path that does not exist as typed, else None.

    Raises AmbiguousPath when 2+ folders share the exact name and none was used
    recently - Jarvis asks the owner instead of silently picking one.
    """
    found = locate_detailed(value, kind=kind, limit=5, extra_roots=[root])
    if found["ambiguous"]:
        raise AmbiguousPath(clean_name(value) or str(value), found["exact"][:5])
    return Path(found["matches"][0]) if found["matches"] else None
