"""Truthful local system telemetry with explicit unavailable sensor states."""

from __future__ import annotations

import os
import platform
import time
from pathlib import Path
from typing import Any, Dict

import psutil
from pydantic import BaseModel

from backend.app.tools.tool_base import BaseTool


class SystemMetricsArgs(BaseModel):
    pass


def _disk_root() -> str:
    anchor = Path.home().anchor
    return anchor or os.path.abspath(os.sep)


def _temperature_reading() -> tuple[float | None, str | None]:
    sensor_fn = getattr(psutil, "sensors_temperatures", None)
    if sensor_fn is None:
        return None, None
    try:
        groups = sensor_fn() or {}
    except (AttributeError, OSError, RuntimeError):
        return None, None
    readings = []
    for group_name, entries in groups.items():
        for entry in entries or []:
            current = getattr(entry, "current", None)
            if isinstance(current, (int, float)) and -50.0 <= float(current) <= 200.0:
                label = getattr(entry, "label", "") or group_name
                readings.append((float(current), str(label)))
    if not readings:
        return None, None
    # Report the hottest available sensor, clearly labelled—not a fabricated CPU value.
    return max(readings, key=lambda item: item[0])


def collect_system_metrics() -> Dict[str, Any]:
    """Collect real local values; optional hardware is represented as unavailable."""
    process = psutil.Process(os.getpid())
    process_ram_mb = process.memory_info().rss / (1024**2)
    cpu_percent = float(psutil.cpu_percent(interval=None))
    ram_percent = float(psutil.virtual_memory().percent)
    disk = psutil.disk_usage(_disk_root())
    disk_used_gb = disk.used / (1024**3)
    disk_total_gb = disk.total / (1024**3)
    disk_percent = float(disk.percent)

    unavailable = []
    try:
        battery_sensor = psutil.sensors_battery()
    except (AttributeError, OSError, RuntimeError):
        battery_sensor = None
    battery_percent = getattr(battery_sensor, "percent", None) if battery_sensor is not None else None
    if not isinstance(battery_percent, (int, float)):
        battery = {
            "available": False,
            "percent": None,
            "power_plugged": None,
            "status": "unavailable",
        }
        battery_display = "Unavailable (no battery sensor reported)"
        unavailable.append("battery")
    else:
        plugged = bool(getattr(battery_sensor, "power_plugged", False))
        battery = {
            "available": True,
            "percent": float(battery_percent),
            "power_plugged": plugged,
            "status": "charging" if plugged else "discharging",
        }
        battery_display = (
            f"{battery['percent']:.1f}% "
            f"({'Charging' if battery['power_plugged'] else 'Discharging'})"
        )

    temperature_c, temperature_sensor = _temperature_reading()
    if temperature_c is None:
        temperature_display = "Unavailable (no temperature sensor reported)"
        unavailable.append("temperature")
    else:
        temperature_display = f"{temperature_c:.1f}°C ({temperature_sensor})"

    try:
        io = psutil.net_io_counters()
        stats = psutil.net_if_stats() or {}
        interfaces_up = sum(1 for item in stats.values() if getattr(item, "isup", False))
        network = {
            "available": io is not None,
            "interfaces_up": interfaces_up,
            "bytes_sent": int(io.bytes_sent) if io is not None else None,
            "bytes_received": int(io.bytes_recv) if io is not None else None,
            "scope": "cumulative_since_boot",
        }
    except (AttributeError, OSError, RuntimeError):
        network = {
            "available": False,
            "interfaces_up": None,
            "bytes_sent": None,
            "bytes_received": None,
            "scope": "unavailable",
        }
    if network["available"]:
        network_display = (
            f"Interfaces up: {network['interfaces_up']} · "
            f"TX {network['bytes_sent'] / (1024**2):.1f} MB · "
            f"RX {network['bytes_received'] / (1024**2):.1f} MB (since boot)"
        )
    else:
        network_display = "Unavailable (network counters not reported)"
        unavailable.append("network")

    try:
        uptime_seconds = max(0.0, time.time() - float(psutil.boot_time()))
    except (AttributeError, OSError, RuntimeError, ValueError):
        uptime_seconds = None
        unavailable.append("uptime")

    return {
        "cpu_percent": cpu_percent,
        "ram_percent": ram_percent,
        "process_ram_mb": round(process_ram_mb, 1),
        "disk_used_gb": round(disk_used_gb, 1),
        "disk_total_gb": round(disk_total_gb, 1),
        "disk_percent": disk_percent,
        "battery": battery,
        "temperature_c": temperature_c,
        "temperature_sensor": temperature_sensor,
        "network": network,
        "uptime_seconds": round(uptime_seconds, 1) if uptime_seconds is not None else None,
        "platform": platform.platform(),
        "unavailable_fields": unavailable,
        # Backward-compatible display fields consumed by existing widgets.
        "cpu": f"{cpu_percent:.1f}%",
        "ram": f"{ram_percent:.1f}%",
        "proc_ram_mb": round(process_ram_mb, 1),
        "disk": f"{disk_used_gb:.1f} GB / {disk_total_gb:.1f} GB used ({disk_percent:.1f}%)",
        "battery_display": battery_display,
        "temperature_display": temperature_display,
        "network_display": network_display,
    }


class SystemMetricsTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="system_metrics",
            name="Hardware System Metrics",
            description="Inspects reported local CPU, RAM, disk, battery, temperature, network counters and uptime.",
            category="system",
            tags=["system", "cpu", "ram", "hardware", "metrics", "storage", "battery"],
            permission_level=0,
            args_model=SystemMetricsArgs,
            usage_examples=["system_metrics()"],
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        try:
            return {"success": True, "data": collect_system_metrics(), "error": None}
        except Exception as exc:
            return {
                "success": False,
                "error": f"Failed to retrieve core system metrics: {exc}",
                "data": {"status": "unavailable"},
            }
