"""In-process per-client rate limiting for the cost-bearing chat route.

A small sliding-window limiter — no external dependency, no Redis. The app's
target is a single VM (see CLAUDE.md), so per-process state is acceptable: the
real cost ceiling is the provider spend cap you set in the Anthropic/Voyage
dashboards, and this is *defense-in-depth* against scripted abuse of the
unauthenticated chat endpoint (CORS only stops browsers, not `curl`).

The chat route is the only one that spends money — each request makes two
Anthropic calls (the streamed answer + the suggestion chips). Session creation
and the read APIs are cheap, so this limiter guards `POST .../messages`.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status

# Sweep idle keys once the table grows past this many distinct clients, so a
# long-lived process that has seen many IPs doesn't leak memory. Generous —
# scale-to-zero resets the process long before a portfolio demo reaches it.
_SWEEP_THRESHOLD = 10_000


def client_ip(request: Request) -> str:
    """Best-effort real client IP.

    Behind Fly's proxy the socket peer *is* the proxy, so the real client IP
    arrives in the ``Fly-Client-IP`` header; prefer it, then the first hop of
    ``X-Forwarded-For``, then the socket peer for a direct local run. These
    headers are set by the trusted proxy in production — we don't accept them
    from a direct connection that has no proxy in front, but for a portfolio
    demo the spend cap is the real backstop, so best-effort attribution is fine.
    """
    fly = request.headers.get("fly-client-ip")
    if fly:
        return fly.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


class SlidingWindowRateLimiter:
    """Allow at most ``max_requests`` per ``window_seconds`` per key.

    Sliding-window log: keep each key's recent hit timestamps and evict those
    older than the window on every check. ``max_requests <= 0`` disables the
    limiter entirely (handy for local dev and tests). ``clock`` is injectable so
    the behavior is testable without sleeping.
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    @property
    def enabled(self) -> bool:
        return self._max > 0

    def check(self, key: str) -> None:
        """Record a hit for ``key``; raise HTTP 429 if it exceeds the budget.

        On rejection the response carries a ``Retry-After`` header (seconds
        until the oldest in-window hit ages out), which well-behaved clients
        honor and which makes the limit legible to a human reading the demo.
        """
        if not self.enabled:
            return
        now = self._clock()
        cutoff = now - self._window
        if len(self._hits) >= _SWEEP_THRESHOLD:
            self._sweep(cutoff)

        hits = self._hits.get(key)
        if hits is None:
            hits = deque()
            self._hits[key] = hits
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= self._max:
            retry_after = max(1, int(self._window - (now - hits[0])))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests — please slow down and try again shortly.",
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)

    def _sweep(self, cutoff: float) -> None:
        """Drop keys whose hits have all aged out, bounding memory."""
        for key in list(self._hits.keys()):
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if not hits:
                del self._hits[key]
