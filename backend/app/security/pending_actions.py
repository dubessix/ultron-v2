"""One-time confirmations bound to an exact tool call and session."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from typing import Any, Dict, Optional

DEFAULT_TTL_SECONDS = 600.0  # 10 minutes to say yes
USED_MEMORY_SECONDS = 180.0  # a second confirm of a just-used token = "already done"
MAX_PERSISTED = 20
MAX_PENDING = 200
MAX_RESUME_CONTEXT_BYTES = 128 * 1024


def _canonical_arguments(arguments: Dict[str, Any]) -> str:
    return json.dumps(arguments or {}, sort_keys=True, separators=(",", ":"), default=str)


def _argument_hash(arguments: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_arguments(arguments).encode("utf-8")).hexdigest()


def _safe_summary(arguments: Dict[str, Any]) -> dict:
    """Return a confirmation display that never exposes full file content/secrets."""
    summary = {"argument_names": sorted((arguments or {}).keys())}
    for key in (
        "filepath", "folderpath", "source_path", "destination_path", "save_path",
        "directory", "command", "action", "url", "repo_name", "backup_path",
    ):
        if key in arguments:
            value = str(arguments[key])
            summary[key] = value[:240]
    for field in ("content", "search_text", "replace_text"):
        if field in arguments and arguments.get(field) is not None:
            content = str(arguments.get(field) or "")
            summary[f"{field}_sha256"] = hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest()
            summary[f"{field}_bytes"] = len(content.encode("utf-8"))
    return summary


class PendingActionRegistry:
    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS, *, persist: bool = False) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.RLock()
        self._items: Dict[str, Dict[str, Any]] = {}
        self._used: Dict[str, float] = {}
        self._used_reason: Dict[str, str] = {}
        self._persist = persist
        self._loaded = not persist

    # -- disk: waiting actions survive a backend restart (like a checkpointer)
    @staticmethod
    def _store_path():
        from backend.app.runtime_paths import runtime_data_path

        return runtime_data_path("pending_actions.json")

    def _load_locked(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            data = json.loads(self._store_path().read_text(encoding="utf-8"))
            for token, item in (data or {}).items():
                if isinstance(item, dict) and item.get("tool_id") and token not in self._items:
                    self._items[token] = item
        except (OSError, ValueError, TypeError):
            pass

    def _save_locked(self) -> None:
        if not self._persist:
            return
        newest = sorted(self._items.items(), key=lambda kv: kv[1]["created"], reverse=True)[:MAX_PERSISTED]
        try:
            path = self._store_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(dict(newest), default=str), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass

    def _prune_locked(self) -> None:
        self._load_locked()
        now = time.time()
        for token in [
            token for token, item in self._items.items()
            if now - item["created"] >= self._ttl
        ]:
            self._items.pop(token, None)
        for token in [t for t, used in self._used.items() if now - used >= USED_MEMORY_SECONDS]:
            self._used.pop(token, None)
            self._used_reason.pop(token, None)

    def _consume_locked(self, token: str) -> None:
        self._items.pop(token, None)
        self._used[token] = time.time()
        self._save_locked()

    def create(
        self,
        tool_id: str,
        session_id: Optional[str],
        arguments: Dict[str, Any],
        *,
        resume_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Store an exact pending action and private bounded agent-resume state."""
        canonical = _canonical_arguments(arguments)
        safe_resume_context = None
        if resume_context is not None:
            encoded = json.dumps(resume_context, separators=(",", ":"), default=str)
            if len(encoded.encode("utf-8")) <= MAX_RESUME_CONTEXT_BYTES:
                safe_resume_context = json.loads(encoded)
        token = uuid.uuid4().hex
        with self._lock:
            self._prune_locked()
            if len(self._items) >= MAX_PENDING:
                oldest = min(self._items, key=lambda key: self._items[key]["created"])
                self._items.pop(oldest, None)
            self._items[token] = {
                "tool_id": str(tool_id),
                "session_id": session_id,
                "arguments": json.loads(canonical),
                "arguments_hash": _argument_hash(arguments),
                "created": time.time(),
                "resume_context": safe_resume_context,
            }
            self._save_locked()
        return {
            "confirmation_token": token,
            "tool_id": str(tool_id),
            "session_id": session_id,
            "arguments_hash": _argument_hash(arguments),
            "summary": _safe_summary(arguments),
            "expires_in_seconds": self._ttl,
        }

    def validate(
        self,
        token: Optional[str],
        tool_id: str,
        session_id: Optional[str],
        arguments: Dict[str, Any],
        *,
        consume: bool = True,
    ) -> Dict[str, Any]:
        """Validate and optionally consume a token against the exact requested call."""
        if not token:
            return {"valid": False, "reason": "missing_confirmation_token"}
        with self._lock:
            self._prune_locked()
            item = self._items.get(token)
            if item is None:
                return {"valid": False, "reason": "unknown_or_expired_token"}
            if item["tool_id"] != str(tool_id):
                return {"valid": False, "reason": "tool_mismatch"}
            if item["session_id"] != session_id:
                return {"valid": False, "reason": "session_mismatch"}
            if item["arguments_hash"] != _argument_hash(arguments):
                return {"valid": False, "reason": "arguments_mismatch"}
            if consume:
                self._consume_locked(token)
            return {"valid": True, "action": dict(item)}

    def claim(self, token: Optional[str], session_id: Optional[str], *, cancel: bool = False) -> Dict[str, Any]:
        """Atomically consume a stored action without asking the LLM to regenerate it."""
        if not token:
            return {"valid": False, "reason": "missing_confirmation_token"}
        with self._lock:
            self._prune_locked()
            item = self._items.get(token)
            if item is None:
                if token in self._used:
                    return {"valid": False, "reason": self._used_reason.get(token, "already_used")}
                return {"valid": False, "reason": "unknown_or_expired_token"}
            if item["session_id"] != session_id:
                return {"valid": False, "reason": "session_mismatch"}
            self._consume_locked(token)
            if cancel:
                self._used_reason[token] = "cancelled"
            return {"valid": True, "action": dict(item)}

    def set_awaiting(self, session_id: Optional[str], token: Optional[str]) -> None:
        """Mark the ONE action Ultron's latest reply asked about (None = no open question).

        owner_reply can only run this action, so a later "yes" to another
        question can never fire an old waiting action by mistake.
        """
        if not session_id:
            return
        with self._lock:
            self._prune_locked()
            changed = False
            for key, item in self._items.items():
                if item.get("session_id") != session_id:
                    continue
                flag = key == token
                if bool(item.get("awaiting")) != flag:
                    item["awaiting"] = flag
                    changed = True
            if changed:
                self._save_locked()

    def awaiting_for_session(self, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """The action Ultron's latest reply asked about (public fields only), or None."""
        if not session_id:
            return None
        with self._lock:
            self._prune_locked()
            for token, item in self._items.items():
                if item.get("session_id") == session_id and item.get("awaiting"):
                    return {
                        "confirmation_token": token,
                        "tool_id": item["tool_id"],
                        "arguments": dict(item["arguments"]),
                        "arguments_hash": item["arguments_hash"],
                        "summary": _safe_summary(item["arguments"]),
                        "expires_in_seconds": max(0.0, self._ttl - (time.time() - item["created"])),
                    }
        return None

    def pending_count(self) -> int:
        with self._lock:
            self._prune_locked()
            return len(self._items)

    def clear(self) -> None:
        with self._lock:
            self._loaded = True
            self._items.clear()
            self._used.clear()
            self._used_reason.clear()
            self._save_locked()


_pending_actions = PendingActionRegistry(persist=True)


def get_pending_action_registry() -> PendingActionRegistry:
    return _pending_actions
