"""
Ultron Reminders & Alarms Tool
Implements a production-grade, un-mocked tool for scheduling, snoozing, dismissing,
listing, and deleting local developer reminders and alarms in the SQLite database (Level 1 Security).
Supports intelligent duration offsets (e.g., '10m', '1h', '30s') and recurring rules.
"""

import uuid
import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from backend.app.tools.tool_base import BaseTool
from backend.app.database.db import get_db_connection

class ReminderArgs(BaseModel):
    action: str = Field(..., description="Action to perform: create, snooze, dismiss, list, delete.")
    reminder_id: Optional[str] = Field(None, description="Reminder id (for snooze, dismiss, delete). If unknown, pass the title instead.")
    type: Optional[str] = Field("reminder", description="Type of alert: 'reminder' or 'alarm'.")
    title: Optional[str] = Field(None, description="The subject or description of the alert.")
    description: Optional[str] = Field(None, description="Optional extra details.")
    target_time: Optional[str] = Field(None, description="When, in the owner's local time: 'in 10 minutes', 'tomorrow 10am', 'monday 9am', '2h', or ISO local time. For snooze: how long (default 5m).")
    recurrence: Optional[str] = Field("one_time", description="Recurrence policy: 'one_time', 'daily', 'weekly'.")
    recurrence_details: Optional[str] = Field(None, description="Optional JSON details for recurrence.")

class ReminderTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="manage_reminder",
            name="Reminder & Alarm Manager",
            description="Creates, updates, snoozes, lists, or deletes local reminders and alarms.",
            category="system",
            tags=["reminder", "alarm", "schedule", "time", "clock", "alert"],
            permission_level=1,  # Level 1: Write (no manual confirmation required for CRUD)
            args_model=ReminderArgs,
            usage_examples=[
                "manage_reminder(action='create', type='alarm', title='Git Commit', target_time='10m')",
                "manage_reminder(action='list')",
                "manage_reminder(action='dismiss', reminder_id='some-uuid-here')"
            ]
        )

    def _parse_time(self, time_str: str) -> datetime.datetime:
        """Owner-local natural/relative/ISO time -> aware UTC datetime."""
        from backend.app.core.time_parse import parse_when

        return parse_when(time_str).astimezone(datetime.timezone.utc)

    @staticmethod
    def _local_words(value: str) -> str:
        from backend.app.core.time_parse import speakable_time

        try:
            return speakable_time(datetime.datetime.fromisoformat(value))
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _find_id(cursor, reminder_id: str) -> Optional[str]:
        """Accept a real id, or a title the model remembered instead of the id."""
        row = cursor.execute("SELECT id FROM reminders_alarms WHERE id = ?;", (reminder_id,)).fetchone()
        if row:
            return row["id"]
        rows = cursor.execute(
            "SELECT id FROM reminders_alarms WHERE lower(title) LIKE ? "
            "AND status IN ('pending', 'snoozed', 'triggered') ORDER BY target_time ASC LIMIT 2;",
            (f"%{reminder_id.strip().lower()}%",),
        ).fetchall()
        return rows[0]["id"] if len(rows) == 1 else None

    async def execute(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "list").lower()
        reminder_id = kwargs.get("reminder_id")
        alert_type = kwargs.get("type", "reminder").lower()
        title = kwargs.get("title")
        description = kwargs.get("description")
        target_time_str = kwargs.get("target_time")
        recurrence = kwargs.get("recurrence", "one_time").lower()
        recurrence_details = kwargs.get("recurrence_details")

        if action not in {"create", "list", "snooze", "dismiss", "delete"}:
            return {"success": False, "error": f"Unsupported action '{action}'.", "data": {}}
        if alert_type not in {"reminder", "alarm"}:
            return {"success": False, "error": f"Unsupported alert type '{alert_type}'.", "data": {}}
        if recurrence not in {"one_time", "daily", "weekly"}:
            return {"success": False, "error": f"Unsupported recurrence '{recurrence}'.", "data": {}}

        with get_db_connection() as conn:
            cursor = conn.cursor()

            if action == "create":
                if not title:
                    return {"success": False, "error": "Parameter 'title' is required for action='create'.", "data": {}}
                if not target_time_str:
                    return {"success": False, "error": "Parameter 'target_time' is required for action='create'.", "data": {}}
                
                try:
                    parsed_dt = self._parse_time(target_time_str)
                except ValueError as exc:
                    return {"success": False, "error": str(exc), "data": {}}
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                if parsed_dt < now_utc - datetime.timedelta(minutes=1):
                    return {
                        "success": False,
                        "error": (
                            f"That time ({self._local_words(parsed_dt.isoformat())}) is already past. "
                            "Ask the owner for a future time."
                        ),
                        "data": {},
                    }
                new_id = str(uuid.uuid4())
                
                cursor.execute(
                    """
                    INSERT INTO reminders_alarms (
                        id, type, title, description, target_time, recurrence, recurrence_details, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        new_id,
                        alert_type,
                        title,
                        description,
                        parsed_dt.isoformat(),
                        recurrence,
                        recurrence_details,
                        "pending"
                    )
                )
                conn.commit()
                
                return {
                    "success": True,
                    "data": {
                        "message": f"Successfully created {alert_type} '{title}' for {self._local_words(parsed_dt.isoformat())}.",
                        "id": new_id,
                        "target_time": parsed_dt.isoformat(),
                        "when_local": self._local_words(parsed_dt.isoformat()),
                        "type": alert_type,
                        "recurrence": recurrence
                    },
                    "error": None
                }

            elif action == "list":
                cursor.execute(
                    """
                    SELECT id, type, title, description, target_time, recurrence, recurrence_details, snooze_count, status, created_at 
                    FROM reminders_alarms 
                    WHERE status IN ('pending', 'snoozed')
                    ORDER BY target_time ASC
                    LIMIT 50;
                    """
                )
                rows = cursor.fetchall()
                results = [
                    {**dict(row), "when_local": self._local_words(row["target_time"])}
                    for row in rows
                ]
                
                return {
                    "success": True,
                    "data": {
                        "reminders": results,
                        "count": len(results)
                    },
                    "error": None
                }

            elif action == "snooze":
                if not reminder_id:
                    return {"success": False, "error": "Parameter 'reminder_id' is required for action='snooze'.", "data": {}}
                reminder_id = self._find_id(cursor, reminder_id) or reminder_id
                
                # Fetch existing record to increment snooze count
                cursor.execute("SELECT snooze_count, title FROM reminders_alarms WHERE id = ?;", (reminder_id,))
                row = cursor.fetchone()
                if not row:
                    return {"success": False, "error": f"Reminder ID '{reminder_id}' not found.", "data": {}}
                
                current_snooze = row["snooze_count"] or 0
                try:
                    snoozed_time = self._parse_time(target_time_str) if target_time_str else (
                        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)
                    )
                except ValueError as exc:
                    return {"success": False, "error": str(exc), "data": {}}
                
                cursor.execute(
                    """
                    UPDATE reminders_alarms 
                    SET status = 'snoozed', snooze_count = ?, target_time = ? 
                    WHERE id = ?;
                    """,
                    (current_snooze + 1, snoozed_time.isoformat(), reminder_id)
                )
                conn.commit()
                
                return {
                    "success": True,
                    "data": {
                        "message": f"Snoozed '{row['title']}' until {self._local_words(snoozed_time.isoformat())}.",
                        "id": reminder_id,
                        "new_target_time": snoozed_time.isoformat(),
                        "snooze_count": current_snooze + 1
                    },
                    "error": None
                }

            elif action == "dismiss":
                if not reminder_id:
                    return {"success": False, "error": "Parameter 'reminder_id' is required for action='dismiss'.", "data": {}}
                reminder_id = self._find_id(cursor, reminder_id) or reminder_id
                
                cursor.execute("SELECT title, type, recurrence, target_time FROM reminders_alarms WHERE id = ?;", (reminder_id,))
                row = cursor.fetchone()
                if not row:
                    return {"success": False, "error": f"Reminder ID '{reminder_id}' not found.", "data": {}}
                
                rec = row["recurrence"].lower()
                title_val = row["title"]
                
                if rec == "one_time":
                    cursor.execute("UPDATE reminders_alarms SET status = 'dismissed' WHERE id = ?;", (reminder_id,))
                else:
                    # Recurring reminders: compute next interval
                    current_target = datetime.datetime.fromisoformat(row["target_time"])
                    if rec == "daily":
                        next_target = current_target + datetime.timedelta(days=1)
                    elif rec == "weekly":
                        next_target = current_target + datetime.timedelta(days=7)
                    else:
                        return {
                            "success": False,
                            "error": f"Stored reminder has unsupported recurrence '{rec}'.",
                            "data": {"id": reminder_id},
                        }

                    # Reset target time and set back to pending for next trigger
                    cursor.execute(
                        """
                        UPDATE reminders_alarms 
                        SET target_time = ?, status = 'pending', snooze_count = 0 
                        WHERE id = ?;
                        """,
                        (next_target.isoformat(), reminder_id)
                    )
                conn.commit()
                
                return {
                    "success": True,
                    "data": {
                        "message": f"Successfully dismissed '{title_val}'.",
                        "id": reminder_id,
                        "recurrence": rec,
                        "next_target_time": next_target.isoformat() if rec != "one_time" else None
                    },
                    "error": None
                }

            elif action == "delete":
                if not reminder_id:
                    return {"success": False, "error": "Parameter 'reminder_id' is required for action='delete'.", "data": {}}
                reminder_id = self._find_id(cursor, reminder_id) or reminder_id
                
                cursor.execute("DELETE FROM reminders_alarms WHERE id = ?;", (reminder_id,))
                deleted = cursor.rowcount > 0
                conn.commit()
                
                if not deleted:
                    return {"success": False, "error": f"Reminder ID '{reminder_id}' not found.", "data": {}}
                    
                return {
                    "success": True,
                    "data": {
                        "message": f"Successfully deleted reminder '{reminder_id}'.",
                        "id": reminder_id
                    },
                    "error": None
                }

            else:
                return {"success": False, "error": f"Unsupported action '{action}'.", "data": {}}
