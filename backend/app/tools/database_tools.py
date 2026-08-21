"""Dangerous database actions exposed through the exact-confirmation registry."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from pydantic import BaseModel, Field

from backend.app.database.backup import restore_database
from backend.app.database.durability import load_durability_settings
from backend.app.tools.tool_base import BaseTool


class DatabaseRestoreArgs(BaseModel):
    backup_path: str = Field(..., min_length=1, description="Approved local SQLite backup file.")


class DatabaseRestoreTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            tool_id="database_restore",
            name="Database Restore",
            description="Restore an approved verified backup with maintenance lock and rollback.",
            category="database",
            tags=["database", "restore", "backup", "durability"],
            permission_level=3,
            args_model=DatabaseRestoreArgs,
            usage_examples=["database_restore(backup_path='data/memory/backups/ultron_....db')"],
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        settings = load_durability_settings()
        return await asyncio.to_thread(
            restore_database,
            kwargs["backup_path"],
            settings.restore_lock_timeout_seconds,
        )
