"""Owner says "stop" / "ruko" while a job runs (V2 Step D).

One process-wide stop moment. Every job remembers when it began (a context
variable, so it follows the job into its tool calls); a stop that arrives after
that moment makes ``requested()`` true for that job only. The next job begins
later, so it is never affected. The job loop checks between steps, and a
command running in wait mode is ended at once. Background servers the owner
started earlier are left alone.
"""

from __future__ import annotations

import contextvars
import time

_stop_at: float = 0.0
_job_started: contextvars.ContextVar = contextvars.ContextVar("ultron_job_started", default=None)

STOPPED_REPLY = "Stopped, Sir."


def begin() -> float:
    """Call when a job (one owner request) starts."""
    started = time.monotonic()
    _job_started.set(started)
    return started


def request() -> None:
    """The owner said stop: every job that is already running stops at its next step."""
    global _stop_at
    _stop_at = time.monotonic()


def requested() -> bool:
    started = _job_started.get()
    return started is not None and _stop_at >= started
