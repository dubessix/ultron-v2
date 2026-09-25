"""Deletes go to the Trash / Recycle Bin, and can be restored (V2 Step 7).

* Ubuntu/Linux: freedesktop.org Trash (~/.local/share/Trash) - shows up in the
  Files app's Trash with "Restore" working there too.
* Windows: the real Recycle Bin (via the built-in .NET VisualBasic API); restore
  uses the Shell "undelete" verb on the matching item.
* Tests / unusual setups: ULTRON_TRASH_DIR forces a plain folder trash.
"""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import urllib.parse
from pathlib import Path


def _plain_trash() -> Path | None:
    forced = os.environ.get("ULTRON_TRASH_DIR")
    return Path(forced) if forced else None


def _xdg_trash() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "Trash"


def _unique(folder: Path, name: str) -> Path:
    candidate = folder / name
    counter = 2
    while candidate.exists() or candidate.is_symlink():
        stem, suffix = os.path.splitext(name)
        candidate = folder / f"{stem}.{counter}{suffix}"
        counter += 1
    return candidate


def send_to_trash(path: str | os.PathLike) -> dict:
    """Move a file/folder to the trash. Returns a record used by restore()."""
    target = Path(path).resolve()
    if not target.exists():
        raise FileNotFoundError(str(target))
    plain = _plain_trash()
    if plain is None and os.name == "nt":
        return _windows_recycle(target)
    trash = plain or _xdg_trash()
    files = trash / "files"
    info = trash / "info"
    files.mkdir(parents=True, exist_ok=True)
    info.mkdir(parents=True, exist_ok=True)
    destination = _unique(files, target.name)
    stamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    info_file = info / (destination.name + ".trashinfo")
    info_file.write_text(
        f"[Trash Info]\nPath={urllib.parse.quote(str(target))}\nDeletionDate={stamp}\n", encoding="utf-8"
    )
    try:
        shutil.move(str(target), str(destination))
    except Exception:
        info_file.unlink(missing_ok=True)
        raise
    return {"method": "folder", "original": str(target), "trashed": str(destination), "info": str(info_file)}


def restore(record: dict) -> str:
    """Put a trashed item back where it was. Returns the restored path."""
    original = Path(record["original"])
    if original.exists():
        raise FileExistsError(f"Something already exists at {original}")
    if record.get("method") == "recycle_bin":
        _windows_restore(original)
        return str(original)
    original.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(record["trashed"], str(original))
    Path(record.get("info") or "").unlink(missing_ok=True) if record.get("info") else None
    return str(original)


def _powershell(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=60,
    )


def _windows_recycle(target: Path) -> dict:
    kind = "DeleteDirectory" if target.is_dir() else "DeleteFile"
    literal = str(target).replace("'", "''")
    result = _powershell(
        "Add-Type -AssemblyName Microsoft.VisualBasic;"
        f"[Microsoft.VisualBasic.FileIO.FileSystem]::{kind}('{literal}',"
        "'OnlyErrorDialogs','SendToRecycleBin')"
    )
    if result.returncode != 0 or target.exists():
        raise OSError(result.stderr.strip()[:300] or "Recycle Bin move failed")
    return {"method": "recycle_bin", "original": str(target)}


def _windows_restore(original: Path) -> None:
    folder = str(original.parent).replace("'", "''")
    name = original.name.replace("'", "''")
    result = _powershell(
        "$bin=(New-Object -ComObject Shell.Application).NameSpace(10);"
        "$item=$bin.Items()|Where-Object {"
        f"$bin.GetDetailsOf($_,1) -eq '{folder}' -and $_.Name -eq '{name}'"
        "}|Select-Object -First 1;"
        "if(-not $item){exit 3};$item.InvokeVerb('undelete')"
    )
    if result.returncode != 0 or not original.exists():
        raise OSError("Could not restore from the Recycle Bin; it may have been emptied.")
