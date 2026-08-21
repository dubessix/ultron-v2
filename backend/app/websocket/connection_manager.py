"""
Ultron Multichannel WebSocket Connection Manager
Coordinates thread-safe connection pools, client subscriptions, and broadcast operations.
Natively prevents socket leaks and manages client disconnection cycles.
"""

from fastapi import WebSocket
from typing import Dict, Any

class WebSocketManager:
    def __init__(self) -> None:
        # Active connection registry mapping: {channel_name: {client_id: WebSocket}}
        self._active_connections: Dict[str, Dict[str, WebSocket]] = {
            "chat": {},
            "events": {},
            "logs": {},
            "dashboard": {}
        }

    async def connect(self, channel: str, client_id: str, websocket: WebSocket) -> None:
        """Accepts the WebSocket connection and registers it in the specified channel pool."""
        await websocket.accept()
        if channel not in self._active_connections:
            self._active_connections[channel] = {}
        self._active_connections[channel][client_id] = websocket
        print(f"[WS_MANAGER] Client '{client_id}' successfully connected to channel: '{channel}'.")

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

    async def broadcast(self, channel: str, message: Dict[str, Any]) -> None:
        """Broadcasts a structured JSON packet to all active subscribers on a specific channel."""
        if channel in self._active_connections:
            # Create snapshot of current pool to avoid mutation errors during iteration
            clients = list(self._active_connections[channel].items())
            for client_id, ws in clients:
                try:
                    await ws.send_json(message)
                except Exception:
                    # Handle dropped sockets on-the-fly to protect server health
                    self.disconnect(channel, client_id)
                    
    def get_active_client_count(self, channel: str) -> int:
        """Returns the number of active connected clients on a given channel."""
        return len(self._active_connections.get(channel, {}))
