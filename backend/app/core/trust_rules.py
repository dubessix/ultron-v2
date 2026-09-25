"""Trust rules - "always allow this in this folder" (V2 Step 7).

* Every owner approval of a risky action is counted per scope
  (tool + folder, or tool + action/command word).
* After 3 approvals of the same scope, Jarvis OFFERS a rule. Only the owner
  can accept it (frontend button / voice "yes, always" -> POST /api/trust).
  The AI has no tool that creates rules, so it can never grant itself power.
* Hard blocks (system folders, secrets, disk-wiping commands) run BEFORE this
  gate, so a rule can never unlock them. Some tools can never be trusted.
"""

from __future__ import annotations

import json
import os
import shlex
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

OFFER_AFTER = 3
NEVER_TRUSTED = {"database_restore", "github_integration", "file_write", "close_browser"}
NEVER_TRUSTED_ACTIONS = {("pc_control", "shutdown"), ("pc_control", "restart")}
_PATH_FIELDS = ("folderpath", "source_path", "old_path", "path", "zippath", "save_path", "directory",
                "source_filepath", "extract_to", "destination_path", "cwd", "filepath")
_lock = threading.Lock()


def _store() -> Path:
    from backend.app.runtime_paths import runtime_data_path

    return runtime_data_path("trust_rules.json")


def _load() -> dict:
    try:
        data = json.loads(_store().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("rules", [])
            data.setdefault("approvals", {})
            return data
    except (OSError, ValueError):
        pass
    return {"rules": [], "approvals": {}}


def _save(data: dict) -> None:
    store = _store()
    store.parent.mkdir(parents=True, exist_ok=True)
    tmp = store.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, store)


def scope_for(tool_id: str, arguments: dict) -> Optional[dict]:
    """What an approval is 'about'. None = this action can never become trusted."""
    args = arguments or {}
    action = str(args.get("action") or "").lower()
    if tool_id in NEVER_TRUSTED or (tool_id, action) in NEVER_TRUSTED_ACTIONS:
        return None
    if tool_id == "terminal_run":
        try:
            word = shlex.split(str(args.get("command") or ""))[0]
        except (ValueError, IndexError):
            return None
        return {"tool_id": tool_id, "kind": "command", "value": os.path.basename(word).lower(),
                "label": f"run '{os.path.basename(word)}' commands"}
    for field in _PATH_FIELDS:
        value = args.get(field)
        if isinstance(value, str) and value.strip():
            target = Path(value)
            item_tool = tool_id in {"delete_folder", "move_folder", "rename_folder", "copy_folder"}
            folder = target.parent if (item_tool or target.suffix) else target
            return {"tool_id": tool_id, "kind": "folder", "value": str(folder),
                    "label": f"{tool_id.replace('_', ' ')} inside {folder}"}
    if action:
        return {"tool_id": tool_id, "kind": "action", "value": action,
                "label": f"{tool_id.replace('_', ' ')} {action}"}
    return {"tool_id": tool_id, "kind": "tool", "value": "*", "label": tool_id.replace("_", " ")}


def _key(scope: dict) -> str:
    return f"{scope['tool_id']}|{scope['kind']}|{os.path.normcase(scope['value'])}"


def _inside(child: str, parent: str) -> bool:
    try:
        c, p = Path(child).resolve(), Path(parent).resolve()
        return c == p or p in c.parents
    except (OSError, RuntimeError):
        return False


def allows(tool_id: str, arguments: dict) -> Optional[dict]:
    """The rule that pre-approves this exact action, or None."""
    scope = scope_for(tool_id, arguments)
    if scope is None:
        return None
    for rule in _load()["rules"]:
        if rule["tool_id"] != tool_id or rule["kind"] != scope["kind"]:
            continue
        if scope["kind"] == "folder" and _inside(scope["value"], rule["value"]):
            return rule
        if scope["kind"] != "folder" and os.path.normcase(rule["value"]) == os.path.normcase(scope["value"]):
            return rule
    return None


def note_approval(tool_id: str, arguments: dict) -> Optional[dict]:
    """Count an owner approval; returns an offer once the same scope reached OFFER_AFTER."""
    scope = scope_for(tool_id, arguments)
    if scope is None:
        return None
    with _lock:
        data = _load()
        key = _key(scope)
        data["approvals"][key] = int(data["approvals"].get(key, 0)) + 1
        count = data["approvals"][key]
        try:
            _save(data)
        except OSError:
            return None
    too_broad = scope["kind"] == "folder" and Path(scope["value"]).resolve() in {
        Path.home().resolve(), Path(Path.home().anchor)}
    if count >= OFFER_AFTER and not too_broad and allows(tool_id, arguments) is None:
        return {**scope, "approvals": count,
                "question": f"You've approved this {count} times. Always allow {scope['label']}?"}
    return None


def allow(scope: dict) -> dict:
    """Owner accepted an offer. Validated so a crafted request cannot trust blocked tools."""
    tool_id = str(scope.get("tool_id") or "")
    kind = str(scope.get("kind") or "")
    value = str(scope.get("value") or "")
    if not tool_id or kind not in {"folder", "command", "action", "tool"} or not value:
        raise ValueError("Invalid trust rule.")
    if tool_id in NEVER_TRUSTED or (kind == "action" and (tool_id, value.lower()) in NEVER_TRUSTED_ACTIONS):
        raise ValueError(f"'{tool_id}' can never be always-allowed.")
    if kind == "tool" and tool_id in {"pc_control", "terminal_run", "delete_folder", "apps"}:
        raise ValueError("Too broad: this tool needs a folder, command or action.")
    if kind == "folder":
        from backend.app.security.path_guard import check_path

        decision = check_path(value)
        if not decision.get("safe"):
            raise ValueError(f"Folder not allowed: {decision.get('reason')}")
        if Path(value).resolve() in {Path.home().resolve(), Path(Path.home().anchor)}:
            raise ValueError("Too broad: pick a folder inside your home, not all of it.")
    rule = {"id": uuid.uuid4().hex[:8], "tool_id": tool_id, "kind": kind, "value": value,
            "label": str(scope.get("label") or f"{tool_id} {value}")[:160], "created_at": time.time()}
    with _lock:
        data = _load()
        data["rules"] = [r for r in data["rules"] if _key(r) != _key(rule)] + [rule]
        _save(data)
    return rule


def rules() -> list[dict]:
    return list(_load()["rules"])


def revoke(rule_id: str) -> bool:
    with _lock:
        data = _load()
        before = len(data["rules"])
        data["rules"] = [r for r in data["rules"] if r["id"] != rule_id and rule_id != "all"]
        _save(data)
        return len(data["rules"]) < before


def clear() -> None:
    with _lock:
        try:
            _store().unlink()
        except OSError:
            pass


def describe(arguments: Any) -> str:  # pragma: no cover - helper for logs
    return json.dumps(arguments, default=str)[:200]
