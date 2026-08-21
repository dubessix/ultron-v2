"""
Ultron Session Management Engine
Ensures secure session creation, state caching, and context validation.
"""

import uuid
import sqlite3
from typing import Dict, Any, Optional
from backend.app.database.db import get_db_connection
from backend.app.database.models import get_session, create_session

class SessionManager:
    @staticmethod
    def get_or_create_session(session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Validates an existing session ID or creates a secure new UUIDv4 context.
        Restores state parameters from database records.
        """
        # If no session was provided, generate a secure new ID
        if not session_id:
            return SessionManager.initialize_new_session()
            
        with get_db_connection() as conn:
            existing = get_session(conn, session_id)
            if existing:
                return existing
                
            # If session ID was provided but not found, initialize it cleanly
            return SessionManager.initialize_new_session(session_id)

    @staticmethod
    def initialize_new_session(custom_id: Optional[str] = None) -> Dict[str, Any]:
        """Creates and registers a new secure session into local SQLite database."""
        session_id = custom_id or str(uuid.uuid4())
        
        with get_db_connection() as conn:
            try:
                create_session(
                    conn=conn,
                    session_id=session_id,
                    active_project=None,
                    current_goal="Bootstrap V1",
                    current_mode="developer",
                    personality="ultron"
                )
                
                # Fetch created record to guarantee verification
                session_data = get_session(conn, session_id)
                if not session_data:
                    raise OSError("Session initialization check failed.")
                return session_data
                
            except sqlite3.Error as e:
                raise OSError(f"Failed to write new session state to database: {e}") from e
