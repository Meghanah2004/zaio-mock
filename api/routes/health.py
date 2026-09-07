"""GET /api/health - minimal, safe liveness check.

LOOSER rate-limit tier (src/security/rate_limiter.py's "read" bucket) -
cheap, read-only, meant to be polled.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import enforce_read_rate_limit
from api.models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, dependencies=[Depends(enforce_read_rate_limit)])
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
