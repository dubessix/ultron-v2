"""show_widget - the AI decides which panel is on the owner's screen."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

from backend.app.core.widgets import WIDGETS
from backend.app.tools.tool_base import BaseTool


class ShowWidgetArgs(BaseModel):
    widget_id: Optional[str] = Field(
        None, max_length=40, description="Panel id: " + ", ".join(WIDGETS) + ". Not needed for close_all."
    )
    action: Literal["open", "close", "close_all"] = Field("open", description="open, close, or close_all panels.")
    refresh: bool = Field(False, description="Reload the panel's data if it is already open.")


_ALIASES = {
    "tasks": "todo", "task": "todo", "to_do": "todo", "todos": "todo", "todo_list": "todo",
    "reminders": "reminder", "alarm": "reminder", "alarms": "reminder",
    "files": "file_explorer", "folders": "file_explorer", "explorer": "file_explorer", "file": "file_explorer",
    "schedule": "calendar", "stocks": "market", "crypto": "market", "news": "world_monitor",
    "search": "universal_search", "research": "deep_research", "briefing": "daily_briefing",
    "cpu": "system", "ram": "system", "system_metrics": "system", "spotify": "music",
    "notifications": "notification", "security": "security_guardian", "code": "coding",
}


def normalize_widget_id(value: Any) -> Optional[str]:
    key = "_".join(str(value or "").strip().lower().replace("-", " ").split())
    if key.endswith("_widget"):
        key = key[: -len("_widget")]
    if key in WIDGETS:
        return key
    return _ALIASES.get(key)


class ShowWidgetTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="show_widget",
            name="Screen Panels",
            description="Open, close or refresh a panel on the owner's screen, or close all panels.",
            category="system",
            tags=["widget", "panel", "screen", "show", "display"],
            permission_level=0,
            args_model=ShowWidgetArgs,
            usage_examples=["show_widget(widget_id='calendar')", "show_widget(action='close_all')"],
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        action = str(kwargs.get("action") or "open").lower()
        if action == "close_all":
            return {"success": True, "data": {"action": "close_all_widgets"}}
        widget = normalize_widget_id(kwargs.get("widget_id"))
        if not widget:
            return {
                "success": False,
                "error": f"Unknown panel '{kwargs.get('widget_id')}'. Choose one of: {', '.join(WIDGETS)}.",
            }
        return {
            "success": True,
            "data": {
                "action": "close_widget" if action == "close" else "open_widget",
                "widget_id": widget,
                "refresh": bool(kwargs.get("refresh")),
                "label": WIDGETS[widget],
            },
        }
