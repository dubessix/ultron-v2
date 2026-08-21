"""
Ultron Core Database Schemas and Transactions
Handles database initialization, parameterized migrations, and clean write/read helper operations.
Uses no heavy ORM to conserve RAM. Runs purely raw, optimized SQL queries.
"""

import sqlite3
import json
from typing import List, Dict, Optional, Any

# Schema versioning (Phase 9 durability): each integer maps to a migration step.
# initialize_database() creates the base schema then applies any pending
# migrations by stepping user_version forward. NEVER renumber/delete old steps —
# always append new ones.
SCHEMA_VERSION = 1

# Ordered migrations: {from_version: sql_or_callable}. Run in order until the DB
# user_version reaches SCHEMA_VERSION. Each is idempotent (guarded statements).
_MIGRATIONS = {
    # 0 -> 1 : baseline — the base schema is created by initialize_database();
    # this empty step simply advances user_version so future migrations have a
    # known starting point. Future schema changes append new steps below.
    0: "",
}


def _apply_migrations(conn: sqlite3.Connection, current: int) -> int:
    """Apply pending migrations sequentially, returning the new user_version."""
    version = current
    while version < SCHEMA_VERSION:
        migration = _MIGRATIONS.get(version)
        if migration is None:
            break  # no migration defined for this step; stop
        cursor = conn.cursor()
        if isinstance(migration, str):
            cursor.executescript(migration)
        else:
            migration(conn)
        version += 1
        conn.execute(f"PRAGMA user_version = {version};")
    return version


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Reads PRAGMA user_version (the current applied schema version)."""
    return conn.execute("PRAGMA user_version;").fetchone()[0]

def initialize_database(conn: sqlite3.Connection) -> None:
    """Creates tables for sessions, conversations, alarms, tasks, and calendar events using parameterized constraints."""
    cursor = conn.cursor()
    
    # 1. Create Sessions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            ended_at DATETIME,
            active_project TEXT,
            current_goal TEXT,
            current_mode TEXT DEFAULT 'developer',
            personality TEXT DEFAULT 'ultron',
            summary TEXT
        );
    """)
    
    # 2. Create Conversations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            user_message TEXT NOT NULL,
            ai_response TEXT NOT NULL,
            personality TEXT NOT NULL,
            tools_used TEXT DEFAULT '[]',
            widget_shown TEXT,
            intent TEXT DEFAULT 'Conversation',
            mode TEXT DEFAULT 'developer',
            path_used TEXT DEFAULT 'fast',
            response_ms INTEGER NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
    """)
    
    # 3. Create Reminders and Alarms table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders_alarms (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            target_time DATETIME NOT NULL,
            recurrence TEXT NOT NULL,
            recurrence_details TEXT,
            snooze_count INTEGER DEFAULT 0,
            status TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 4. Create Project Tasks table (Hierarchical Project-Module tree for TrustQuiz support)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS project_tasks (
            id TEXT PRIMARY KEY,
            project_name TEXT DEFAULT 'General',
            module_name TEXT DEFAULT 'Root',
            title TEXT NOT NULL,
            description TEXT,
            priority TEXT CHECK(priority IN ('high', 'medium', 'low')) DEFAULT 'medium',
            due_date DATETIME,
            status TEXT CHECK(status IN ('todo', 'in_progress', 'done')) DEFAULT 'todo',
            parent_task_id TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (parent_task_id) REFERENCES project_tasks(id) ON DELETE CASCADE
        );
    """)

    # 5. Create Calendar Events table (For Smart Day-planning)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS calendar_events (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            start_time DATETIME NOT NULL,
            end_time DATETIME NOT NULL,
            category TEXT DEFAULT 'general',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    conn.commit()

    # Phase 9: apply any pending schema migrations (idempotent).
    _apply_migrations(conn, get_schema_version(conn))

def create_session(
    conn: sqlite3.Connection,
    session_id: str,
    active_project: Optional[str] = None,
    current_goal: Optional[str] = None,
    current_mode: str = "developer",
    personality: str = "ultron"
) -> None:
    """Inserts a new session record into the database."""
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO sessions (id, active_project, current_goal, current_mode, personality)
        VALUES (?, ?, ?, ?, ?);
        """,
        (session_id, active_project, current_goal, current_mode, personality)
    )
    conn.commit()

def get_session(conn: sqlite3.Connection, session_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves session metadata by ID."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE id = ?;", (session_id,))
    row = cursor.fetchone()
    if row:
        return dict(row)
    return None

def update_session_personality(conn: sqlite3.Connection, session_id: str, personality: str) -> None:
    """Persists the active personality on a session so it survives across requests."""
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE sessions SET personality = ? WHERE id = ?;",
        (personality, session_id)
    )
    conn.commit()


def update_session_project(conn: sqlite3.Connection, session_id: str, project_id: str) -> None:
    """Persist the active project used to scope long-term memories."""
    conn.execute(
        "UPDATE sessions SET active_project = ? WHERE id = ?;",
        (project_id, session_id),
    )
    conn.commit()


def save_conversation(
    conn: sqlite3.Connection,
    msg_id: str,
    session_id: str,
    user_message: str,
    ai_response: str,
    personality: str,
    tools_used: Optional[List[str]] = None,
    widget_shown: Optional[str] = None,
    intent: str = "Conversation",
    mode: str = "developer",
    path_used: str = "fast",
    response_ms: int = 0
) -> None:
    """Saves a conversational turn cleanly with JSON serialized metadata list."""
    tools_str = json.dumps(tools_used or [])
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO conversations (
            id, session_id, user_message, ai_response, personality, 
            tools_used, widget_shown, intent, mode, path_used, response_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            msg_id, session_id, user_message, ai_response, personality,
            tools_str, widget_shown, intent, mode, path_used, response_ms
        )
    )
    conn.commit()

def get_conversation_history(conn: sqlite3.Connection, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieves history of conversation records inside a specific session."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM (
            SELECT rowid AS _rowid, * FROM conversations
            WHERE session_id = ?
            ORDER BY timestamp DESC, rowid DESC
            LIMIT ?
        )
        ORDER BY timestamp ASC, _rowid ASC;
        """,
        (session_id, limit)
    )
    rows = cursor.fetchall()
    history = []
    for row in rows:
        item = dict(row)
        item.pop("_rowid", None)
        # Safely parse JSON strings back to python lists
        try:
            item["tools_used"] = json.loads(item["tools_used"])
        except (json.JSONDecodeError, TypeError):
            item["tools_used"] = []
        history.append(item)
    return history
