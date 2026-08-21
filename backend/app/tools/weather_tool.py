"""Verified Open-Meteo weather values without estimated/fabricated fallbacks."""

from __future__ import annotations

import datetime
from typing import Any, Dict

import httpx
from pydantic import BaseModel, Field

from backend.app.tools.tool_base import BaseTool


class WeatherArgs(BaseModel):
    latitude: float = Field(22.57, ge=-90, le=90, description="Target latitude coordinate.")
    longitude: float = Field(88.36, ge=-180, le=180, description="Target longitude coordinate.")


def _condition(code: Any) -> str:
    try:
        value = int(code)
    except (TypeError, ValueError):
        return "Unavailable"
    if value == 0:
        return "Clear"
    if value in {1, 2, 3}:
        return "Cloudy"
    if value in {45, 48}:
        return "Fog"
    if 51 <= value <= 67 or 80 <= value <= 82:
        return "Rain"
    if 71 <= value <= 77 or 85 <= value <= 86:
        return "Snow"
    if 95 <= value <= 99:
        return "Thunderstorm"
    return f"Weather code {value}"


class WeatherTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="weather_tool",
            name="Weather Watcher",
            description="Queries reported current, hourly, and daily Open-Meteo values for coordinates.",
            category="productivity",
            tags=["weather", "forecast", "temperature", "rain", "sunny", "climate"],
            permission_level=0,
            args_model=WeatherArgs,
            usage_examples=["weather_tool(latitude=22.57, longitude=88.36)"],
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        lat = float(kwargs.get("latitude", 22.57))
        lon = float(kwargs.get("longitude", 88.36))
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "current_weather": "true",
            "hourly": "temperature_2m,weathercode",
            "daily": "temperature_2m_max,weathercode",
            "forecast_days": 7,
            "timezone": "auto",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
        except Exception as exc:
            return {
                "success": False,
                "data": {"status": "unavailable", "location": f"Lat: {lat}, Lon: {lon}"},
                "error": f"Live weather unavailable: {exc}",
            }
        if response.status_code != 200:
            return {
                "success": False,
                "data": {"status": "unavailable", "location": f"Lat: {lat}, Lon: {lon}"},
                "error": f"Weather API returned HTTP {response.status_code}",
            }
        try:
            data = response.json()
            current = data.get("current_weather") or {}
            temperature = current.get("temperature")
            weather_code = current.get("weathercode")
            if not isinstance(temperature, (int, float)):
                raise ValueError("current temperature missing from provider response")

            hourly_data = data.get("hourly") or {}
            hourly_times = hourly_data.get("time") or []
            hourly_temps = hourly_data.get("temperature_2m") or []
            hourly_codes = hourly_data.get("weathercode") or []
            current_time = str(current.get("time") or "")
            hourly = []
            for index, timestamp in enumerate(hourly_times):
                if current_time and str(timestamp) < current_time:
                    continue
                if index >= len(hourly_temps) or not isinstance(hourly_temps[index], (int, float)):
                    continue
                hourly.append({
                    "time": str(timestamp),
                    "temp": f"{float(hourly_temps[index]):.1f}°C",
                    "condition": _condition(hourly_codes[index] if index < len(hourly_codes) else None),
                })
                if len(hourly) >= 3:
                    break

            daily = data.get("daily") or {}
            dates = daily.get("time") or []
            max_temps = daily.get("temperature_2m_max") or []
            daily_codes = daily.get("weathercode") or []
            weekly = []
            for index, date_text in enumerate(dates[:7]):
                if index >= len(max_temps) or not isinstance(max_temps[index], (int, float)):
                    continue
                try:
                    day = datetime.date.fromisoformat(str(date_text)).strftime("%a").upper()
                except ValueError:
                    day = str(date_text)
                weekly.append({
                    "day": day,
                    "date": str(date_text),
                    "temp": f"{float(max_temps[index]):.1f}°C",
                    "cond": _condition(daily_codes[index] if index < len(daily_codes) else None),
                })
        except (TypeError, ValueError, KeyError) as exc:
            return {
                "success": False,
                "data": {"status": "unavailable", "location": f"Lat: {lat}, Lon: {lon}"},
                "error": f"Weather provider returned incomplete data: {exc}",
            }

        windspeed = current.get("windspeed")
        return {
            "success": True,
            "data": {
                "status": "live",
                "source": "Open-Meteo",
                "observed_at": current.get("time"),
                "location": f"Lat: {lat}, Lon: {lon}",
                "temp": f"{float(temperature):.1f}°C",
                "condition": _condition(weather_code),
                "windspeed": (
                    f"{float(windspeed):.1f} km/h"
                    if isinstance(windspeed, (int, float))
                    else "Unavailable"
                ),
                "hourly": hourly,
                "weekly": weekly,
            },
            "error": None,
        }
