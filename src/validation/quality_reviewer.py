"""LLM-based quality review stage.

Runs AFTER the deterministic validators (schema/marks/coverage) have already
passed - this stage is for the judgement calls a schema can't make
(ambiguity, occupational realism, whether a "fix" is actually safe), not for
structural checks, which stay deterministic per docs/DESIGN.md.

The reviewer's ``approved: false`` or per-question issues are a signal for
*targeted* regeneration of the affected question/memo only - never a reason
to regenerate the whole paper.
"""
from __future__ import annotations

import json
from typing import Any

from src.generation.llm_utils import (
    call_provider_with_retry,
    extract_json,
    load_prompt_template,
)
from src.providers.base import LLMProvider


def run_quality_review(paper: dict[str, Any], memo: dict[str, Any], provider: LLMProvider) -> dict[str, Any]:
    template = load_prompt_template("review.txt")
    system_part, _, user_part = template.partition("USER (templated at call time):")
    system_prompt = system_part.replace("SYSTEM:", "", 1).strip()
    user_prompt = (
        user_part.replace("{paper_json}", json.dumps(paper)).replace("{memo_json}", json.dumps(memo)).strip()
    )
    task = {"kind": "quality_review", "paper": paper, "memo": memo}
    raw = call_provider_with_retry(provider, system_prompt, user_prompt, task)
    review = extract_json(raw)

    review.setdefault("approved", False)
    review.setdefault("issues", [])
    review.setdefault("question_reviews", [])
    return review
