"""
Ultron Smart Calendar Tool & Time-Block Solver
Implements un-mocked SQLite day planner CRUD, and embeds a mathematical 
Time-Block Solver that computes scheduling overlaps and suggests blank gaps (Level 1 Security).
"""

import uuid
import datetime
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from backend.app.tools.tool_base import BaseTool
from backend.app.database.db import get_db_connection

class CalendarArgs(BaseModel):
    action: str = Field(..., description="Action to perform: create, list, delete, smart_schedule.")
    event_id: Optional[str] = Field(None, description="Event ID (required for deletion).")
    title: Optional[str] = Field(None, description="Title of the schedule event.")
    description: Optional[str] = Field(None, description="Optional description details.")
    start_time: Optional[str] = Field(None, description="Start date/time (ISO format, YYYY-MM-DDTHH:MM:SS).")
    end_time: Optional[str] = Field(None, description="End date/time (ISO format, YYYY-MM-DDTHH:MM:SS).")
    category: Optional[str] = Field("general", description="Category classification: work, development, physical, study, break.")
    duration_hours: Optional[float] = Field(2.0, gt=0, le=12, description="Duration in hours requested for smart_schedule search.")

class CalendarTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="manage_calendar",
            name="Calendar & Smart Scheduler",
            description="Manages day planner schedules and runs a smart algorithm to find available working time slots.",
            category="productivity",
            tags=["calendar", "schedule", "events", "meeting", "timeblock", "planning"],
            permission_level=1,  # Level 1: Write (no manual confirmation required)
            args_model=CalendarArgs,
            usage_examples=[
                "manage_calendar(action='create', title='Web Dev', start_time='2026-08-11T14:00:00', end_time='2026-08-11T16:00:00')",
                "manage_calendar(action='smart_schedule', duration_hours=2.0)"
            ]
        )

    @staticmethod
    def _to_local_aware(value: datetime.datetime) -> datetime.datetime:
        local_tz = datetime.datetime.now().astimezone().tzinfo
        if value.tzinfo is None:
            return value.replace(tzinfo=local_tz)
        return value.astimezone(local_tz)

    def _find_free_slots(self, current_events: List[Dict[str, Any]], duration_hours: float) -> List[Dict[str, Any]]:
        """
        SMART SCHEDULING SOLVER (Requirement 3)
        1. Defines search bounds (Next 5 days, from 09:00 AM to 21:00 PM standard working hours).
        2. Merges and structures overlapping busy events.
        3. Computes inverse free blocks and returns slots larger than requested duration.
        """
        now = datetime.datetime.now().astimezone()
        start_search = now.replace(hour=9, minute=0, second=0, microsecond=0)
        
        # Build search intervals for the next 5 days
        search_days = []
        for i in range(5):
            day_start = start_search + datetime.timedelta(days=i)
            day_end = day_start.replace(hour=21, minute=0, second=0, microsecond=0)
            search_days.append((day_start, day_end))

        # Parse busy periods from existing database events
        busy_intervals = []
        for ev in current_events:
            try:
                ev_start = self._to_local_aware(datetime.datetime.fromisoformat(ev["start_time"]))
                ev_end = self._to_local_aware(datetime.datetime.fromisoformat(ev["end_time"]))
                busy_intervals.append((ev_start, ev_end))
            except Exception:
                continue

        suggested_slots = []
        target_delta = datetime.timedelta(hours=duration_hours)

        for day_start, day_end in search_days:
            # Skip past days/hours
            if day_end <= now:
                continue
            effective_start = max(day_start, now)
            
            # Find all busy intervals for this specific day
            day_busy = []
            for b_start, b_end in busy_intervals:
                # Calculate intersection of busy interval with this day's work hours
                inter_start = max(b_start, effective_start)
                inter_end = min(b_end, day_end)
                if inter_start < inter_end:
                    day_busy.append((inter_start, inter_end))

            # Sort and merge overlapping busy intervals
            day_busy.sort(key=lambda x: x[0])
            merged_busy = []
            for item in day_busy:
                if not merged_busy:
                    merged_busy.append(item)
                else:
                    prev_start, prev_end = merged_busy[-1]
                    curr_start, curr_end = item
                    if curr_start <= prev_end:
                        # Overlap: merge intervals
                        merged_busy[-1] = (prev_start, max(prev_end, curr_end))
                    else:
                        merged_busy.append(item)

            # Compute free gap blocks between busy blocks
            current_cursor = effective_start
            for b_start, b_end in merged_busy:
                gap = b_start - current_cursor
                if gap >= target_delta:
                    suggested_slots.append({
                        "start_time": current_cursor.isoformat(),
                        "end_time": (current_cursor + target_delta).isoformat(),
                        "duration_hours": duration_hours,
                        "day_string": current_cursor.strftime("%A (%b %d)")
                    })
                current_cursor = max(current_cursor, b_end)

            # Final check from last busy block to end of the work day
            final_gap = day_end - current_cursor
            if final_gap >= target_delta:
                suggested_slots.append({
                    "start_time": current_cursor.isoformat(),
                    "end_time": (current_cursor + target_delta).isoformat(),
                    "duration_hours": duration_hours,
                    "day_string": current_cursor.strftime("%A (%b %d)")
                })

            # Limit suggestions to 3 items to avoid cluttering screen
            if len(suggested_slots) >= 3:
                break

        return suggested_slots[:3]

    async def execute(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "list").lower()
        event_id = kwargs.get("event_id")
        title = kwargs.get("title")
        description = kwargs.get("description")
        start_time_str = kwargs.get("start_time")
        end_time_str = kwargs.get("end_time")
        category = kwargs.get("category", "general").lower()
        duration_hours = kwargs.get("duration_hours", 2.0)
        try:
            duration_hours = float(duration_hours)
        except (TypeError, ValueError):
            return {"success": False, "error": "duration_hours must be numeric.", "data": {}}
        if not 0 < duration_hours <= 12:
            return {"success": False, "error": "duration_hours must be greater than 0 and at most 12.", "data": {}}

        with get_db_connection() as conn:
            cursor = conn.cursor()

            if action == "create":
                if not title or not start_time_str or not end_time_str:
                    return {"success": False, "error": "Parameters 'title', 'start_time', and 'end_time' are required.", "data": {}}
                
                # Simple validation checks
                try:
                    dt_start = self._to_local_aware(datetime.datetime.fromisoformat(start_time_str))
                    dt_end = self._to_local_aware(datetime.datetime.fromisoformat(end_time_str))
                    if dt_start >= dt_end:
                        return {"success": False, "error": "Event start_time cannot be greater or equal to end_time.", "data": {}}
                except ValueError:
                    return {"success": False, "error": "Invalid date string formats. Please use ISO 8601 strings.", "data": {}}

                new_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO calendar_events (id, title, description, start_time, end_time, category)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    (new_id, title, description, start_time_str, end_time_str, category)
                )
                conn.commit()
                return {
                    "success": True,
                    "data": {
                        "message": f"Calendar event '{title}' scheduled successfully.",
                        "event_id": new_id,
                        "start_time": start_time_str,
                        "end_time": end_time_str,
                        "category": category
                    },
                    "error": None
                }

            elif action == "list":
                cursor.execute("SELECT * FROM calendar_events ORDER BY start_time ASC;")
                rows = cursor.fetchall()
                results = [dict(row) for row in rows]
                return {
                    "success": True,
                    "data": {
                        "events": results,
                        "count": len(results)
                    },
                    "error": None
                }

            elif action == "delete":
                if not event_id:
                    return {"success": False, "error": "Parameter 'event_id' is required for event deletion.", "data": {}}
                
                cursor.execute("DELETE FROM calendar_events WHERE id = ?;", (event_id,))
                deleted = cursor.rowcount > 0
                conn.commit()
                
                if not deleted:
                    return {"success": False, "error": f"Event '{event_id}' not found.", "data": {}}
                    
                return {
                    "success": True,
                    "data": {"message": f"Successfully deleted calendar event '{event_id}'.", "event_id": event_id},
                    "error": None
                }

            elif action == "smart_schedule":
                # Fetch all upcoming events to feed into solver
                cursor.execute("SELECT * FROM calendar_events WHERE end_time >= CURRENT_TIMESTAMP;")
                rows = cursor.fetchall()
                current_events = [dict(row) for row in rows]
                
                suggestions = self._find_free_slots(current_events, duration_hours)
                
                return {
                    "success": True,
                    "data": {
                        "duration_hours_requested": duration_hours,
                        "suggestions": suggestions,
                        "suggestions_found": len(suggestions)
                    },
                    "error": None
                }

            else:
                return {"success": False, "error": f"Unsupported action '{action}'.", "data": {}}
