"""Natural reminder time parsing in the OWNER'S local time zone.

Understands (English / Hinglish / a little Bengali):
  relative : 10m, +5m, 1h30m, "10 minutes", "in 2 hours", "half an hour",
             "an hour", "3 days", "2 ghante baad", "10 minute baad"
  absolute : "tomorrow 10am", "today at 5:30 pm", "tonight", "tomorrow morning",
             "monday 9am", "next friday", "day after tomorrow", "at 7",
             "kal subah 10 baje", "parso shaam 6 baje", "kal sokal 9 ta"
  ISO      : 2026-09-26T10:00:00 (no zone = LOCAL time, not UTC),
             2026-09-26T10:00:00+05:30, ...Z, 2026-09-26 (= 9 AM local)

Returns an aware datetime; callers store it as UTC ISO. Raises ValueError with
an "Invalid target_time" message when nothing sensible is found, so the tool
never invents a time.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from typing import Optional

_UNIT_SECONDS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60, "minit": 60, "mint": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "ghanta": 3600, "ghante": 3600, "ghonta": 3600,
    "d": 86400, "day": 86400, "days": 86400, "din": 86400,
    "w": 604800, "week": 604800, "weeks": 604800, "hafta": 604800,
}
_UNIT_PATTERN = "|".join(sorted(_UNIT_SECONDS, key=len, reverse=True))
_RELATIVE_PART = re.compile(rf"(\d+(?:\.\d+)?)\s*({_UNIT_PATTERN})(?![a-z])")
_FILLER = re.compile(
    r"\b(in|after|within|from now|later|baad|bad|pore|por|me|mein|ke|ka|ki|the|at|on|by|around|about|o'?clock|ta|te|e)\b"
)

_WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}
_DAY_WORDS = {
    "today": 0, "aaj": 0, "aj": 0, "tonight": 0,
    "tomorrow": 1, "tmrw": 1, "tmr": 1, "kal": 1, "kaal": 1,
    "parso": 2, "porshu": 2, "porsu": 2,
}
# daypart -> (default hour, meridiem hint)
_DAYPARTS = {
    "morning": (9, "am"), "subah": (9, "am"), "sokal": (9, "am"), "sakal": (9, "am"),
    "noon": (12, "pm"), "dopahar": (14, "pm"), "dupur": (14, "pm"), "afternoon": (14, "pm"),
    "evening": (18, "pm"), "shaam": (18, "pm"), "sham": (18, "pm"), "sondhe": (18, "pm"),
    "sondhya": (18, "pm"), "bikel": (17, "pm"),
    "night": (21, "pm"), "tonight": (21, "pm"), "raat": (21, "pm"), "rat": (21, "pm"),
    "midnight": (0, "am"),
}
_CLOCK = re.compile(
    r"\b(\d{1,2})(?:[:.](\d{2}))?\s*"
    r"(?:(a\.?m\.?|p\.?m\.?|baje|bje|o'?clock|ta|hrs)(?![a-z]))?(?!\d)"
)


def local_timezone() -> _dt.tzinfo:
    """ULTRON_TIMEZONE (e.g. Asia/Kolkata) or the computer's own zone."""
    name = os.getenv("ULTRON_TIMEZONE", "").strip()
    if name:
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(name)
        except Exception:  # unknown zone or missing tzdata on Windows
            pass
    return _dt.datetime.now().astimezone().tzinfo or _dt.timezone.utc


def _invalid() -> ValueError:
    return ValueError(
        "Invalid target_time. Use a time like 'in 10 minutes', 'tomorrow 10am', "
        "'monday 9am', a relative value like 10m / 2h / 1d, or ISO local time."
    )


def _parse_iso(text: str, tz: _dt.tzinfo) -> Optional[_dt.datetime]:
    candidate = text.strip().replace("Z", "+00:00").replace("z", "+00:00")
    if not re.match(r"^\d{4}-\d{2}-\d{2}", candidate):
        return None
    try:
        parsed = _dt.datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if len(candidate) == 10:  # date only -> 9 AM that day
        parsed = parsed.replace(hour=9)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)  # naive = owner's local time
    return parsed


def _parse_relative(text: str) -> Optional[_dt.timedelta]:
    clean = text.replace("half an hour", "30 minutes").replace("half hour", "30 minutes")
    clean = re.sub(r"\b(an|a|one|ek)\s+(hour|minute|day|week|ghanta)\b", r"1 \2", clean)
    clean = re.sub(r"\b(\d+)\s*(?:and a half|\.5)\s*(hours?|ghante)\b",
                   lambda m: f"{int(m.group(1)) * 60 + 30} minutes", clean)
    parts = _RELATIVE_PART.findall(clean)
    if not parts:
        return None
    leftover = _RELATIVE_PART.sub(" ", clean)
    leftover = _FILLER.sub(" ", leftover)
    leftover = re.sub(r"[+\s,]+|\band\b", " ", leftover).strip()
    if leftover:  # e.g. "tomorrow 10m" or "3 days after monday": not purely relative
        return None
    total = sum(float(value) * _UNIT_SECONDS[unit] for value, unit in parts)
    if total <= 0:
        raise ValueError("Relative target_time must be greater than zero.")
    return _dt.timedelta(seconds=total)


def _parse_natural(text: str, now: _dt.datetime) -> Optional[_dt.datetime]:
    words = set(re.findall(r"[a-z']+", text))
    day_offset: Optional[int] = None
    if "day after tomorrow" in text:
        day_offset = 2
    else:
        for word, offset in _DAY_WORDS.items():
            if word in words:
                day_offset = offset
                break
    weekday = next((_WEEKDAYS[w] for w in words if w in _WEEKDAYS), None)
    daypart = next((_DAYPARTS[w] for w in words if w in _DAYPARTS), None)

    hour = minute = None
    meridiem = None
    for match in _CLOCK.finditer(text):
        number, mins, marker = match.group(1), match.group(2), (match.group(3) or "")
        before = text[: match.start()]
        explicit = bool(mins or marker) or re.search(r"\b(at|by|around)\s*$", before)
        if not explicit and not (daypart or day_offset is not None or weekday is not None):
            continue
        value = int(number)
        if value > 23 or (mins and int(mins) > 59):
            continue
        hour, minute = value, int(mins or 0)
        marker = marker.replace(".", "")
        if marker in ("am", "pm"):
            meridiem = marker
        break

    if hour is None and daypart is None and day_offset is None and weekday is None:
        return None

    if hour is None:
        hour, minute = (daypart[0], 0) if daypart else (9, 0)
    else:
        hint = meridiem or (daypart[1] if daypart else None)
        if hint == "pm" and hour < 12:
            hour += 12
        elif hint == "am" and hour == 12:
            hour = 0

    base = now
    if weekday is not None:
        ahead = (weekday - now.weekday()) % 7
        if ahead == 0 or "next" in words:
            ahead = ahead or 7
        base = now + _dt.timedelta(days=ahead)
    elif day_offset is not None:
        base = now + _dt.timedelta(days=day_offset)

    target = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now and day_offset is None and weekday is None:
        if meridiem is None and daypart is None and hour < 12:
            evening = target + _dt.timedelta(hours=12)
            if evening > now:  # "at 5" said at 2 PM means 5 PM
                return evening
        target += _dt.timedelta(days=1)
    return target


def parse_when(text: str, now: Optional[_dt.datetime] = None) -> _dt.datetime:
    """Parse a reminder time. Returns an aware datetime in the local zone."""
    tz = local_timezone()
    now = (now or _dt.datetime.now(tz)).astimezone(tz)
    raw = str(text or "").strip()
    if not raw:
        raise _invalid()
    iso = _parse_iso(raw, tz)
    if iso is not None:
        return iso.astimezone(tz)
    lowered = raw.lower().strip()
    if lowered.startswith("-"):
        raise ValueError("target_time must be a future ISO time or positive relative duration.")
    delta = _parse_relative(lowered.lstrip("+"))
    if delta is not None:
        return now + delta
    natural = _parse_natural(lowered, now)
    if natural is not None:
        return natural
    raise _invalid()


def speakable_time(when: _dt.datetime, now: Optional[_dt.datetime] = None) -> str:
    """'10:00 AM today' / '9:30 PM tomorrow' / '6:00 PM on Monday, 29 September'."""
    tz = local_timezone()
    now = (now or _dt.datetime.now(tz)).astimezone(tz)
    local = when.astimezone(tz)
    clock = local.strftime("%I:%M %p").lstrip("0")
    days = (local.date() - now.date()).days
    if days == 0:
        return f"{clock} today"
    if days == 1:
        return f"{clock} tomorrow"
    if days == -1:
        return f"{clock} yesterday"
    return f"{clock} on {local.strftime('%A')}, {local.day} {local.strftime('%B')}"
