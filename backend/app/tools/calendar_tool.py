"""
Ultron Smart Calendar Tool & Time-Block Solver
Implements un-mocked SQLite day planner CRUD, and embeds a mathematical 
Time-Block Solver that computes scheduling overlaps and suggests blank gaps (Level 1 Security).
"""

import json
import uuid
import datetime
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from backend.app.tools.tool_base import BaseTool
from backend.app.database.db import get_db_connection

class CalendarArgs(BaseModel):
    action: str = Field(..., description=(
        "create, list, delete, smart_schedule; plan = save several blocks at once (a study or day plan); "
        "mark = a plan block done or skipped; shift = move a plan block and the rest of that day's plan."))
    event_id: Optional[str] = Field(None, description="Event ID (required for deletion).")
    title: Optional[str] = Field(None, description="Title of the schedule event.")
    description: Optional[str] = Field(None, description="Optional description details.")
    start_time: Optional[str] = Field(None, description="Start date/time (ISO format, YYYY-MM-DDTHH:MM:SS).")
    end_time: Optional[str] = Field(None, description="End date/time (ISO format, YYYY-MM-DDTHH:MM:SS).")
    category: Optional[str] = Field("general", description="Category classification: work, development, physical, study, break.")
    duration_hours: Optional[float] = Field(2.0, gt=0, le=12, description="Duration in hours requested for smart_schedule search.")
    blocks: Optional[List[Dict[str, Any]]] = Field(None, description=(
        "For plan: [{title, start_time, end_time, say?, check_in?}] local ISO; say=spoken at start, "
        "check_in=ask at end"))
    status: Optional[str] = Field(None, description="For mark: done or skipped.")
    minutes: Optional[int] = Field(None, description="For shift: minutes to move (negative = earlier).")

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

    MAX_PLAN_BLOCKS = 12
    PLAN = "plan"  # open block; plan_done / plan_skipped once checked

    @staticmethod
    def _find_plan_block(cursor, ref: str) -> Optional[dict]:
        """A plan block by id, or by (part of) its title: the open one closest to now."""
        row = cursor.execute("SELECT * FROM calendar_events WHERE id = ?;", (ref,)).fetchone()
        if row:
            return dict(row) if str(row["category"] or "").startswith("plan") else None
        rows = [dict(r) for r in cursor.execute(
            "SELECT * FROM calendar_events WHERE category LIKE 'plan%' AND lower(title) LIKE ? "
            "ORDER BY start_time ASC LIMIT 40;", (f"%{str(ref).strip().lower()}%",))]
        if not rows:
            return None
        now = datetime.datetime.now().astimezone()

        def distance(item: dict) -> float:
            try:
                start = CalendarTool._to_local_aware(datetime.datetime.fromisoformat(item["start_time"]))
                return abs((start - now).total_seconds()) + (0 if item["category"] == "plan" else 10 ** 9)
            except (TypeError, ValueError):
                return float("inf")

        return min(rows, key=distance)

    def _save_plan(self, cursor, blocks: Any) -> Dict[str, Any]:
        if not isinstance(blocks, list) or not blocks:
            return {"success": False, "error": "blocks must be a non-empty list.", "data": {}}
        if len(blocks) > self.MAX_PLAN_BLOCKS:
            return {"success": False, "error": f"At most {self.MAX_PLAN_BLOCKS} blocks per plan.", "data": {}}
        now = datetime.datetime.now().astimezone()
        rows = []
        for number, block in enumerate(blocks, 1):
            if not isinstance(block, dict):
                return {"success": False, "error": f"Block {number} must be an object.", "data": {}}
            title = " ".join(str(block.get("title") or "").split())[:120]
            try:
                start = self._to_local_aware(datetime.datetime.fromisoformat(str(block.get("start_time"))))
                end = self._to_local_aware(datetime.datetime.fromisoformat(str(block.get("end_time"))))
            except ValueError:
                return {"success": False, "error": f"Block {number}: use ISO local times.", "data": {}}
            if not title or start >= end:
                return {"success": False, "error": f"Block {number}: needs a title and start before end.", "data": {}}
            if end <= now:
                return {"success": False, "error": f"Block {number} ({title}) is already over.", "data": {}}
            if end - start > datetime.timedelta(hours=12):
                return {"success": False, "error": f"Block {number} is longer than 12 hours.", "data": {}}
            extra = {"check_in": bool(block.get("check_in", True))}
            say = " ".join(str(block.get("say") or "").split())[:160]
            if say:
                extra["say"] = say
            rows.append((str(uuid.uuid4()), title, json.dumps(extra), start.replace(tzinfo=None).isoformat(timespec="seconds"),
                         end.replace(tzinfo=None).isoformat(timespec="seconds"), self.PLAN))
        # all or nothing: never half a plan
        cursor.executemany(
            "INSERT INTO calendar_events (id, title, description, start_time, end_time, category) "
            "VALUES (?, ?, ?, ?, ?, ?);", rows)
        return {"success": True, "error": None, "data": {
            "message": f"Plan saved: {len(rows)} blocks. Each block is announced when it starts.",
            "blocks": [{"event_id": r[0], "title": r[1], "start_time": r[3], "end_time": r[4]} for r in rows]}}

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

            elif action == "plan":
                result = self._save_plan(cursor, kwargs.get("blocks"))
                if result["success"]:
                    conn.commit()
                return result

            elif action == "mark":
                status = str(kwargs.get("status") or "done").lower()
                if status not in {"done", "skipped"}:
                    return {"success": False, "error": "status must be done or skipped.", "data": {}}
                block = self._find_plan_block(cursor, event_id or title or "")
                if not block:
                    return {"success": False, "error": "No plan block matches that.", "data": {}}
                cursor.execute("UPDATE calendar_events SET category = ? WHERE id = ?;", (f"plan_{status}", block["id"]))
                conn.commit()
                return {"success": True, "error": None, "data": {
                    "message": f"{block['title']} marked {status}.", "event_id": block["id"]}}

            elif action == "shift":
                try:
                    minutes = int(kwargs.get("minutes") or 0)
                except (TypeError, ValueError):
                    minutes = 0
                if not minutes or abs(minutes) > 12 * 60:
                    return {"success": False, "error": "minutes must be between -720 and 720, not 0.", "data": {}}
                block = self._find_plan_block(cursor, event_id or title or "")
                if not block:
                    return {"success": False, "error": "No plan block matches that.", "data": {}}
                first = datetime.datetime.fromisoformat(block["start_time"])
                later = [dict(r) for r in cursor.execute(
                    "SELECT id, start_time, end_time FROM calendar_events WHERE category = 'plan';")]
                moved = []
                step = datetime.timedelta(minutes=minutes)
                for item in later:
                    try:
                        start = datetime.datetime.fromisoformat(item["start_time"])
                        end = datetime.datetime.fromisoformat(item["end_time"])
                    except (TypeError, ValueError):
                        continue
                    same_day = start.date() == first.date()
                    if item["id"] == block["id"] or (same_day and start >= first):
                        cursor.execute("UPDATE calendar_events SET start_time = ?, end_time = ? WHERE id = ?;",
                                       ((start + step).isoformat(timespec="seconds"),
                                        (end + step).isoformat(timespec="seconds"), item["id"]))
                        moved.append(item["id"])
                conn.commit()
                return {"success": True, "error": None, "data": {
                    "message": f"Moved {len(moved)} plan block(s) by {minutes} minutes.", "moved": len(moved)}}

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
