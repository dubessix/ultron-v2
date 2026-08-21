"""Daily briefing from local SQLite plus explicitly sourced live data."""

from __future__ import annotations

import asyncio
import datetime
from typing import Any, Dict

import httpx
from pydantic import BaseModel, Field

from backend.app.database.db import get_db_connection
from backend.app.tools._realsearch import real_web_search
from backend.app.tools.tool_base import BaseTool


class DailyBriefingArgs(BaseModel):
    include_weather: bool = Field(True, description="Fetch live Open-Meteo current weather.")
    include_tasks: bool = Field(True, description="Query unresolved high-priority local tasks.")
    include_schedule: bool = Field(True, description="Query today's local calendar events.")
    include_news: bool = Field(True, description="Fetch currently verifiable public AI-news search results.")


def _greeting_for_hour(hour: int) -> tuple[str, str]:
    """Return a local-time greeting suitable for first-open briefing at any hour."""
    if 5 <= hour < 12:
        return "morning", "Good morning, Debjeet, Sir."
    if 12 <= hour < 17:
        return "afternoon", "Good afternoon, Debjeet, Sir."
    if 17 <= hour < 22:
        return "evening", "Good evening, Debjeet, Sir."
    return "night", "Good evening, Debjeet, Sir. It is a late-hour briefing."


class DailyBriefingTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="daily_briefing",
            name="Daily Briefing Builder",
            description="Compiles local calendar/tasks with sourced live weather and public search results.",
            category="productivity",
            tags=["briefing", "schedule", "routine", "weather", "status", "summary"],
            permission_level=1,
            args_model=DailyBriefingArgs,
            usage_examples=["daily_briefing()"],
        )

    async def _get_local_weather(self) -> Dict[str, Any]:
        lat, lon = 22.5726, 88.3639
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current_weather": "true",
                        "timezone": "auto",
                    },
                )
        except Exception as exc:
            return {
                "available": False,
                "source": "Open-Meteo",
                "temperature": None,
                "windspeed": None,
                "observed_at": None,
                "error": str(exc),
            }
        if response.status_code != 200:
            return {
                "available": False,
                "source": "Open-Meteo",
                "temperature": None,
                "windspeed": None,
                "observed_at": None,
                "error": f"HTTP {response.status_code}",
            }
        try:
            current = (response.json() or {}).get("current_weather") or {}
            temperature = current.get("temperature")
            windspeed = current.get("windspeed")
            if not isinstance(temperature, (int, float)):
                raise ValueError("temperature missing")
        except (TypeError, ValueError) as exc:
            return {
                "available": False,
                "source": "Open-Meteo",
                "temperature": None,
                "windspeed": None,
                "observed_at": None,
                "error": f"incomplete provider data: {exc}",
            }
        return {
            "available": True,
            "source": "Open-Meteo",
            "temperature": f"{float(temperature):.1f}°C",
            "windspeed": (
                f"{float(windspeed):.1f} km/h"
                if isinstance(windspeed, (int, float))
                else None
            ),
            "observed_at": current.get("time"),
            "error": None,
        }

    async def _get_live_news(self) -> Dict[str, Any]:
        try:
            results = await real_web_search(
                "artificial intelligence technology news today",
                limit=3,
            )
        except Exception as exc:
            return {"available": False, "source": "public web search", "items": [], "error": str(exc)}
        items = []
        for result in results:
            title = str(result.get("title") or "").strip()
            url = str(result.get("url") or "").strip()
            if not title or not url.startswith(("http://", "https://")):
                continue
            items.append({
                "title": title,
                "url": url,
                "snippet": str(result.get("snippet") or "").strip()[:240],
                "source": result.get("source") or "public web search",
            })
        return {
            "available": bool(items),
            "source": "public web search",
            "items": items,
            "error": None if items else "No current results could be verified.",
        }

    async def execute(self, **kwargs) -> Dict[str, Any]:
        include_weather = bool(kwargs.get("include_weather", True))
        include_tasks = bool(kwargs.get("include_tasks", True))
        include_schedule = bool(kwargs.get("include_schedule", True))
        include_news = bool(kwargs.get("include_news", True))

        now = datetime.datetime.now()
        today_date = now.strftime("%A, %B %d, %Y")
        weather_data = {"available": False, "status": "not_requested"}
        news_data = {"available": False, "status": "not_requested", "items": []}
        if include_weather and include_news:
            weather_data, news_data = await asyncio.gather(
                self._get_local_weather(),
                self._get_live_news(),
            )
        elif include_weather:
            weather_data = await self._get_local_weather()
        elif include_news:
            news_data = await self._get_live_news()
        schedule_events = []
        high_priority_tasks = []

        with get_db_connection() as conn:
            if include_schedule:
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
                today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
                schedule_events = [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT title, start_time, end_time, category
                        FROM calendar_events
                        WHERE start_time >= ? AND start_time <= ?
                        ORDER BY start_time ASC;
                        """,
                        (today_start, today_end),
                    ).fetchall()
                ]
            if include_tasks:
                high_priority_tasks = [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT id, title, project_name, module_name, priority
                        FROM project_tasks
                        WHERE status != 'done' AND priority = 'high'
                        ORDER BY created_at ASC
                        LIMIT 3;
                        """
                    ).fetchall()
                ]

        greeting_period, greeting = _greeting_for_hour(now.hour)
        lines = [f"=== DAILY BRIEFING: {today_date.upper()} ===", "", greeting]
        if include_weather:
            if weather_data.get("available"):
                wind = weather_data.get("windspeed") or "windspeed not reported"
                lines.append(
                    f"• Weather ({weather_data['source']}): {weather_data['temperature']}, {wind}."
                )
            else:
                lines.append("• Weather: live data unavailable; no estimate was substituted.")

        lines.extend(["", "[SCHEDULE & TIMELINE]"])
        if schedule_events:
            for event in schedule_events:
                time_text = str(event["start_time"]).split("T")[-1][:5]
                category = str(event.get("category") or "general").upper()
                lines.append(f"  - [{time_text}] {event['title']} ({category})")
        else:
            lines.append("  - No local events are scheduled for today.")

        lines.extend(["", "[HIGH-PRIORITY BACKLOG]"])
        if high_priority_tasks:
            for task in high_priority_tasks:
                lines.append(
                    f"  - [HIGH] {task['title']} ({task['project_name']}/{task['module_name']})"
                )
        else:
            lines.append("  - No unresolved high-priority local tasks were found.")

        if include_news:
            lines.extend(["", "[LIVE PUBLIC SEARCH RESULTS]"])
            if news_data.get("available"):
                for index, item in enumerate(news_data["items"], 1):
                    lines.append(f"  {index}. {item['title']} — {item['url']}")
            else:
                lines.append("  - Current results unavailable; no headlines were substituted.")

        return {
            "success": True,
            "data": {
                "date": today_date,
                "greeting_period": greeting_period,
                "briefing_text": "\n".join(lines),
                "weather": weather_data,
                "news": news_data,
                "events_count": len(schedule_events),
                "tasks_count": len(high_priority_tasks),
            },
            "error": None,
        }
