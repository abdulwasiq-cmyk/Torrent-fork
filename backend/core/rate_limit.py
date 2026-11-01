"""Small in-memory per-client rate limit for the public lookup endpoints.

The endpoints that spend provider quota (TMDB title search, episode lists, NexStream
resolve) are reachable by anyone who knows the URL. This keeps one client from using it all.
It is per process, which is enough for a single small instance; it is not a security boundary.
"""
from __future__ import annotations

import math
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_DISABLED = os.getenv("RATE_LIMIT_DISABLED", "").strip().casefold() in {"1", "true", "yes", "on"}
try:
    _SCALE = max(0.1, float(os.getenv("RATE_LIMIT_SCALE", "1") or 1))
except ValueError:
    _SCALE = 1.0
_MAX_TRACKED_CLIENTS = 5000


def client_ip(request: Request) -> str:
    """The caller's address; behind Render's proxy it is the first X-Forwarded-For entry."""
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else "unknown"


class RateLimit:
    """FastAPI dependency: allow `limit` calls per `window` seconds for each client."""

    def __init__(self, name: str, limit: int, window: float = 60.0) -> None:
        self.name = name
        self.limit = max(1, int(limit * _SCALE))
        self.window = float(window)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def __call__(self, request: Request) -> None:
        if _DISABLED:
            return
        key = client_ip(request)
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry = max(1, math.ceil(self.window - (now - hits[0])))
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Try again in a few seconds.",
                    headers={"Retry-After": str(retry)},
                )
            hits.append(now)
            if len(self._hits) > _MAX_TRACKED_CLIENTS:
                for stale in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window]:
                    del self._hits[stale]
