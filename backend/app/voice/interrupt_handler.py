"""
Ultron Voice Interruption Handler
Manages barge-ins, instantly cancelling active async speech generation tasks to stop sound streams.
"""

import asyncio
from typing import Optional

class InterruptHandler:
    def __init__(self) -> None:
        self._active_task: Optional[asyncio.Task] = None

    def register_task(self, task: asyncio.Task) -> None:
        """Registers the active speech synthesis task for interruption tracking."""
        self._active_task = task

    def trigger_interrupt(self) -> bool:
        """
        Instantly cancels the active speech synthesis task (barge-in).
        Returns True if a task was actively cancelled, False otherwise.
        """
        if self._active_task and not self._active_task.done():
            self._active_task.cancel()
            print("[INTERRUPT_HANDLER] Barge-In: Active speech synthesis task cancelled successfully.")
            self._active_task = None
            return True
            
        self._active_task = None
        return False
