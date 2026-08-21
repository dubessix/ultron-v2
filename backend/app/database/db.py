"""
Ultron Core Database Connection Manager.

All application SQLite connections pass through one process-wide maintenance
coordinator. Normal readers/writers may run concurrently, but a database restore
first blocks new connections and waits for existing connections to close. This
prevents live chat/tool/background writes from racing an atomic restore.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

# Resolve all storage through one runtime policy. Under pytest/unittest this
# points to a process-local temporary root; production continues to use data/.
from backend.app.runtime_paths import TEST_MODE, runtime_data_path

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
DB_DIR = runtime_data_path("memory")
DB_PATH = DB_DIR / ("test_ultron.db" if TEST_MODE else "ultron.db")

# Ensure directory existence before running transactions.
DB_DIR.mkdir(parents=True, exist_ok=True)


class DatabaseMaintenanceError(RuntimeError):
    """Raised when normal DB access is attempted during exclusive maintenance."""


class DatabaseMaintenanceTimeoutError(DatabaseMaintenanceError):
    """Raised when existing connections do not drain before the restore timeout."""


class DatabaseMaintenanceCoordinator:
    """Small in-process readers/maintenance gate for SQLite lifecycle safety."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._active_connections = 0
        self._maintenance_active = False
        self._reason = None

    @contextmanager
    def database_access(self) -> Generator[None, None, None]:
        """Register one normal DB connection or fail fast during maintenance."""
        with self._condition:
            if self._maintenance_active:
                raise DatabaseMaintenanceError(
                    f"Database is temporarily unavailable for maintenance ({self._reason or 'restore'})."
                )
            self._active_connections += 1
        try:
            yield
        finally:
            with self._condition:
                self._active_connections -= 1
                if self._active_connections == 0:
                    self._condition.notify_all()

    @contextmanager
    def maintenance(
        self,
        reason: str = "restore",
        timeout_seconds: float = 30.0,
    ) -> Generator[None, None, None]:
        """Block new DB connections and wait for current users to drain."""
        timeout_seconds = max(0.01, float(timeout_seconds))
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            if self._maintenance_active:
                raise DatabaseMaintenanceError(
                    f"Database maintenance is already active ({self._reason or 'unknown'})."
                )
            self._maintenance_active = True
            self._reason = str(reason or "maintenance")
            while self._active_connections:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._maintenance_active = False
                    self._reason = None
                    self._condition.notify_all()
                    raise DatabaseMaintenanceTimeoutError(
                        "Timed out waiting for active database connections to close."
                    )
                self._condition.wait(timeout=remaining)
        try:
            yield
        finally:
            with self._condition:
                self._maintenance_active = False
                self._reason = None
                self._condition.notify_all()

    def status(self) -> dict:
        with self._condition:
            return {
                "maintenance_active": self._maintenance_active,
                "reason": self._reason,
                "active_connections": self._active_connections,
            }


maintenance_coordinator = DatabaseMaintenanceCoordinator()


@contextmanager
def get_db_connection() -> Generator[sqlite3.Connection, None, None]:
    """
    Yield a configured SQLite connection protected by the maintenance gate.

    WAL + NORMAL synchronous mode remain appropriate for everyday local writes;
    verified backups use SQLite's online backup API rather than copying a live
    WAL database file.
    """
    conn = None
    with maintenance_coordinator.database_access():
        try:
            conn = sqlite3.connect(
                str(DB_PATH),
                timeout=15.0,
                check_same_thread=False,
            )
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.row_factory = sqlite3.Row

            # A standalone unittest process does not load pytest fixtures. In test
            # mode, initialize the isolated schema on every fresh temporary DB so
            # pytest and unittest are independently safe and deterministic.
            if TEST_MODE:
                from backend.app.database.models import initialize_database
                initialize_database(conn)

            yield conn
        except sqlite3.Error as exc:
            if conn:
                conn.rollback()
            raise OSError(f"Database transaction failure: {exc}") from exc
        finally:
            if conn:
                conn.close()
