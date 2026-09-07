"""GET /api/results/{result_id} and PDF sub-resources.

``result_id`` is typed as a bounded ``int`` path parameter - FastAPI/Pydantic
reject anything that isn't a plain integer in range before this module's
code ever runs, so path traversal via this parameter is structurally
impossible (see api/results.py for the full reasoning). LOOSER rate-limit
tier - read-only access to already-generated results.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi import Path as PathParam
from fastapi.responses import FileResponse

from api import results as result_files
from api.dependencies import SECURITY_CONFIG, enforce_read_rate_limit
from api.models import ResultResponse
from src.validation.schema_validator import load_json_file

router = APIRouter(tags=["results"])

_ResultId = PathParam(..., ge=SECURITY_CONFIG.min_paper_number, le=SECURITY_CONFIG.max_paper_number)


@router.get("/results/{result_id}", response_model=ResultResponse, dependencies=[Depends(enforce_read_rate_limit)])
async def get_result(result_id: int = _ResultId) -> ResultResponse:
    if not result_files.result_exists(result_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result not found.")
    paper = load_json_file(result_files.paper_json_path(result_id))
    memo = load_json_file(result_files.memo_json_path(result_id))
    return ResultResponse(
        result_id=result_id,
        available_formats=result_files.available_formats(result_id),
        paper=paper,
        memo=memo,
    )


@router.get("/results/{result_id}/paper.pdf", dependencies=[Depends(enforce_read_rate_limit)])
async def get_paper_pdf(result_id: int = _ResultId) -> FileResponse:
    path = result_files.paper_pdf_path(result_id)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper PDF not found for this result.")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.get("/results/{result_id}/memo.pdf", dependencies=[Depends(enforce_read_rate_limit)])
async def get_memo_pdf(result_id: int = _ResultId) -> FileResponse:
    path = result_files.memo_pdf_path(result_id)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memo PDF not found for this result.")
    return FileResponse(path, media_type="application/pdf", filename=path.name)
