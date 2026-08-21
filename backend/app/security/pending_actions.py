"""One-time confirmations bound to an exact tool call and session."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from typing import Any, Dict, Optional

DEFAULT_TTL_SECONDS = 300.0
MAX_PENDING = 200


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
    if "content" in arguments:
        content = str(arguments.get("content") or "")
        summary["content_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        summary["content_bytes"] = len(content.encode("utf-8"))
    return summary


class PendingActionRegistry:
    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.RLock()
        self._items: Dict[str, Dict[str, Any]] = {}

    def _prune_locked(self) -> None:
        now = time.time()
        for token in [
            token for token, item in self._items.items()
            if now - item["created"] >= self._ttl
        ]:
            self._items.pop(token, None)

    def create(
        self,
        tool_id: str,
        session_id: Optional[str],
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Store an exact pending action and return its client-safe description."""
        canonical = _canonical_arguments(arguments)
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
            }
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
                self._items.pop(token, None)
            return {"valid": True, "action": dict(item)}

    def claim(self, token: Optional[str], session_id: Optional[str]) -> Dict[str, Any]:
        """Atomically consume a stored action without asking the LLM to regenerate it."""
        if not token:
            return {"valid": False, "reason": "missing_confirmation_token"}
        with self._lock:
            self._prune_locked()
            item = self._items.get(token)
            if item is None:
                return {"valid": False, "reason": "unknown_or_expired_token"}
            if item["session_id"] != session_id:
                return {"valid": False, "reason": "session_mismatch"}
            self._items.pop(token, None)
            return {"valid": True, "action": dict(item)}

    def pending_count(self) -> int:
        with self._lock:
            self._prune_locked()
            return len(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_pending_actions = PendingActionRegistry()


def get_pending_action_registry() -> PendingActionRegistry:
    return _pending_actions
