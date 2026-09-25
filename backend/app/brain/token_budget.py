"""Per-provider sliding-window token/request budget (free-tier guard).

Groq's free tier limits are per ORGANIZATION (all keys share them), e.g.
gpt-oss-120b: 30 requests/min and 8K tokens/min. Cached prompt-prefix tokens
do NOT count toward those limits, so the router records
``prompt_tokens - cached_tokens + completion_tokens`` from each response.

The router asks ``room(provider, estimate)`` before a request:
  * ``0``  -> send now
  * ``>0`` -> seconds until the window has room; start the job on another
    provider, or (mid-job, provider locked) wait that long instead of eating
    a 429 error.
Zero dependencies, O(requests in the last minute) memory.
"""

from __future__ import annotations

import os
import time
from collections import deque
from typing import Callable, Optional

_WINDOW_SECONDS = 60.0
# Keep a safety margin: estimates are approximate (chars/4).
_HEADROOM = 0.9

_DEFAULT_LIMITS: dict[str, tuple[int, int]] = {
    # provider: (tokens per minute, requests per minute); 0 = unlimited/unknown
    "groq": (8000, 30),
}


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, "") or default))
    except ValueError:
        return default


class TokenBudget:
    def __init__(self, clock: Optional[Callable[[], float]] = None) -> None:
        self._clock = clock or time.monotonic
        self._events: dict[str, deque[tuple[float, int]]] = {}
        self._last_cached: dict[str, int] = {}

    # -- configuration -------------------------------------------------
    @staticmethod
    def limits(provider: str) -> tuple[int, int]:
        tpm, rpm = _DEFAULT_LIMITS.get(provider, (0, 0))
        prefix = f"ULTRON_{provider.upper()}"
        return _env_int(f"{prefix}_TPM", tpm), _env_int(f"{prefix}_RPM", rpm)

    # -- bookkeeping ---------------------------------------------------
    def _window(self, provider: str) -> deque[tuple[float, int]]:
        events = self._events.setdefault(provider, deque())
        cutoff = self._clock() - _WINDOW_SECONDS
        while events and events[0][0] <= cutoff:
            events.popleft()
        return events

    def used(self, provider: str) -> tuple[int, int]:
        events = self._window(provider)
        return sum(tokens for _, tokens in events), len(events)

    def record_usage(self, provider: str, usage: Optional[dict]) -> int:
        """Record one finished request from the provider's ``usage`` block."""
        usage = usage or {}
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        details = usage.get("prompt_tokens_details") or {}
        cached = int(details.get("cached_tokens") or 0) if isinstance(details, dict) else 0
        self._last_cached[provider] = cached
        counted = max(0, prompt - cached) + completion
        self._window(provider).append((self._clock(), counted))
        return counted

    def estimate(self, provider: str, payload_chars: int, max_output: int = 600) -> int:
        """Rough counted-token estimate for a request about to be sent.

        The stable prefix is usually cached (last response tells us how much),
        so subtract it, but never estimate below a quarter of the raw size.
        """
        raw = max(1, payload_chars // 4)
        uncached = max(raw - self._last_cached.get(provider, 0), raw // 4)
        return uncached + max_output

    # -- decision ------------------------------------------------------
    def room(self, provider: str, estimate: int) -> float:
        """0 if the request fits now, else seconds until it should fit."""
        tpm, rpm = self.limits(provider)
        if not tpm and not rpm:
            return 0.0
        events = self._window(provider)
        tokens_used = sum(tokens for _, tokens in events)
        fits_tokens = not tpm or tokens_used + estimate <= tpm * _HEADROOM
        fits_requests = not rpm or len(events) + 1 <= rpm
        if fits_tokens and fits_requests:
            return 0.0
        if not events:
            return 0.0  # one oversized request: let the provider decide
        now = self._clock()
        # Walk the window oldest-first until enough expires.
        freed_tokens, dropped = 0, 0
        for stamp, tokens in events:
            freed_tokens += tokens
            dropped += 1
            ok_tokens = not tpm or tokens_used - freed_tokens + estimate <= tpm * _HEADROOM
            ok_requests = not rpm or len(events) - dropped + 1 <= rpm
            if ok_tokens and ok_requests:
                return max(0.0, stamp + _WINDOW_SECONDS - now)
        return max(0.0, events[-1][0] + _WINDOW_SECONDS - now)
