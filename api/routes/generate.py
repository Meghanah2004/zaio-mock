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


@router.post("/generate", response_model=GenerateResponse, dependencies=[Depends(enforce_generation_rate_limit)])
async def generate(request: GenerateRequest) -> GenerateResponse:
    result = generate_paper_and_memo(
        qualification=request.qualification,
        paper_number=request.paper_number,
        seed=request.seed,
        want_pdf=request.pdf,
    )
    return GenerateResponse(**dataclasses.asdict(result))
