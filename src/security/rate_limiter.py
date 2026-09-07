"""Reusable, in-memory rate limiter.

PREPARED FOR A FUTURE API LAYER. This component is fully implemented and
tested, but this project is currently CLI-only - there is no HTTP server
for it to protect yet, and it is not invoked anywhere in the live pipeline.
Do not read its presence as evidence that an API is rate-limited today.

Design: a token bucket per key (e.g. per-IP, per-API-key, or per
operation-class once those concepts exist). Deliberately in-process and
single-node - this is a Phase 1 local tool, not a distributed service, so
a Redis-backed or otherwise distributed limiter would be over-engineering
per the project's explicit scope. If this application is ever deployed
behind multiple worker processes, this in-memory limiter would need to be
replaced with a shared store - documented here rather than built
speculatively.

Intended endpoint classes (see docs/DESIGN.md and docs/SECURITY-AUDIT.md
for the full mapping), once an API exists:

    STRICT   - expensive generation / LLM operations, and any future
               authentication endpoints. Small limit, small window.
    MODERATE - public/read-only endpoints (e.g. fetching a rendered paper).
    LOOSER   - authenticated user operations, if authentication is ever
               introduced. Not used today - no authentication exists.

This module does not implement account lockouts. Repeated failures are
never used to lock out a caller entirely; only to throttle request rate,
which is a rate-limiter's job, not an auth system's.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: float
    retry_after_seconds: float


class TokenBucketRateLimiter:
    """A simple, thread-safe, per-key token bucket.

    ``rate`` tokens are added per ``window_seconds``; ``burst`` extra
    tokens may accumulate on top of a full bucket so a caller who has been
    idle can make a short burst of requests before being throttled to the
    steady-state rate.
    """

    def __init__(self, rate: int, window_seconds: float, burst: int = 0):
        if rate <= 0:
            raise ValueError("rate must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if burst < 0:
            raise ValueError("burst must not be negative")
        self._rate = rate
        self._window_seconds = window_seconds
        self._capacity = rate + burst
        self._refill_per_second = rate / window_seconds
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_refill_ts)

    def _refill(self, key: str, now: float) -> float:
        tokens, last = self._buckets.get(key, (float(self._capacity), now))
        elapsed = max(0.0, now - last)
        tokens = min(self._capacity, tokens + elapsed * self._refill_per_second)
        self._buckets[key] = (tokens, now)
        return tokens

    def check(self, key: str, *, cost: float = 1.0, now: float | None = None) -> RateLimitResult:
        """Consume ``cost`` tokens for ``key`` if available.

        Does not raise - returns a result the caller decides what to do
        with (a future API layer would turn ``allowed=False`` into an HTTP
        429 with a ``Retry-After`` header set from ``retry_after_seconds``).
        """
        now = time.monotonic() if now is None else now
        with self._lock:
            tokens = self._refill(key, now)
            if tokens >= cost:
                self._buckets[key] = (tokens - cost, now)
                return RateLimitResult(allowed=True, remaining=tokens - cost, retry_after_seconds=0.0)

            missing = cost - tokens
            retry_after = missing / self._refill_per_second if self._refill_per_second > 0 else self._window_seconds
            return RateLimitResult(allowed=False, remaining=tokens, retry_after_seconds=retry_after)

    def reset(self, key: str) -> None:
        with self._lock:
            self._buckets.pop(key, None)


class RateLimiterRegistry:
    """Named limiters for different endpoint classes, built from one
    SecurityConfig - the "one place" configuration lives in
    src/security/config.py, this just wires named limiters to it.
    """

    def __init__(self, security_config):  # type: ignore[no-untyped-def]  # avoid import cycle with src.security.config
        self.enabled = security_config.rate_limit_enabled
        self.generation = TokenBucketRateLimiter(
            rate=security_config.generation_rate_limit,
            window_seconds=security_config.generation_rate_window_seconds,
            burst=security_config.generation_burst,
        )
        self.read = TokenBucketRateLimiter(
            rate=security_config.read_rate_limit,
            window_seconds=security_config.read_rate_window_seconds,
        )

    def check_generation(self, key: str) -> RateLimitResult:
        if not self.enabled:
            return RateLimitResult(allowed=True, remaining=float("inf"), retry_after_seconds=0.0)
        return self.generation.check(key)

    def check_read(self, key: str) -> RateLimitResult:
        if not self.enabled:
            return RateLimitResult(allowed=True, remaining=float("inf"), retry_after_seconds=0.0)
        return self.read.check(key)
