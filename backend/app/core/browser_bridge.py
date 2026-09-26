"""Bridge to the Ultron Chrome extension (V2 Step C3).

The extension (extension/chrome) keeps one WebSocket open to /ws/browser and
does the real tab work with the chrome.tabs API, so Ultron controls the actual
tabs on Wayland and X11 alike, never presses keys, and never closes his own tab.

`call()` sends {"id", "action", "args"} and waits (max a few seconds) for the
matching {"type": "reply", "id", "ok", "data"|"error"}. No extension connected
-> an honest message with the one-time setup steps. Never raises.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from typing import Any, Optional

_socket: Any = None
_pending: dict[int, asyncio.Future] = {}
_ids = itertools.count(1)
_info: dict[str, Any] = {}


def extension_folder() -> str:
    try:
        from backend.app.install_paths import ASSET_ROOT

        return str(ASSET_ROOT / "extension" / "chrome")
    except Exception:
        return "extension/chrome (inside the Ultron folder)"


def setup_steps() -> str:
    return ("The Ultron browser helper is not connected, so I can't touch your tabs yet. "
            "One-time setup, 1 minute: open chrome://extensions, switch on Developer mode, "
            f"click Load unpacked and pick the folder {extension_folder()}. Then ask me again.")


def connected() -> bool:
    return _socket is not None


def status() -> dict[str, Any]:
    return {"connected": connected(), **({"version": _info.get("version")} if _info else {})}


def ultron_origins() -> list[str]:
    """Where Ultron's own UI lives, so the extension never closes it."""
    try:
        import yaml

        from backend.app.install_paths import CONFIG_PATH

        server = (yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}).get("server", {}) or {}
        ports = {int(server.get("frontend_port", 5173)), int(server.get("backend_port", 8000))}
    except Exception:
        ports = {5173, 8000}
    return sorted(f"http://{host}:{port}" for host in ("127.0.0.1", "localhost") for port in ports)


async def attach(websocket: Any) -> None:
    """A (re)connected extension replaces any older one."""
    global _socket
    old = _socket
    _socket = websocket
    _info.clear()
    if old is not None and old is not websocket:
        try:
            await old.close(code=1000)
        except Exception:
            pass
    await websocket.send_text(json.dumps({"type": "config", "ultron_origins": ultron_origins()}))


def detach(websocket: Any) -> None:
    global _socket
    if _socket is websocket:
        _socket = None
        for future in list(_pending.values()):
            if not future.done():
                future.set_result({"ok": False, "error": "The browser helper disconnected."})
        _pending.clear()


def handle(text: str) -> None:
    """One message from the extension: hello, ping or a reply."""
    try:
        message = json.loads(text)
    except (TypeError, ValueError):
        return
    if not isinstance(message, dict):
        return
    kind = message.get("type")
    if kind == "hello":
        _info.update({"version": str(message.get("version") or "")[:20]})
    elif kind == "reply":
        future = _pending.pop(message.get("id"), None) if isinstance(message.get("id"), int) else None
        if future is not None and not future.done():
            future.set_result(message)


async def call(action: str, args: Optional[dict] = None, timeout: float = 6.0) -> dict[str, Any]:
    """Ask the extension to do one tab action -> tool-style dict."""
    websocket = _socket
    if websocket is None:
        return {"success": False, "error": setup_steps(), "data": {"extension": False}}
    request_id = next(_ids)
    future: asyncio.Future = asyncio.get_running_loop().create_future()
    _pending[request_id] = future
    try:
        await websocket.send_text(json.dumps({"id": request_id, "action": action, "args": args or {}}))
        reply = await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        return {"success": False, "error": "The browser helper did not answer in time.", "data": {}}
    except Exception as exc:
        return {"success": False, "error": f"Could not reach the browser helper: {exc}", "data": {}}
    finally:
        _pending.pop(request_id, None)
    if reply.get("ok"):
        data = reply.get("data")
        return {"success": True, "data": data if isinstance(data, dict) else {"result": data}, "error": None}
    return {"success": False, "error": str(reply.get("error") or "The browser said no.")[:300], "data": {}}
