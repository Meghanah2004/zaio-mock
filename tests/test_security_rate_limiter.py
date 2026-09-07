"""Tests for the rate-limiter component.

PREPARED FOR A FUTURE API LAYER (see src/security/rate_limiter.py's module
docstring) - these tests verify the component's own behaviour in
isolation; they do not exercise any live endpoint, because none exists yet.
"""
from __future__ import annotations

from src.security.config import SecurityConfig
from src.security.rate_limiter import RateLimiterRegistry, TokenBucketRateLimiter


def test_allows_requests_up_to_the_configured_rate():
    limiter = TokenBucketRateLimiter(rate=3, window_seconds=60)
    now = 1000.0
    for _ in range(3):
        result = limiter.check("client-a", now=now)
        assert result.allowed

    blocked = limiter.check("client-a", now=now)
    assert not blocked.allowed
    assert blocked.retry_after_seconds > 0


def test_burst_allows_extra_requests_beyond_steady_state_rate():
    limiter = TokenBucketRateLimiter(rate=2, window_seconds=60, burst=2)
    now = 1000.0
    results = [limiter.check("client-a", now=now) for _ in range(4)]
    assert all(r.allowed for r in results)
    assert not limiter.check("client-a", now=now).allowed


def test_tokens_refill_over_time():
    limiter = TokenBucketRateLimiter(rate=1, window_seconds=10)
    now = 1000.0
    assert limiter.check("client-a", now=now).allowed
    assert not limiter.check("client-a", now=now).allowed
    # 10 seconds later, exactly one token should have refilled.
    assert limiter.check("client-a", now=now + 10).allowed
    assert not limiter.check("client-a", now=now + 10).allowed


def test_keys_are_independent():
    limiter = TokenBucketRateLimiter(rate=1, window_seconds=60)
    now = 1000.0
    assert limiter.check("client-a", now=now).allowed
    assert not limiter.check("client-a", now=now).allowed
    # A different key must not be affected by client-a's usage.
    assert limiter.check("client-b", now=now).allowed


def test_reset_clears_a_key():
    limiter = TokenBucketRateLimiter(rate=1, window_seconds=60)
    now = 1000.0
    limiter.check("client-a", now=now)
    assert not limiter.check("client-a", now=now).allowed
    limiter.reset("client-a")
    assert limiter.check("client-a", now=now).allowed


def test_rejects_invalid_construction():
    import pytest

    with pytest.raises(ValueError):
        TokenBucketRateLimiter(rate=0, window_seconds=60)
    with pytest.raises(ValueError):
        TokenBucketRateLimiter(rate=1, window_seconds=0)
    with pytest.raises(ValueError):
        TokenBucketRateLimiter(rate=1, window_seconds=60, burst=-1)


def test_registry_builds_named_limiters_from_security_config():
    config = SecurityConfig(generation_rate_limit=2, generation_rate_window_seconds=60, generation_burst=0)
    registry = RateLimiterRegistry(config)

    assert registry.check_generation("caller-1").allowed
    assert registry.check_generation("caller-1").allowed
    assert not registry.check_generation("caller-1").allowed
    # The read-endpoint limiter is independent of the generation limiter.
    assert registry.check_read("caller-1").allowed


def test_registry_disabled_always_allows():
    config = SecurityConfig(rate_limit_enabled=False, generation_rate_limit=1, generation_rate_window_seconds=60)
    registry = RateLimiterRegistry(config)
    for _ in range(50):
        assert registry.check_generation("caller-1").allowed
