"""Central lifecycle manager for process-owned asyncio background tasks."""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Awaitable, Callable
from typing import Any, Dict, Optional


class BackgroundTaskManager:
    """Track, deduplicate, observe, and cancel application background tasks."""

    def __init__(self) -> None:
        self._tasks: Dict[str, asyncio.Task] = {}
        self._counter = itertools.count(1)

    def _register(self, key: str, awaitable: Awaitable[Any]) -> asyncio.Task:
        task = asyncio.create_task(awaitable, name=f"ultron:{key}")
        self._tasks[key] = task

        def _finished(done: asyncio.Task, *, task_key: str = key) -> None:
            if self._tasks.get(task_key) is done:
                self._tasks.pop(task_key, None)
            if done.cancelled():
                return
            try:
                error = done.exception()
            except (asyncio.CancelledError, RuntimeError):
                return
            if error is not None:
                print(f"[BACKGROUND_TASKS] Task '{task_key}' failed: {error}")

        task.add_done_callback(_finished)
        return task

    def start_singleton(
        self,
        name: str,
        factory: Callable[[], Awaitable[Any]],
    ) -> asyncio.Task:
        """Start one named task; return the existing live task on duplicates."""
        key = str(name)
        existing = self._tasks.get(key)
        if existing is not None and not existing.done():
            return existing
        return self._register(key, factory())

    def create(self, awaitable: Awaitable[Any], name: str = "task") -> asyncio.Task:
        """Track a non-singleton task such as one memory-persistence operation."""
        key = f"{name}#{next(self._counter)}"
        return self._register(key, awaitable)

    def active_count(self) -> int:
        return sum(1 for task in self._tasks.values() if not task.done())

    def active_names(self) -> list[str]:
        return sorted(name for name, task in self._tasks.items() if not task.done())

    async def cancel_all(self, timeout_seconds: float = 10.0) -> dict:
        """Cancel and await every owned task so shutdown leaves no orphan loops."""
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        timed_out = False
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=max(0.1, float(timeout_seconds)),
                )
            except asyncio.TimeoutError:
                timed_out = True
        cancelled = len(tasks)
        self._tasks = {
            name: task for name, task in self._tasks.items() if not task.done()
        }
        return {
            "cancelled": cancelled,
            "remaining": self.active_count(),
            "timed_out": timed_out,
        }


_background_tasks: Optional[BackgroundTaskManager] = None


def get_background_task_manager() -> BackgroundTaskManager:
    global _background_tasks
    if _background_tasks is None:
        _background_tasks = BackgroundTaskManager()
    return _background_tasks
