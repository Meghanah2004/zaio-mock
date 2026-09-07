"""Shared, process-wide singletons and FastAPI dependency functions.

One ``SecurityConfig`` and one ``RateLimiterRegistry`` are built here and
reused everywhere in ``api/`` - never re-instantiated per request, and
never duplicated as a second rate limiter (this project has exactly one:
``src/security/rate_limiter.py``).
"""
from __future__ import annotations

from fastapi import HTTPException, Request, status

# Import for its module-load side effect only: src.config runs
# _load_dotenv_if_present() at import time, which populates os.environ from
# a .env file (see .env.example) before SecurityConfig.from_env() below
# reads it. src.security.config itself never imports src.config, so
# without this, .env-based settings (CORS_ALLOWED_ORIGINS, rate limits,
# etc.) would silently have no effect on the API even though they already
# work for the CLI, which does import src.config early (src/cli.py).
import src.config  # noqa: F401
from src.security.config import SecurityConfig
from src.security.rate_limiter import RateLimiterRegistry

SECURITY_CONFIG = SecurityConfig.from_env()
RATE_LIMITER = RateLimiterRegistry(SECURITY_CONFIG)


def get_security_config() -> SecurityConfig:
    return SECURITY_CONFIG


def client_key(request: Request) -> str:
    """Best-effort per-caller rate-limit key.

    Uses the direct connecting peer address. Deliberately does NOT trust
    X-Forwarded-For / X-Real-IP (a caller controls those headers, which
    would let them pick their own rate-limit bucket) - if this API is ever
    deployed behind a trusted reverse proxy, the proxy layer is the right
    place to set the real client IP into ``request.client``, not something
    this application should parse from spoofable headers.
    """
    if request.client is None:
        return "unknown"
    return request.client.host


def enforce_generation_rate_limit(request: Request) -> None:
    """STRICT-ish tier: the one expensive, LLM-adjacent endpoint."""
    result = RATE_LIMITER.check_generation(client_key(request))
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for generation requests.",
            headers={"Retry-After": str(max(1, int(result.retry_after_seconds)))},
        )


def enforce_read_rate_limit(request: Request) -> None:
    """LOOSER tier: health checks and read-only result access."""
    result = RATE_LIMITER.check_read(client_key(request))
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded.",
            headers={"Retry-After": str(max(1, int(result.retry_after_seconds)))},
        )
