"""
Ultron Unit & Integration Testing Suite — Phase 1 Verification
Validates database connection pooling, schema integrity, session isolation, and REST chat routing.
"""

import unittest
import sqlite3
import uuid
from fastapi.testclient import TestClient

from backend.app.database.db import get_db_connection
from backend.app.database.models import initialize_database, get_conversation_history
from backend.app.main import app

class TestPhase1Architecture(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        """Perform database setup checks on startup."""
        # Initialize target database with schemas
        with get_db_connection() as conn:
            initialize_database(conn)

    def test_database_connection_and_wal_mode(self):
        """Test 1: Verify thread-safe SQLite connection and check WAL mode activation."""
        with get_db_connection() as conn:
            self.assertIsInstance(conn, sqlite3.Connection)
            # Fetch journal mode state from SQLite PRAGMA
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode;")
            mode = cursor.fetchone()[0]
            self.assertEqual(mode.lower(), "wal")

    def test_database_schema_integrity(self):
        """Test 2: Verify both tables sessions and conversations are successfully built."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Verify sessions tables existence
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions';")
            sessions_table = cursor.fetchone()
            self.assertIsNotNone(sessions_table)
            
            # Verify conversations tables existence
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='conversations';")
            conversations_table = cursor.fetchone()
            self.assertIsNotNone(conversations_table)

    def test_session_isolation_and_lookup(self):
        """Test 3: Assert that session management holds unique keys and isolated state caches."""
        client = TestClient(app)
        
        # Dispatch two independent requests to create isolated sessions
        response1 = client.post("/api/chat", json={"content": "Ping Session 1"})
        self.assertEqual(response1.status_code, 200)
        session_id_1 = response1.json()["session_id"]
        
        response2 = client.post("/api/chat", json={"content": "Ping Session 2"})
        self.assertEqual(response2.status_code, 200)
        session_id_2 = response2.json()["session_id"]
        
        # Verify IDs do not overlap
        self.assertNotEqual(session_id_1, session_id_2)

    def test_chat_echo_e2e_transactions(self):
        """Test 4: Verify full REST POST transaction sequence and database state writes."""
        client = TestClient(app)
        
        test_session_id = str(uuid.uuid4())
        test_message = "Test transaction string verification."
        
        # Dispatch chat request
        response = client.post(
            "/api/chat",
            json={"session_id": test_session_id, "content": test_message}
        )
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertEqual(data["session_id"], test_session_id)

        # Provider-agnostic assertions: the e2e transaction must return real,
        # non-empty content and the correct personality — but NOT a specific
        # mock/realtime string, since the active LLM provider can vary.
        self.assertTrue(data["content"])  # non-empty response
        self.assertEqual(data["personality"], "ultron")  # Standard startup default

        # Validate record is safely saved into the database
        with get_db_connection() as conn:
            history = get_conversation_history(conn, test_session_id)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["user_message"], test_message)
            self.assertTrue(history[0]["ai_response"])  # saved response is non-empty

if __name__ == "__main__":
    unittest.main()
