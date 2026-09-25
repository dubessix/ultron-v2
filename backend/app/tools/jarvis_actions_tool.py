"""jarvis_actions - what did you do, undo that, trust rules (V2 Step 7)."""

from __future__ import annotations

import asyncio
import datetime
import json
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

from backend.app.tools.tool_base import BaseTool


class JarvisActionsArgs(BaseModel):
    action: Literal["log", "undo", "undo_list", "trusted", "revoke"] = Field(
        "log", description="log = what Ultron did; undo = reverse the last file action; trusted / revoke = trust rules.")
    day: Literal["today", "yesterday", "week"] = Field("today", description="log period.")
    id: Optional[str] = Field(None, max_length=40, description="undo: a specific action id; revoke: rule id or 'all'.")


_SKIP_ERRORS = ("PENDING_CONFIRMATION", "CONFIRMATION_REJECTED")


def _short(arguments: str) -> str:
    try:
        data = json.loads(arguments or "{}")
    except ValueError:
        return ""
    parts = []
    for key, value in (data or {}).items():
        if value in (None, "", False, [], {}):
            continue
        text = str(value)
        parts.append(f"{key}={text[:60]}")
        if len(parts) == 3:
            break
    return ", ".join(parts)


def read_log(day: str, limit: int = 30) -> Dict[str, Any]:
    from backend.app.database.db import get_db_connection

    now_local = datetime.datetime.now().astimezone()
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    if day == "yesterday":
        start_local -= datetime.timedelta(days=1)
    elif day == "week":
        start_local -= datetime.timedelta(days=6)
    end_local = start_local + datetime.timedelta(days=1) if day == "yesterday" else now_local + datetime.timedelta(minutes=1)
    fmt = "%Y-%m-%d %H:%M:%S"
    start_utc = start_local.astimezone(datetime.timezone.utc).strftime(fmt)
    end_utc = end_local.astimezone(datetime.timezone.utc).strftime(fmt)
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT timestamp, tool_name, arguments, success, error FROM tool_audit_logs "
            "WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp DESC LIMIT 400",
            (start_utc, end_utc),
        ).fetchall()
    done, failed, counts, items = 0, 0, {}, []
    for timestamp, tool_name, arguments, success, error in rows:
        if tool_name == "Ultron Action Log" or (error and str(error).startswith(_SKIP_ERRORS)):
            continue
        counts[tool_name] = counts.get(tool_name, 0) + 1
        if success:
            done += 1
        else:
            failed += 1
        if len(items) < limit:
            try:
                when = datetime.datetime.strptime(str(timestamp)[:19], fmt).replace(
                    tzinfo=datetime.timezone.utc).astimezone().strftime("%H:%M" if day != "week" else "%a %H:%M")
            except ValueError:
                when = str(timestamp)
            items.append({"time": when, "tool": tool_name, "ok": bool(success), "details": _short(arguments),
                          **({"error": str(error)[:120]} if error and not success else {})})
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:6]
    return {"period": day, "actions_done": done, "failed": failed,
            "most_used": [{"tool": k, "times": v} for k, v in top], "latest": items}


class JarvisActionsTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="jarvis_actions",
            name="Ultron Action Log",
            description="What Ultron did today/yesterday/this week, undo the last file action (delete, move, rename, sort), list or remove always-allow rules.",
            category="system",
            tags=["what did you do", "action log", "history", "undo", "undo that", "trust", "always allow"],
            permission_level=0,
            args_model=JarvisActionsArgs,
            usage_examples=["jarvis_actions(action='log')", "jarvis_actions(action='undo')"],
        )

    def permission_for_arguments(self, arguments: Dict[str, Any]) -> int:
        return 1 if arguments.get("action") in {"undo", "revoke"} else 0

    async def execute(self, **kwargs) -> Dict[str, Any]:
        from backend.app.core import action_journal, trust_rules

        action = kwargs.get("action") or "log"
        if action == "log":
            try:
                return {"success": True, "data": await asyncio.to_thread(read_log, kwargs.get("day") or "today"), "error": None}
            except Exception as exc:
                return {"success": False, "data": {}, "error": f"Action log unavailable: {exc}"}
        if action == "undo":
            result = await asyncio.to_thread(action_journal.undo_last, kwargs.get("id"))
            if not result["success"]:
                return {"success": False, "data": {}, "error": result["error"]}
            return {"success": True, "data": {"undone": result["undone"], "message": result["message"]}, "error": None}
        if action == "undo_list":
            items = [{"id": e["id"], "what": e["summary"], "undone": e.get("undone", False),
                      "when": datetime.datetime.fromtimestamp(e["at"]).strftime("%a %H:%M")}
                     for e in action_journal.recent(10)]
            return {"success": True, "data": {"actions": items}, "error": None}
        if action == "trusted":
            rules = [{"id": r["id"], "allows": r["label"]} for r in trust_rules.rules()]
            return {"success": True, "data": {"rules": rules, "count": len(rules)}, "error": None}
        rule_id = str(kwargs.get("id") or "").strip()
        if not rule_id:
            return {"success": False, "data": {}, "error": "Say which rule to remove (id or 'all')."}
        removed = trust_rules.revoke(rule_id)
        return {"success": removed, "data": {"revoked": rule_id}, "error": None if removed else "No such rule."}
