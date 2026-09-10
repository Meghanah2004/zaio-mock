"""POST /api/generate - request one Mock EISA paper + memo.

The one expensive, LLM-adjacent endpoint - uses the stricter "generation"
rate-limit tier. Runs synchronously; see docs/API.md, "Why generation is
synchronous," for why no job queue was introduced.
"""
from __future__ import annotations

import dataclasses

from fastapi import APIRouter, Depends

from api.dependencies import enforce_generation_rate_limit
from api.models import GenerateRequest, GenerateResponse
from api.service import generate_paper_and_memo

router = APIRouter(tags=["generate"])


# REWORK (final audit - event-loop-blocking finding): a plain `def`, not
# `async def`. generate_paper_and_memo is fully synchronous, blocking work
# (real file I/O, and blocking HTTP calls to whichever real provider is
# configured - Groq/Anthropic/Gemini's SDKs all use a synchronous HTTP
# client, never an async one - confirmed directly, none of the three
# provider modules imports an Async* client). An `async def` route that
# calls blocking code directly, with no `await`/threadpool dispatch, blocks
# the ENTIRE asyncio event loop for the whole call - which, per docs/API.md
# ("Why generation is synchronous"), is itself already documented to take
# anywhere from a few seconds to several minutes with a real provider. That
# would have stalled every OTHER request on the same worker - including
# `GET /api/health`, which platforms/orchestrators rely on to decide
# whether an instance is still alive - for the full duration of any
# in-flight generation. A plain `def` route handler is the standard,
# FastAPI-documented fix for exactly this shape of endpoint: FastAPI runs
# `def` path operations in an external threadpool automatically, so
# blocking work here no longer blocks the event loop other requests share.
# Purely a dispatch-mechanism change - no request/response shape, no
# validation, no rate-limiting, no generation logic is touched.
@router.post("/generate", response_model=GenerateResponse, dependencies=[Depends(enforce_generation_rate_limit)])
def generate(request: GenerateRequest) -> GenerateResponse:
    result = generate_paper_and_memo(
        qualification=request.qualification,
        paper_number=request.paper_number,
        seed=request.seed,
        want_pdf=request.pdf,
    )
    return GenerateResponse(**dataclasses.asdict(result))
