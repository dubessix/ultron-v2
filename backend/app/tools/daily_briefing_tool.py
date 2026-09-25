"""Daily briefing from local SQLite plus explicitly sourced live data.

Two outputs, built from real data only (no LLM call, zero tokens):
  * ``speech``        - what Ultron SAYS: 4-6 natural sentences, plain words,
                        no symbols, no links. The most important thing first
                        and one clear suggestion at the end.
  * ``briefing_text`` - what the chat SHOWS: short sections, clean times,
                        headlines with the site name instead of long links.
If a live source fails, both say so honestly; nothing is invented.
"""

from __future__ import annotations

import asyncio
import datetime
import os
import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from backend.app.database.db import get_db_connection
from backend.app.tools._realsearch import real_web_search
from backend.app.tools.tool_base import BaseTool

# Home location for weather. Default Kolkata; set ULTRON_HOME_LAT / _LON for
# the exact town (e.g. Bhatpara 22.87, 88.41).
_DEFAULT_LAT, _DEFAULT_LON = 22.5726, 88.3639
_RAIN_ALERT_PERCENT = 50


class DailyBriefingArgs(BaseModel):
    include_weather: bool = Field(True, description="Fetch live Open-Meteo current weather.")
    include_tasks: bool = Field(True, description="Query open tasks due today, overdue, or high priority.")
    include_schedule: bool = Field(True, description="Query today's local calendar events and reminders.")
    include_news: bool = Field(True, description="Fetch currently verifiable public AI-news search results.")


def _greeting_for_hour(hour: int) -> tuple[str, str]:
    """Return a local-time greeting suitable for first-open briefing at any hour."""
    if 5 <= hour < 12:
        return "morning", "Good morning, Sir."
    if 12 <= hour < 17:
        return "afternoon", "Good afternoon, Sir."
    if 17 <= hour < 22:
        return "evening", "Good evening, Sir."
    return "night", "You're up late, Sir. Here's a quick late-hour briefing."


# ---------------------------------------------------------------------------
# small helpers (plain words for the voice)
# ---------------------------------------------------------------------------
def _local_now() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


def _as_local(value: Any) -> Optional[datetime.datetime]:
    """ISO text -> aware local datetime. Naive values are local; a plain date is end of day."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00").replace(" ", "T", 1)
    try:
        if len(text) == 10:
            day = datetime.date.fromisoformat(text)
            return datetime.datetime.combine(day, datetime.time(23, 59)).astimezone()
        return datetime.datetime.fromisoformat(text).astimezone()
    except ValueError:
        return None


def _date_only(value: Any) -> bool:
    return bool(value) and len(str(value).strip()) == 10


def _clock(moment: datetime.datetime) -> str:
    hour = moment.hour % 12 or 12
    suffix = "AM" if moment.hour < 12 else "PM"
    return f"{hour} {suffix}" if moment.minute == 0 else f"{hour}:{moment.minute:02d} {suffix}"


def _clean(title: Any) -> str:
    return " ".join(str(title or "").replace("_", " ").split()).strip(" .")[:80]


def _join(items: list[str]) -> str:
    items = [item for item in items if item]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _condition(code: Any) -> Optional[str]:
    try:
        value = int(code)
    except (TypeError, ValueError):
        return None
    if value == 0:
        return "clear skies"
    if value in (1, 2):
        return "partly cloudy"
    if value == 3:
        return "cloudy"
    if value in (45, 48):
        return "foggy"
    if 51 <= value <= 57:
        return "drizzle"
    if 61 <= value <= 67 or 80 <= value <= 82:
        return "rain"
    if 71 <= value <= 77 or 85 <= value <= 86:
        return "snow"
    if 95 <= value <= 99:
        return "thunderstorms"
    return None


def _headline(title: str, url: str) -> tuple[str, str]:
    """'Big news - Reuters' + url -> ('Big news', 'Reuters' or 'site.com')."""
    source = ""
    match = re.search(r"\s[-|–—]\s([^-|–—]{2,40})$", title)
    if match:
        source = match.group(1).strip()
        title = title[: match.start()].strip()
    if not source:
        host = (urlparse(url).hostname or "").removeprefix("www.")
        source = "" if host.endswith("news.google.com") else host
    return _clean(title)[:90], source


def _is_index_page(title: str) -> bool:
    """Search sometimes returns news *section pages*, not stories. Skip them."""
    lowered = title.lower()
    return (
        lowered.startswith("google news")
        or bool(re.match(r"^(ai|tech|technology|artificial intelligence) news\b", lowered))
        or "latest headlines" in lowered
        or "latest news" in lowered
    )


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

    # -- live sources ---------------------------------------------------
    @staticmethod
    def _home() -> tuple[float, float]:
        try:
            return float(os.getenv("ULTRON_HOME_LAT", _DEFAULT_LAT)), float(os.getenv("ULTRON_HOME_LON", _DEFAULT_LON))
        except ValueError:
            return _DEFAULT_LAT, _DEFAULT_LON

    async def _get_local_weather(self) -> Dict[str, Any]:
        lat, lon = self._home()
        unavailable = {
            "available": False,
            "source": "Open-Meteo",
            "temperature": None,
            "windspeed": None,
            "observed_at": None,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current_weather": "true",
                        "hourly": "precipitation_probability",
                        "daily": "temperature_2m_max,temperature_2m_min",
                        "forecast_days": 1,
                        "timezone": "auto",
                    },
                )
        except Exception as exc:
            return {**unavailable, "error": str(exc)}
        if response.status_code != 200:
            return {**unavailable, "error": f"HTTP {response.status_code}"}
        try:
            body = response.json() or {}
            current = body.get("current_weather") or {}
            temperature = current.get("temperature")
            windspeed = current.get("windspeed")
            if not isinstance(temperature, (int, float)):
                raise ValueError("temperature missing")
        except (TypeError, ValueError, AttributeError) as exc:
            return {**unavailable, "error": f"incomplete provider data: {exc}"}

        daily = body.get("daily") or {}
        high = (daily.get("temperature_2m_max") or [None])[0]
        low = (daily.get("temperature_2m_min") or [None])[0]
        rain_at = None
        hourly = body.get("hourly") or {}
        now_text = str(current.get("time") or "")
        for stamp, chance in zip(hourly.get("time") or [], hourly.get("precipitation_probability") or []):
            if now_text and str(stamp) < now_text[:13]:
                continue
            if isinstance(chance, (int, float)) and chance >= _RAIN_ALERT_PERCENT:
                rain_at = {"time": str(stamp), "chance": int(chance)}
                break
        return {
            "available": True,
            "source": "Open-Meteo",
            "temperature": f"{float(temperature):.1f}°C",
            "temp_c": round(float(temperature)),
            "high_c": round(float(high)) if isinstance(high, (int, float)) else None,
            "low_c": round(float(low)) if isinstance(low, (int, float)) else None,
            "condition": _condition(current.get("weathercode")),
            "windspeed": (
                f"{float(windspeed):.1f} km/h" if isinstance(windspeed, (int, float)) else None
            ),
            "rain": rain_at,
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
            if _is_index_page(title):
                continue
            headline, site = _headline(title, url)
            items.append({
                "title": title,
                "headline": headline,
                "site": site,
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

    # -- local data -------------------------------------------------------
    @staticmethod
    def _local_day(now: datetime.datetime, include_tasks: bool, include_schedule: bool) -> dict:
        end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
        events, reminders, tasks = [], [], []
        with get_db_connection() as conn:
            if include_schedule:
                for row in conn.execute("SELECT title, start_time, category FROM calendar_events LIMIT 500"):
                    start = _as_local(row["start_time"])
                    if start is not None and start.date() == now.date():
                        events.append({"title": _clean(row["title"]), "start": start,
                                       "category": row["category"] or "general"})
                try:
                    rows = conn.execute(
                        "SELECT title, target_time FROM reminders_alarms "
                        "WHERE status IN ('pending', 'snoozed') LIMIT 200"
                    ).fetchall()
                except Exception:
                    rows = []
                for row in rows:
                    when = _as_local(row["target_time"])
                    if when is not None and now <= when <= end_of_day:
                        reminders.append({"title": _clean(row["title"]), "at": when})
            if include_tasks:
                for row in conn.execute(
                    "SELECT title, priority, due_date, project_name FROM project_tasks "
                    "WHERE status != 'done' LIMIT 300"
                ):
                    due = _as_local(row["due_date"])
                    item = {"title": _clean(row["title"]), "priority": row["priority"] or "medium",
                            "due": due, "date_only": _date_only(row["due_date"]),
                            "project": row["project_name"] or "General"}
                    if due is not None and due <= end_of_day:
                        overdue = due.date() < now.date() if item["date_only"] else due < now
                        tasks.append({**item, "overdue": overdue})
                    elif due is None and item["priority"] == "high":
                        tasks.append({**item, "overdue": False})
        rank = {"high": 0, "medium": 1, "low": 2}
        tasks.sort(key=lambda t: (not t["overdue"], rank.get(t["priority"], 1), t["due"] or end_of_day))
        events.sort(key=lambda e: e["start"])
        reminders.sort(key=lambda r: r["at"])
        return {"events": events, "reminders": reminders, "tasks": tasks}

    # -- composing ---------------------------------------------------------
    @staticmethod
    def _task_note(task: dict, now: datetime.datetime) -> str:
        due = task["due"]
        if task["overdue"]:
            return "overdue"
        if due is None:
            return "high priority"
        if task["date_only"]:
            return "due today"
        return f"due {_clock(due)}"

    def _compose(self, now, greeting, weather, news, day, flags) -> tuple[str, str]:
        include_weather, include_tasks, include_schedule, include_news = flags
        date_words = f"{now.strftime('%A')}, {now.day} {now.strftime('%B')}"
        events = day["events"]
        upcoming = [e for e in events if e["start"] >= now]
        reminders = day["reminders"]
        tasks = day["tasks"]
        overdue = [t for t in tasks if t["overdue"]]

        # ---------------- what Ultron SAYS ----------------
        say = [f"{greeting} It's {date_words}."]
        if include_weather:
            if weather.get("available"):
                cond = weather.get("condition")
                bits = f"It's {cond} and {weather['temp_c']} degrees" if cond else f"It's {weather['temp_c']} degrees"
                if weather.get("high_c") is not None and weather["high_c"] > weather["temp_c"]:
                    bits += f", heading up to {weather['high_c']}"
                rain = weather.get("rain")
                if rain:
                    at = _as_local(rain["time"])
                    when = f"around {_clock(at)}" if at and at.hour != now.hour else "soon"
                    bits += f". Rain is likely {when}, so keep an umbrella handy"
                say.append(bits + ".")
            else:
                say.append("I couldn't reach the weather service just now.")
        if include_schedule:
            if upcoming:
                first = upcoming[0]
                if len(upcoming) == 1:
                    say.append(f"You have one event left today: {first['title']} at {_clock(first['start'])}.")
                else:
                    say.append(f"You have {len(upcoming)} events left today, starting with "
                               f"{first['title']} at {_clock(first['start'])}.")
            if reminders:
                first = reminders[0]
                more = f", plus {len(reminders) - 1} more" if len(reminders) > 1 else ""
                say.append(f"I'll remind you about {first['title']} at {_clock(first['at'])}{more}.")
        if include_tasks and tasks:
            top = tasks[0]
            if overdue:
                names = _join([t["title"] for t in overdue[:2]])
                say.append(f"{_plural(len(tasks), 'task')} need you today, and {len(overdue)} "
                           f"{'is' if len(overdue) == 1 else 'are'} overdue: {names}.")
            else:
                say.append(f"{_plural(len(tasks), 'task')} for today, the top one is {top['title']}"
                           f"{'' if top['due'] is None else ', ' + self._task_note(top, now)}.")
        # one clear suggestion, like a real assistant
        suggestion = ""
        if include_tasks and overdue:
            suggestion = f"I'd clear {overdue[0]['title']} first."
        elif include_schedule and upcoming and (upcoming[0]["start"] - now).total_seconds() <= 3600:
            suggestion = f"{upcoming[0]['title']} is within the hour, so you may want to get ready."
        elif include_tasks and tasks:
            suggestion = f"I'd start with {tasks[0]['title']}."
        elif (include_tasks or include_schedule) and not upcoming and not reminders:
            suggestion = "Your day is clear, a good window for focused work."
        if suggestion:
            say.append(suggestion)
        if include_news and news.get("available"):
            say.append("I've put today's AI headlines on your screen.")

        # ---------------- what the chat SHOWS ----------------
        show = [f"{greeting}", f"{date_words}", ""]
        if include_weather:
            show.append("WEATHER")
            if weather.get("available"):
                line = f"  {(weather.get('condition') or 'Now').capitalize()}, {weather['temp_c']}°C"
                if weather.get("high_c") is not None and weather.get("low_c") is not None:
                    line += f"  (high {weather['high_c']}°, low {weather['low_c']}°)"
                show.append(line)
                if weather.get("rain"):
                    at = _as_local(weather["rain"]["time"])
                    show.append(f"  Rain likely {('around ' + _clock(at)) if at else 'today'} "
                                f"({weather['rain']['chance']}%). Keep an umbrella.")
            else:
                show.append("  Weather service unreachable right now (no estimate was substituted).")
            show.append("")
        if include_schedule:
            show.append("TODAY")
            if events:
                for event in events[:5]:
                    done = "  (done)" if event["start"] < now else ""
                    show.append(f"  {_clock(event['start']):>8}  {event['title']}{done}")
            else:
                show.append("  No events on your calendar.")
            for reminder in reminders[:3]:
                show.append(f"  {_clock(reminder['at']):>8}  Reminder: {reminder['title']}")
            show.append("")
        if include_tasks:
            head = "TASKS" + (f"  ({len(tasks)} open, {len(overdue)} overdue)" if overdue
                              else f"  ({len(tasks)} open)" if tasks else "")
            show.append(head)
            if tasks:
                for task in tasks[:4]:
                    show.append(f"  - {task['title']}  ({self._task_note(task, now)})")
                if len(tasks) > 4:
                    show.append(f"  + {len(tasks) - 4} more")
            else:
                show.append("  Nothing due today.")
            show.append("")
        if include_news:
            show.append("AI HEADLINES")
            if news.get("available"):
                for item in news["items"][:3]:
                    site = f"  ({item['site']})" if item.get("site") else ""
                    show.append(f"  - {item.get('headline') or item['title']}{site}")
            else:
                show.append("  Headlines unavailable right now (no headlines were substituted).")
            show.append("")
        if suggestion:
            show.append(f"Suggestion: {suggestion}")
        return " ".join(say), "\n".join(show).rstrip()

    async def execute(self, **kwargs) -> Dict[str, Any]:
        include_weather = bool(kwargs.get("include_weather", True))
        include_tasks = bool(kwargs.get("include_tasks", True))
        include_schedule = bool(kwargs.get("include_schedule", True))
        include_news = bool(kwargs.get("include_news", True))

        now = datetime.datetime.now()
        if now.tzinfo is None:
            now = now.astimezone()
        today_date = now.strftime("%A, %B %d, %Y")
        weather_data: Dict[str, Any] = {"available": False, "status": "not_requested"}
        news_data: Dict[str, Any] = {"available": False, "status": "not_requested", "items": []}
        if include_weather and include_news:
            weather_data, news_data = await asyncio.gather(
                self._get_local_weather(),
                self._get_live_news(),
            )
        elif include_weather:
            weather_data = await self._get_local_weather()
        elif include_news:
            news_data = await self._get_live_news()

        day = await asyncio.to_thread(self._local_day, now, include_tasks, include_schedule)
        greeting_period, greeting = _greeting_for_hour(now.hour)
        speech, text = self._compose(
            now, greeting, weather_data, news_data, day,
            (include_weather, include_tasks, include_schedule, include_news),
        )
        return {
            "success": True,
            "data": {
                "date": today_date,
                "greeting_period": greeting_period,
                "briefing_text": text,
                "speech": speech,
                "weather": weather_data,
                "news": news_data,
                "events_count": len(day["events"]),
                "tasks_count": len(day["tasks"]),
                "reminders_count": len(day["reminders"]),
                "overdue_count": sum(1 for t in day["tasks"] if t["overdue"]),
            },
            "error": None,
        }
