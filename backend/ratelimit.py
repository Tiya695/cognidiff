"""Rate limiting.

Prevents API abuse: brute-force login attempts, and the replay attack in
Attack 12 where the same valid session batch is submitted fifty times to inflate
a daily average.

`slowapi` is listed in requirements.txt and is used for its middleware if it is
installed, but the limiter below is the one that actually enforces the limits.
It is dependency-free and deterministic, which matters because the attacker
simulations are encoded as automated tests, a limiter that behaves differently
under pytest is not a limiter you can regression-test.

Storage is in-process. That is correct for CogniDiff's single-instance
deployment and is called out in docs/dependency_audit.md as a documented
limitation: a multi-worker deployment would need a shared store such as Redis.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import HTTPException, Request, status


class RateLimiter:
    """Fixed-window counter, keyed by identity or client IP."""

    def __init__(self):
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self.enabled = True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def check(self, key: str, limit: int, window_s: float) -> tuple[bool, float]:
        """Return ``(allowed, retry_after_seconds)``."""
        if not self.enabled:
            return True, 0.0

        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            cutoff = now - window_s
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                return False, round(bucket[0] + window_s - now, 2)

            bucket.append(now)
            return True, 0.0


limiter = RateLimiter()


def _identity(request: Request, user: Optional[dict]) -> str:
    if user is not None:
        return f"user:{user['id']}"
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return f"ip:{fwd.split(',')[0].strip()}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


def enforce(
    request: Request,
    bucket: str,
    limit: int,
    window_s: float,
    user: Optional[dict] = None,
) -> None:
    """Raise 429 when the caller is over the limit."""
    key = f"{bucket}:{_identity(request, user)}"
    allowed, retry_after = limiter.check(key, limit, window_s)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )


# Limits, in one place so the docs and the tests can quote the same numbers.
LIMITS = {
    "session":  (5, 60.0),        # 5 batches per minute, one per 60s window
    "login":    (10, 300.0),      # 10 attempts per 5 minutes per IP
    "summary":  (10, 3600.0),     # Claude API is the expensive one
    "score":    (30, 60.0),
    "fit":      (6, 300.0),       # model training is CPU-heavy
    "default":  (120, 60.0),
}
