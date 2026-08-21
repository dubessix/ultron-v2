"""
Ultron Persistent Metadata Memory Layer
Stores permanent key-value parameters (such as user profile details and configs) in SQLite.
"""

from typing import Optional
from backend.app.database.db import get_db_connection

class PersistentMemory:
    def __init__(self) -> None:
        self._initialize_table()

    def _initialize_table(self) -> None:
        """Initializes self-contained persistent_metadata table on instantiation."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS persistent_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
            conn.commit()

    def set(self, key: str, value: str) -> None:
        """Saves or updates a permanent key-value pair in SQLite."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO persistent_metadata (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value;
                """,
                (key, value)
            )
            conn.commit()

    def get(self, key: str) -> Optional[str]:
        """Retrieves a saved permanent string parameter by its key."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM persistent_metadata WHERE key = ?;", (key,))
            row = cursor.fetchone()
            if row:
                return row["value"]
            return None

    def delete(self, key: str) -> None:
        """Deletes a permanent metadata parameter by its key."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM persistent_metadata WHERE key = ?;", (key,))
            conn.commit()

    def clear(self) -> None:
        """Wipes persistent metadata values."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM persistent_metadata;")
            conn.commit()
