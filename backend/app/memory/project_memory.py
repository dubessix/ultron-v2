"""
Ultron Project State Memory Layer
Handles per-project goals, tech stacks, and active decision registries.
"""

from typing import Optional
from backend.app.database.db import get_db_connection

class ProjectMemory:
    def __init__(self) -> None:
        self._initialize_table()

    def _initialize_table(self) -> None:
        """Initializes self-contained project_metadata table on instantiation."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS project_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
            conn.commit()

    def set_project_state(self, key: str, value: str) -> None:
        """Saves or updates a project parameter state in SQLite."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO project_metadata (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value;
                """,
                (key, value)
            )
            conn.commit()

    def get_project_state(self, key: str) -> Optional[str]:
        """Retrieves a project parameter state by its key."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM project_metadata WHERE key = ?;", (key,))
            row = cursor.fetchone()
            if row:
                return row["value"]
            return None

    def clear_project_state(self) -> None:
        """Wipes project metadata states."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM project_metadata;")
            conn.commit()
