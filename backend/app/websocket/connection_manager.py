"""
Ultron Multichannel WebSocket Connection Manager
Coordinates thread-safe connection pools, client subscriptions, and broadcast operations.
Natively prevents socket leaks and manages client disconnection cycles.
"""

import os
from typing import Any, Dict
from urllib.parse import urlsplit

from fastapi import WebSocket

# The Ultron Chrome extension (fixed id from the public "key" in its manifest).
EXTENSION_ID = "pbjmcefgnklmcigoddnnimgjohfeelcd"
_LOOPBACK = {"localhost", "127.0.0.1", "::1", "[::1]"}
_TRUSTED_PROXY_SUFFIXES = (".app.github.dev", ".github.dev")


def origin_allowed(origin: str | None, host: str | None, channel: str) -> bool:
    """Stop other websites from driving Ultron through 127.0.0.1 (cross-site WebSocket).

    Browsers always send Origin on a WebSocket; programs (tests, scripts) do not.
    Allowed: the Ultron UI on this PC, same-origin through a trusted proxy
    (Codespaces or ULTRON_ALLOWED_HOSTS), and the Ultron extension on /ws/browser.
    """
    if not origin:
        return True
    parts = urlsplit(origin)
    if parts.scheme == "chrome-extension":
        extra = {x.strip() for x in os.getenv("ULTRON_EXTENSION_IDS", "").split(",") if x.strip()}
        return channel == "browser" and parts.netloc in ({EXTENSION_ID} | extra)
    if channel == "browser":
        return False  # only the extension talks on the browser channel
    if parts.scheme not in {"http", "https"}:
        return False
    if (parts.hostname or "") in _LOOPBACK:
        return True
    host_name = (host or "").rsplit(":", 1)[0].lower() if not (host or "").startswith("[") else (host or "")
    extra_hosts = {x.strip().lower() for x in os.getenv("ULTRON_ALLOWED_HOSTS", "").split(",") if x.strip()}
    trusted = host_name in extra_hosts or host_name.endswith(_TRUSTED_PROXY_SUFFIXES)
    return trusted and parts.netloc.lower() == (host or "").lower()


class WebSocketManager:
    def __init__(self) -> None:
        # Active connection registry mapping: {channel_name: {client_id: WebSocket}}
        self._active_connections: Dict[str, Dict[str, WebSocket]] = {
            "chat": {},
            "events": {},
            "logs": {},
            "dashboard": {},
            "browser": {},
        }

    async def connect(self, channel: str, client_id: str, websocket: WebSocket) -> bool:
        """Accepts the WebSocket connection and registers it; False = refused (foreign site)."""
        headers = websocket.headers
        if not origin_allowed(headers.get("origin"), headers.get("host"), channel):
            print(f"[WS_MANAGER] Refused {channel} connection from origin {headers.get('origin')!r}.")
            await websocket.close(code=1008)
            return False
        await websocket.accept()
        if channel not in self._active_connections:
            self._active_connections[channel] = {}
        self._active_connections[channel][client_id] = websocket
        print(f"[WS_MANAGER] Client '{client_id}' successfully connected to channel: '{channel}'.")
        return True

    def disconnect(self, channel: str, client_id: str) -> None:
        """Removes the disconnected client from the specified channel pool, preventing resource leaks."""
        if channel in self._active_connections:
            self._active_connections[channel].pop(client_id, None)
            print(f"[WS_MANAGER] Client '{client_id}' disconnected from channel: '{channel}'.")

    async def send_personal_message(self, channel: str, client_id: str, message: Dict[str, Any]) -> None:
        """Sends a structured JSON packet to a specific, isolated client."""
        ws = self._active_connections.get(channel, {}).get(client_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception as e:
                print(f"[WS_MANAGER] Error sending to client '{client_id}': {e}. Disconnecting.")
                self.disconnect(channel, client_id)

    async def broadcast(self, channel: str, message: Dict[str, Any]) -> int:
        """Broadcasts to all subscribers of a channel; returns how many received it."""
        delivered = 0
        if channel in self._active_connections:
            # Create snapshot of current pool to avoid mutation errors during iteration
            clients = list(self._active_connections[channel].items())
            for client_id, ws in clients:
                try:
                    await ws.send_json(message)
                    delivered += 1
                except Exception:
                    # Handle dropped sockets on-the-fly to protect server health
                    self.disconnect(channel, client_id)
        return delivered
                    
    def get_active_client_count(self, channel: str) -> int:
        """Returns the number of active connected clients on a given channel."""
        return len(self._active_connections.get(channel, {}))
