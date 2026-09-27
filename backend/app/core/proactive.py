"""JARVIS moments at 0 tokens: Ultron speaks first, from local data only.

Checked once a minute by the heads-up loop (no AI call, tiny CPU cost):

* PC strain   "Memory is at 93%, Sir, mostly Chrome. Shall I sleep the background tabs?"
              RAM (5 minutes high), CPU (5 minutes at full load), low disk, low battery.
* Evening before an important event (exam, deadline, interview, appointment):
              "Tomorrow: Physics exam at 10 am, Sir. Shall we make a plan for tonight?"
* Late night before it: "It's past midnight, Sir, and Physics exam is at 10 am. Sleep will
              do more for you now than another hour awake."
* After it:   "How did the Physics exam go, Sir?"

Rules: each line is spoken once (per event / per episode); event lines only
while he is actually here (chatted in the last 20 minutes, or in the welcome
back briefing); PC lines stay quiet at night unless he is here. Offers are
questions; nothing is done without his yes. The last line said aloud is
shown to the AI on his next message, so "yes" or "it went well" is understood.
Plain words only (the voice reads them).
"""

from __future__ import annotations

import datetime as _dt
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

IMPORTANT = frozenset({"exam", "deadline", "interview", "appointment"})
ACTIVE_MINUTES = 20
RAM_HIGH, RAM_REARM, RAM_MINUTES = 90.0, 80.0, 5
CPU_HIGH, CPU_REARM, CPU_MINUTES = 95.0, 70.0, 5
DISK_LOW_GB = 5.0
BATTERY_LOW = 15
LINE_TTL = {"followup": 6 * 60, "evening": 90}  # minutes the AI still sees the line
DEFAULT_TTL = 45

_lock = threading.Lock()


@dataclass
class PcReadings:
    ram_percent: Optional[float] = None
    cpu_percent: Optional[float] = None
    disk_free_gb: Optional[float] = None
    battery_percent: Optional[float] = None
    battery_plugged: Optional[bool] = None


# --------------------------------------------------------------------------- state
def _state_path() -> Path:
    from backend.app.runtime_paths import runtime_data_path

    return runtime_data_path("proactive.json")


def _load() -> dict:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    try:
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def clear() -> None:
    with _lock:
        try:
            _state_path().unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- helpers
def _now() -> _dt.datetime:
    return _dt.datetime.now().astimezone()


def _spoken_clock(moment: _dt.datetime) -> str:
    hour = moment.hour % 12 or 12
    suffix = "am" if moment.hour < 12 else "pm"
    return f"{hour}:{moment.minute:02d} {suffix}" if moment.minute else f"{hour} {suffix}"


def _clean(text) -> str:
    return " ".join(str(text or "").replace("_", " ").split())[:80]


def _active(now: _dt.datetime) -> bool:
    try:
        from backend.app.core import arrival

        seen = arrival.last_seen()
    except Exception:
        return False
    return seen is not None and 0 <= (now - seen).total_seconds() <= ACTIVE_MINUTES * 60


def _item(kind: str, title: str, speech: str, now: _dt.datetime) -> dict:
    # "minutes" only makes the screen's message id unique (it is not a countdown here)
    return {"type": "heads_up", "kind": kind, "title": title, "speech": speech,
            "minutes": int(now.timestamp() // 60)}


def _remember_line(state: dict, kind: str, speech: str, now: _dt.datetime) -> None:
    state["last_line"] = {"kind": kind, "text": speech, "at": now.isoformat()}


def _said(state: dict, key: str) -> bool:
    return key in (state.get("said") or {})


def _mark(state: dict, key: str, now: _dt.datetime) -> None:
    said = state.setdefault("said", {})
    said[key] = now.isoformat()
    if len(said) > 300:  # bounded: keep the newest
        for old in sorted(said, key=said.get)[: len(said) - 300]:
            said.pop(old, None)


# --------------------------------------------------------------------------- PC strain
def read_pc() -> PcReadings:
    """One cheap sample (no process scan here)."""
    readings = PcReadings()
    try:
        import psutil

        readings.ram_percent = float(psutil.virtual_memory().percent)
        readings.cpu_percent = float(psutil.cpu_percent(interval=None))  # since last call, non-blocking
        try:
            battery = psutil.sensors_battery()
        except Exception:
            battery = None
        if battery is not None:
            readings.battery_percent = float(battery.percent)
            readings.battery_plugged = bool(battery.power_plugged)
    except Exception:
        pass
    try:
        import shutil

        readings.disk_free_gb = shutil.disk_usage(str(Path.home())).free / 1024 ** 3
    except OSError:
        pass
    return readings


def top_memory_app() -> str:
    """Program using the most memory (all its processes together). Only called on an alert."""
    try:
        import psutil

        totals: dict[str, int] = {}
        for proc in psutil.process_iter(["name", "memory_info"]):
            info = proc.info
            name = str(info.get("name") or "").lower().removesuffix(".exe")
            memory = info.get("memory_info")
            if name and memory is not None:
                for family in ("chrome", "chromium", "firefox", "code", "electron"):
                    if name.startswith(family):
                        name = family
                        break
                totals[name] = totals.get(name, 0) + int(memory.rss)
        if not totals:
            return ""
        name = max(totals, key=totals.get)
        return {"code": "VS Code", "chrome": "Chrome", "chromium": "Chromium", "firefox": "Firefox"}.get(
            name, name.replace("-", " ").replace("_", " ").capitalize())  # spoken: no symbols
    except Exception:
        return ""


def pc_checks(now: _dt.datetime, readings: PcReadings, state: dict, owner: str, *,
              helper_connected: bool, active: bool,
              top_app: Optional[Callable[[], str]] = None) -> list[dict]:
    top_app = top_app or top_memory_app  # looked up at call time
    out: list[dict] = []
    quiet = not (8 <= now.hour < 23) and not active
    pc = state.setdefault("pc", {})

    # RAM: high for 5 minutes in a row, then once until it drops below 80%
    ram = readings.ram_percent
    if ram is not None:
        if ram >= RAM_HIGH:
            pc["ram_count"] = int(pc.get("ram_count", 0)) + 1
        elif ram < RAM_REARM:
            pc["ram_count"], pc["ram_said"] = 0, False
        if pc.get("ram_count", 0) >= RAM_MINUTES and not pc.get("ram_said") and not quiet:
            app = top_app()
            speech = f"Memory is at {ram:.0f}%, {owner}" + (f", mostly {app}." if app else ".")
            if app in {"Chrome", "Chromium"} and helper_connected:
                speech += " Shall I sleep the background tabs?"
            elif app:
                speech += f" Closing {app} would free the most."
            out.append(_item("pc", "Memory high", speech, now))
            pc["ram_said"] = True

    # CPU: full load for 5 minutes in a row
    cpu = readings.cpu_percent
    if cpu is not None:
        if cpu >= CPU_HIGH:
            pc["cpu_count"] = int(pc.get("cpu_count", 0)) + 1
        elif cpu < CPU_REARM:
            pc["cpu_count"], pc["cpu_said"] = 0, False
        if pc.get("cpu_count", 0) >= CPU_MINUTES and not pc.get("cpu_said") and not quiet:
            out.append(_item("pc", "Processor busy",
                             f"The processor has been at full load for five minutes, {owner}. "
                             "Shall I check what is using it?", now))
            pc["cpu_said"] = True

    # Disk: under 5 GB free, at most once a day
    disk = readings.disk_free_gb
    if disk is not None and disk < DISK_LOW_GB and not quiet:
        key = f"disk|{now.date().isoformat()}"
        if not _said(state, key):
            out.append(_item("pc", "Disk space low",
                             f"Disk space is low, {owner}: {disk:.1f} gigabytes left. "
                             "Shall I find the biggest files?", now))
            _mark(state, key, now)

    # Battery: on battery and 15% or less, once per discharge
    if readings.battery_percent is not None:
        if readings.battery_plugged or readings.battery_percent > BATTERY_LOW + 10:
            pc["battery_said"] = False
        elif readings.battery_percent <= BATTERY_LOW and not pc.get("battery_said") and not quiet:
            out.append(_item("pc", "Battery low",
                             f"Battery is at {readings.battery_percent:.0f}%, {owner}. Time to plug in.", now))
            pc["battery_said"] = True

    for item in out:
        _remember_line(state, "pc", item["speech"], now)
    return out


# --------------------------------------------------------------------------- important events
def _important(events: list[dict]) -> list[dict]:
    return [e for e in events if str(e.get("category") or "") in IMPORTANT]


def followup_line(event: dict, owner: str) -> str:
    return f"How did the {_clean(event['title'])} go, {owner}?"


def _due_followup(events: list[dict], now: _dt.datetime, state: dict) -> Optional[dict]:
    for event in sorted(_important(events), key=lambda e: e["_end"], reverse=True):
        since_end = (now - event["_end"]).total_seconds() / 3600
        if 1 <= since_end <= 36 and not _said(state, f"followup|{event['id']}"):
            return event
    return None


def event_checks(now: _dt.datetime, events: list[dict], state: dict, owner: str, *, active: bool) -> list[dict]:
    if not active:
        return []  # event lines only while he is here; the welcome-back briefing covers the rest
    out: list[dict] = []
    important = _important(events)

    # After it: how did it go (daytime)
    if 9 <= now.hour < 22:
        event = _due_followup(events, now, state)
        if event:
            speech = followup_line(event, owner)
            out.append(_item("care", f"How it went: {_clean(event['title'])}", speech, now))
            _mark(state, f"followup|{event['id']}", now)
            _remember_line(state, "followup", speech, now)

    tomorrow = now.date() + _dt.timedelta(days=1)
    # Evening before: say what is coming and offer a plan
    if 19 <= now.hour < 23:
        for event in sorted(important, key=lambda e: e["_start"]):
            key = f"evening|{event['id']}"
            if event["_start"].date() == tomorrow and not _said(state, key):
                speech = (f"Tomorrow: {_clean(event['title'])} at {_spoken_clock(event['_start'])}, {owner}. "
                          "Shall we make a plan for tonight?")
                out.append(_item("care", f"Tomorrow: {_clean(event['title'])}", speech, now))
                _mark(state, key, now)
                _remember_line(state, "evening", speech, now)
                break

    # Late night before it (midnight to 4 am, the event is later today)
    if 0 <= now.hour < 4:
        for event in sorted(important, key=lambda e: e["_start"]):
            key = f"night|{event['id']}"
            hours_left = (event["_start"] - now).total_seconds() / 3600
            if 0 < hours_left <= 14 and not _said(state, key):
                speech = (f"It's past midnight, {owner}, and {_clean(event['title'])} is at "
                          f"{_spoken_clock(event['_start'])}. Sleep will do more for you now than "
                          "another hour awake.")
                out.append(_item("care", f"Sleep: {_clean(event['title'])}", speech, now))
                _mark(state, key, now)
                _remember_line(state, "night", speech, now)
                break
    return out


# --------------------------------------------------------------------------- entry points
def run_checks(owner: str = "Sir", *, helper_connected: bool = False,
               now: Optional[_dt.datetime] = None, readings: Optional[PcReadings] = None,
               events: Optional[list[dict]] = None) -> list[dict]:
    """Everything to speak now (called once a minute). Never raises."""
    try:
        now = now or _now()
        readings = readings if readings is not None else read_pc()
        if events is None:
            from backend.app.core import plan_context

            events = plan_context._events()
        active = _active(now)
        with _lock:
            state = _load()
            out = pc_checks(now, readings, state, owner, helper_connected=helper_connected, active=active)
            out += event_checks(now, events, state, owner, active=active)
            _save(state)
        return out
    except Exception as exc:
        print(f"[PROACTIVE] check skipped: {exc}")
        return []


def briefing_followup(now: _dt.datetime, events: list[dict], owner: str = "Sir") -> Optional[str]:
    """For the welcome-back briefing: ask how an important event went (once)."""
    try:
        with _lock:
            state = _load()
            event = _due_followup(events, now, state)
            if not event:
                return None
            speech = followup_line(event, owner)
            _mark(state, f"followup|{event['id']}", now)
            _remember_line(state, "followup", speech, now)
            _save(state)
            return speech
    except Exception:
        return None


def recent_line(now: Optional[_dt.datetime] = None) -> str:
    """The line Ultron said aloud lately, so his next message is understood ('' if none)."""
    try:
        now = now or _now()
        with _lock:
            last = _load().get("last_line") or {}
        said_at = _dt.datetime.fromisoformat(str(last.get("at")))
        minutes = (now - said_at).total_seconds() / 60
        if not 0 <= minutes <= LINE_TTL.get(str(last.get("kind")), DEFAULT_TTL):
            return ""
        text = " ".join(str(last.get("text") or "").split())[:200]
        hint = ("If he answers it, reply warmly and save how it went with manage_memory remember."
                if last.get("kind") == "followup" else "If his message answers it, act on that.")
        return f'[You said aloud {int(minutes)} min ago] "{text}" {hint}'
    except Exception:
        return ""
