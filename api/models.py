"""Pydantic request/response models for the API.

Strict by construction: every request model forbids unknown fields
(``extra="forbid"``) and every bound (paper_number/seed ranges) is read
from the SAME ``SecurityConfig`` the CLI already uses
(``src/security/config.py``) - no duplicated constants.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.dependencies import SECURITY_CONFIG
from src.config import SUPPORTED_QUALIFICATIONS


class GenerateRequest(BaseModel):
    """Everything the server needs to generate one Mock EISA paper + memo.

    Deliberately does NOT accept any filesystem path, reference-corpus
    location, prompt path, or schema path from the client - the server
    alone controls those (see docs/API.md, "No client-supplied paths").
    """

    model_config = ConfigDict(extra="forbid")

    qualification: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Must be one of the server's supported qualifications.",
        examples=["software_developer"],
    )
    paper_number: int = Field(
        ...,
        ge=SECURITY_CONFIG.min_paper_number,
        le=SECURITY_CONFIG.max_paper_number,
        description="Also used as the public result_id for retrieving this paper afterward.",
    )
    seed: int = Field(
        ...,
        ge=SECURITY_CONFIG.min_seed,
        le=SECURITY_CONFIG.max_seed,
        description="Deterministic generation seed (see docs/DESIGN.md, Reproducibility).",
    )
    pdf: bool = Field(default=False, description="Also render PDF versions of the paper and memo.")

    @field_validator("qualification")
    @classmethod
    def _qualification_supported(cls, value: str) -> str:
        if value not in SUPPORTED_QUALIFICATIONS:
            raise ValueError(
                f"Unsupported qualification {value!r}. Allowed: {sorted(SUPPORTED_QUALIFICATIONS)}"
            )
        return value


class ValidationCheckModel(BaseModel):
    name: str
    passed: bool
    details: str


class GenerateResponse(BaseModel):
    result_id: int
    paper_id: str
    qualification: str
    total_marks: int
    validation_passed: bool
    deterministic_checks_passed: int
    deterministic_checks_total: int
    novelty_status: Literal["pass", "flag_for_review", "regenerate"] | None
    quality_review_approved: bool
    pdf_available: bool


class ResultResponse(BaseModel):
    """The full generated paper and memo for one result_id.

    ``paper``/``memo`` are the same JSON Schema-validated documents written
    to ``output/`` by the CLI - modeled here as ``dict[str, Any]`` rather
    than a re-declared Pydantic shape, since ``schemas/paper.schema.json``
    and ``schemas/memo.schema.json`` already are the source of truth for
    their structure (see docs/API.md, "Reuse over duplication").
    """

    result_id: int
    available_formats: list[str]
    paper: dict[str, Any]
    memo: dict[str, Any]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str = "zaio-mock-eisa-api"


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
