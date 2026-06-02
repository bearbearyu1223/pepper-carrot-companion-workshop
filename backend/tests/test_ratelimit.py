"""Tests for the chat abuse guards.

The sliding-window limiter is the security-adjacent bit (it's the app-level
backstop against scripted abuse of the unauthenticated, cost-bearing chat
route), so it gets a focused unit test with an injected clock — deterministic,
no sleeping. The message-length guard is exercised through the Pydantic model.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.messages import _MAX_MESSAGE_CHARS, SendMessageBody
from app.api.ratelimit import SlidingWindowRateLimiter


class _FakeClock:
    """A monotonic clock we can advance by hand."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_allows_up_to_the_limit_then_blocks() -> None:
    clock = _FakeClock()
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60.0, clock=clock)

    # First three in the window are fine.
    for _ in range(3):
        limiter.check("1.2.3.4")

    # The fourth within the same window is rejected with 429 + Retry-After.
    with pytest.raises(HTTPException) as excinfo:
        limiter.check("1.2.3.4")
    assert excinfo.value.status_code == 429
    assert "retry-after" in {k.lower() for k in (excinfo.value.headers or {})}


def test_window_slides_so_old_hits_age_out() -> None:
    clock = _FakeClock()
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60.0, clock=clock)

    limiter.check("ip")
    limiter.check("ip")
    with pytest.raises(HTTPException):
        limiter.check("ip")  # blocked at t=1000

    clock.advance(61.0)  # both earlier hits are now older than the window
    limiter.check("ip")  # allowed again — no exception


def test_limit_is_per_key() -> None:
    clock = _FakeClock()
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60.0, clock=clock)

    limiter.check("ip-a")
    limiter.check("ip-b")  # a different client is unaffected by a's budget
    with pytest.raises(HTTPException):
        limiter.check("ip-a")  # a's own second request is blocked


def test_zero_disables_the_limiter() -> None:
    limiter = SlidingWindowRateLimiter(max_requests=0, window_seconds=60.0)
    assert limiter.enabled is False
    for _ in range(1000):
        limiter.check("anyone")  # never raises


def test_message_length_guard_rejects_oversized_input() -> None:
    # A normal question validates.
    ok = SendMessageBody(mode="page", message="Who is on this page?")
    assert ok.message

    # An empty message and an over-long one are both rejected by the model.
    with pytest.raises(ValueError):
        SendMessageBody(mode="page", message="")
    with pytest.raises(ValueError):
        SendMessageBody(mode="page", message="x" * (_MAX_MESSAGE_CHARS + 1))
