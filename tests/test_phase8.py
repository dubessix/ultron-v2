"""
Ultron Unit & Integration Testing Suite — Phase 8 Diagnostics
Tests multi-channel WebSocket connections, client subscription counts,
token-by-token stream packages, widget pushes, and channel broadcasts.
"""

import unittest
from fastapi.testclient import TestClient

from backend.app.main import app, ws_manager

class TestPhase8WebSocketArchitecture(unittest.TestCase):
    
    def test_websocket_handshake_and_subscriptions(self):
        """Test 1: Verify successful client handshake and correct channel pool indexing."""
        client = TestClient(app)
        
        # Verify active client count starts at 0
        self.assertEqual(ws_manager.get_active_client_count("events"), 0)
        
        # Establish connection handshake to /ws/events
        with client.websocket_connect("/ws/events?client_id=test_client_handshake") as websocket:
            # Active count must dynamically increment to 1
            self.assertEqual(ws_manager.get_active_client_count("events"), 1)
            # Use `websocket`: send a keep-alive frame to confirm it is live.
            websocket.send_text("ping")
            
        # After exit, client must automatically be removed from pool (prevents leaks)
        self.assertEqual(ws_manager.get_active_client_count("events"), 0)

    def test_websocket_token_streaming_completions(self):
        """Test 2: Verify that /ws/chat dispatches stream_start, tokens, stream_end, and done payloads."""
        client = TestClient(app)
        
        with client.websocket_connect("/ws/chat?client_id=test_streamer") as websocket:
            payload = {
                "session_id": "test_ws_sess",
                "content": "What is JavaScript?"
            }
            # Send chat query over WebSocket
            websocket.send_json(payload)
            
            # Read progress frame
            progress = websocket.receive_json()
            self.assertEqual(progress["type"], "progress")
            self.assertEqual(progress["state"], "thinking")
            
            # Read stream start signal
            start = websocket.receive_json()
            self.assertEqual(start["type"], "stream_start")
            
            # Read sequential token packets
            tokens = []
            while True:
                msg = websocket.receive_json()
                if msg["type"] == "stream_end":
                    break
                self.assertEqual(msg["type"], "token")
                tokens.append(msg["content"])
                
            # Verify stream end is followed by the final done transaction
            done = websocket.receive_json()
            self.assertEqual(done["type"], "done")
            self.assertEqual(done["active_personality"], "ultron")
            self.assertGreaterEqual(done["response_ms"], 0)
            
            # Reconstruct the streamed tokens — must be non-empty (real content),
            # but NOT bound to a specific provider string (mock vs real LLM).
            streamed_text = "".join(tokens)
            self.assertTrue(streamed_text.strip())

    def test_websocket_widget_push(self):
        """Test 3: Assert that querying 'todo' pushes a floating TodoWidget trigger."""
        client = TestClient(app)
        
        with client.websocket_connect("/ws/chat?client_id=test_widget_client") as websocket:
            payload = {
                "session_id": "test_ws_sess",
                "content": "Show my todo list."
            }
            websocket.send_json(payload)
            
            # Skip progress, stream_start, tokens, and stream_end
            websocket.receive_json() # progress
            websocket.receive_json() # stream_start
            
            while True:
                msg = websocket.receive_json()
                if msg["type"] == "stream_end":
                    break
            
            # Next message must be the widget trigger push (real data, not a fake 5)
            widget = websocket.receive_json()
            self.assertEqual(widget["type"], "widget")
            self.assertEqual(widget["widget_id"], "todo")
            self.assertEqual(widget["action"], "open")
            self.assertIsInstance(widget["data"]["todos_count"], int)
            self.assertGreaterEqual(widget["data"]["todos_count"], 0)

    def test_websocket_broadcast_distribution(self):
        """Test 4: Verify thread-safe channel broadcasting across multiple concurrent clients."""
        client = TestClient(app)
        
        # Connect two separate clients concurrently
        with client.websocket_connect("/ws/events?client_id=subscriber_1") as ws_1:
            with client.websocket_connect("/ws/events?client_id=subscriber_2") as ws_2:
                
                self.assertEqual(ws_manager.get_active_client_count("events"), 2)
                
                # Broadcaster event frame payload
                event_payload = {
                    "type": "personality_changed",
                    "active_personality": "zora",
                    "reason": "Stress score crossed."
                }
                
                # Trigger server broadcast
                import asyncio
                # Run synchronous wrapper around manager broadcast
                asyncio.run(ws_manager.broadcast("events", event_payload))
                
                # Both clients must receive the identical broadcast frame concurrently
                msg_1 = ws_1.receive_json()
                msg_2 = ws_2.receive_json()
                
                self.assertEqual(msg_1["type"], "personality_changed")
                self.assertEqual(msg_1["active_personality"], "zora")
                
                self.assertEqual(msg_2["type"], "personality_changed")
                self.assertEqual(msg_2["active_personality"], "zora")
