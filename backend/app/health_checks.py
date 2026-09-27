"""V2 Step E5: Ultron's daily health in plain words (used by `ultron doctor`).

Every check returns (level, what, fix):
  level "ok"   = fine
        "warn" = works, but something needs a look
        "fail" = broken; Ultron cannot do this until it is fixed
Checks never raise and never print secrets (key values are never shown).
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path
from typing import Callable, Optional

Check = tuple[str, str, str]

GB = 1024 ** 3
MB = 1024 ** 2


def check_keys() -> list[Check]:
    from backend.app.brain.api_key_manager import APIKeyManager, _looks_like_placeholder

    try:
        manager = APIKeyManager()
        counts = {
            name: sum(1 for key in manager.active_keys(name) if not _looks_like_placeholder(key))
            for name in ("groq", "gemini", "nvidia")
        }
    except Exception as exc:
        return [("fail", f"Could not read the AI keys: {exc}", "Check the .env file.")]
    total = sum(counts.values())
    if total == 0:
        return [("warn", "Ultron has no AI key, so he cannot think or use tools.",
                 "Put GROQ_API_KEY_1=your_key in the .env file (free at console.groq.com).")]
    names = ", ".join(f"{name} {count}" for name, count in counts.items() if count)
    working = [name for name, count in counts.items() if count]
    if len(working) == 1:
        return [("warn", f"AI keys: {names}. Only one provider, so a Groq outage stops him.",
                 "Add a free Gemini key too (GEMINI_API_KEY_1) as a backup brain.")]
    return [("ok", f"AI keys: {names}.", "")]


def check_models() -> list[Check]:
    from backend.app.brain import model_fallback
    from backend.app.brain.model_config import get_model

    try:
        state = model_fallback.status()
        using = {p: get_model(p) for p in ("groq", "gemini", "embedding")}
    except Exception as exc:
        return [("warn", f"Could not read the model list: {exc}", "")]
    line = "Models in use: " + ", ".join(f"{p} {m}" for p, m in using.items()) + "."
    if state["gone"]:
        retired = ", ".join(item.replace("|", " ") for item in state["gone"])
        return [("ok", line, ""),
                ("warn", f"Retired by the provider (Ultron switched by himself): {retired}.",
                 "Nothing to do. Optional: update ultron-v2 some day for newer models.")]
    return [("ok", line, "")]


def check_usage_today() -> list[Check]:
    from backend.app.brain import usage_meter
    from backend.app.brain.api_key_manager import APIKeyManager, _looks_like_placeholder

    try:
        keys = [k for k in APIKeyManager().active_keys("groq") if not _looks_like_placeholder(k)]
        line = usage_meter.summary_line(len(keys))
        rows = usage_meter.today()
    except Exception as exc:
        return [("warn", f"Could not read today's AI use: {exc}", "")]
    groq = rows.get("groq") or {}
    if groq and groq.get("counted", 0) > 0.85 * 200_000 * max(1, len(keys)):
        return [("warn", line, "Nearly at today's free limit; add a second free Groq key "
                                "(another account) as GROQ_API_KEY_2.")]
    return [("ok", line, "")]


def check_browser_helper(port: int, fetch: Optional[Callable[[str], dict]] = None) -> list[Check]:
    """Asks a running Ultron whether the Chrome helper (extension) is connected."""
    url = f"http://127.0.0.1:{port}/api/health"
    try:
        if fetch is None:
            import httpx

            data = httpx.get(url, timeout=3.0).json()
        else:
            data = fetch(url)
    except Exception:
        return [("ok", "Chrome helper: start Ultron first, then run doctor again to check it.", "")]
    helper = (data or {}).get("browser_helper") or {}
    if helper.get("connected"):
        version = f" (version {helper['version']})" if helper.get("version") else ""
        return [("ok", f"Chrome helper is connected{version}: tab control works.", "")]
    return [("warn", "Chrome helper is not connected: close tab / switch tab will not work.",
             "Open chrome://extensions, turn on Developer mode, Load unpacked, "
             "pick the browser_extension folder of ultron-v2.")]


def check_disk(home: Path) -> list[Check]:
    try:
        probe = Path(home)
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        free = shutil.disk_usage(probe).free
    except OSError as exc:
        return [("warn", f"Could not read free disk space: {exc}", "")]
    if free < 1 * GB:
        return [("fail", f"Disk almost full: only {free / GB:.1f} GB free. Backups are paused.",
                 "Free some space (Downloads, old videos) - at least 5 GB is comfortable.")]
    if free < 5 * GB:
        return [("warn", f"Disk space is low: {free / GB:.1f} GB free.", "Free a few GB soon.")]
    return [("ok", f"Disk: {free / GB:.0f} GB free.", "")]


def _folder_size(folder: Path) -> int:
    total = 0
    try:
        for path in folder.rglob("*"):
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
    except OSError:
        pass
    return total


def check_database(db_path: Path, backup_dir: Path) -> list[Check]:
    results: list[Check] = []
    if not Path(db_path).is_file():
        return [("warn", "No database yet (Ultron has not run on this PC).",
                 "Start Ultron once; it is created by itself.")]
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
        try:
            verdict = conn.execute("PRAGMA quick_check").fetchone()[0]
            chats = _count(conn, "conversations")
            facts = _count(conn, "vector_memories")
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return [("fail", f"The database cannot be opened: {exc}",
                 "Run: ultron backup --restore (uses the newest good backup).")]
    size = Path(db_path).stat().st_size
    if verdict != "ok":
        results.append(("fail", f"The database is damaged ({verdict}).",
                        "Run: ultron backup --restore (uses the newest good backup)."))
    else:
        results.append(("ok", f"Database is healthy ({size / MB:.0f} MB). Memory: "
                              f"{chats} chats, {facts} saved memories.", ""))
    backups = sorted(Path(backup_dir).glob("ultron_*.db"), key=lambda p: p.stat().st_mtime) \
        if Path(backup_dir).is_dir() else []
    if not backups:
        results.append(("warn", "No backup yet.", "It is made by itself once a day while Ultron runs."))
    else:
        age_days = (time.time() - backups[-1].stat().st_mtime) / 86400
        total = sum(p.stat().st_size for p in backups)
        line = (f"Backups: {len(backups)} copies, {total / MB:.0f} MB, newest "
                f"{'today' if age_days < 1 else f'{age_days:.0f} day(s) ago'}.")
        if age_days > 3:
            results.append(("warn", line, "Backups run while Ultron is on; start him for a while."))
        else:
            results.append(("ok", line, ""))
    return results


def _count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # nosec B608
    except sqlite3.Error:
        return 0


def check_autostart() -> list[Check]:
    from backend.app import autostart

    try:
        info = autostart.status()
    except Exception as exc:
        return [("warn", f"Could not read autostart: {exc}", "")]
    if info["enabled"]:
        return [("ok", f"Starts at login ({info['how']}) and restarts after a crash.", "")]
    return [("warn", "Ultron does not start at login.", "Run: ultron autostart on")]


def check_data_folder(home: Path) -> list[Check]:
    size = _folder_size(Path(home) / "data")
    return [("ok", f"Ultron's data folder uses {size / MB:.0f} MB (self-cleaning).", "")]


def run_all(*, home: Path, db_path: Path, backup_dir: Path, port: int) -> list[Check]:
    results: list[Check] = []
    for check in (
        check_keys,
        check_models,
        check_usage_today,
        lambda: check_browser_helper(port),
        lambda: check_disk(home),
        lambda: check_database(db_path, backup_dir),
        lambda: check_data_folder(home),
        check_autostart,
    ):
        try:
            results.extend(check())
        except Exception as exc:  # one broken check never hides the rest
            results.append(("warn", f"A check could not run: {exc}", ""))
    return results
