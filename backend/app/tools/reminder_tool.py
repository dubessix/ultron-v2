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
    reminder_id: Optional[str] = Field(None, description="The UUID of the reminder or alarm (required for snooze, dismiss, delete).")
    type: Optional[str] = Field("reminder", description="Type of alert: 'reminder' or 'alarm'.")
    title: Optional[str] = Field(None, description="The subject or description of the alert.")
    description: Optional[str] = Field(None, description="Optional extra details.")
    target_time: Optional[str] = Field(None, description="Target time. Can be ISO format (YYYY-MM-DDTHH:MM:SS) or relative offset (e.g. '10m', '1h', '30s', '+5m').")
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
        """Parses ISO timestamp or parses duration offsets (e.g., '10m', '1h', '30s')."""
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # Try relative offset parsing first
        clean = time_str.strip().lower().lstrip("+")
        if not clean or clean.startswith("-"):
            raise ValueError("target_time must be a future ISO time or positive relative duration.")

        # Matches formats like '10m', '30s', '2h', '1d'
        digits = "".join([c for c in clean if c.isdigit() or c == "."])
        unit = "".join([c for c in clean if not c.isdigit() and c != "."])
        
        if digits and unit:
            try:
                val = float(digits)
                if val <= 0:
                    raise ValueError("Relative target_time must be greater than zero.")
                if "s" in unit:
                    return now + datetime.timedelta(seconds=val)
                elif "m" in unit:
                    return now + datetime.timedelta(minutes=val)
                elif "h" in unit:
                    return now + datetime.timedelta(hours=val)
                elif "d" in unit:
                    return now + datetime.timedelta(days=val)
            except Exception:
                pass
                
        # Try ISO parsing
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.datetime.strptime(time_str, fmt)
                return dt.replace(tzinfo=datetime.timezone.utc)
            except ValueError:
                continue
                
        raise ValueError(
            "Invalid target_time. Use ISO format or a positive relative value such as 10m, 2h, or 1d."
        )

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
                        "message": f"Successfully created {alert_type} '{title}'.",
                        "id": new_id,
                        "target_time": parsed_dt.isoformat(),
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
                    ORDER BY target_time ASC;
                    """
                )
                rows = cursor.fetchall()
                results = [dict(row) for row in rows]
                
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
                
                # Fetch existing record to increment snooze count
                cursor.execute("SELECT snooze_count, title FROM reminders_alarms WHERE id = ?;", (reminder_id,))
                row = cursor.fetchone()
                if not row:
                    return {"success": False, "error": f"Reminder ID '{reminder_id}' not found.", "data": {}}
                
                current_snooze = row["snooze_count"] or 0
                snoozed_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)
                
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
                        "message": f"Successfully snoozed '{row['title']}' for 5 minutes.",
                        "id": reminder_id,
                        "new_target_time": snoozed_time.isoformat(),
                        "snooze_count": current_snooze + 1
                    },
                    "error": None
                }

            elif action == "dismiss":
                if not reminder_id:
                    return {"success": False, "error": "Parameter 'reminder_id' is required for action='dismiss'.", "data": {}}
                
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
