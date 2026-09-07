"""Generates the complete marking memo corresponding to a finalized paper.

One provider call per question (never a bulk "write the whole memo" call) so
each question's marking guidance is grounded in that exact question's final,
already-mark-checked content - this is the "small, specialized prompts over
one giant prompt" principle from docs/DESIGN.md.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.generation.llm_utils import (
    GenerationError,
    call_provider_with_retry,
    extract_json,
    load_prompt_template,
)
from src.providers.base import LLMProvider


def _build_memo_prompt(question: dict[str, Any]) -> tuple[str, str]:
    template = load_prompt_template("generate_memo.txt")
    system_part, _, user_part = template.partition("USER (templated at call time):")
    system_prompt = system_part.replace("SYSTEM:", "", 1).strip()
    user_prompt = user_part.replace("{question_json}", json.dumps(question)).strip()
    return system_prompt, user_prompt


def _validate_memo_marks(memo_question: dict[str, Any], question: dict[str, Any]) -> None:
    qid = question["id"]
    if memo_question.get("question_id") != qid:
        raise GenerationError(f"Memo question_id mismatch: expected {qid}, got {memo_question.get('question_id')!r}")

    sub_questions = question.get("sub_questions")
    if sub_questions:
        memo_subs = {sq["id"]: sq for sq in memo_question.get("sub_questions", [])}
        expected_ids = {sq["id"] for sq in sub_questions}
        if set(memo_subs) != expected_ids:
            raise GenerationError(
                f"{qid}: memo sub-question ids {sorted(memo_subs)} do not match "
                f"question sub-question ids {sorted(expected_ids)}."
            )
        for sq in sub_questions:
            memo_sq = memo_subs[sq["id"]]
            criteria_sum = sum(c["marks"] for c in memo_sq["criteria"])
            if criteria_sum != sq["marks"]:
                raise GenerationError(
                    f"{qid} sub-question {sq['id']}: memo criteria sum to {criteria_sum}, "
                    f"expected {sq['marks']}."
                )
            memo_sq["total_marks"] = sq["marks"]
    else:
        criteria_sum = sum(c["marks"] for c in memo_question["criteria"])
        if criteria_sum != question["marks"]:
            raise GenerationError(
                f"{qid}: memo criteria sum to {criteria_sum}, expected {question['marks']}."
            )
    memo_question["total_marks"] = question["marks"]


def generate_memo(paper: dict[str, Any], provider: LLMProvider, seed: int) -> dict[str, Any]:
    memo_sections = []
    for section in paper["sections"]:
        memo_questions = []
        for question in section["questions"]:
            system_prompt, user_prompt = _build_memo_prompt(question)
            task = {"kind": "generate_memo_for_question", "question": question, "seed": seed}
            raw = call_provider_with_retry(provider, system_prompt, user_prompt, task)
            memo_question = extract_json(raw)
            _validate_memo_marks(memo_question, question)
            memo_questions.append(memo_question)
        memo_sections.append({"id": section["id"], "questions": memo_questions})

    memo = {
        "memo_id": paper["paper_id"].replace("mock-eisa-", "mock-eisa-memo-"),
        "paper_id": paper["paper_id"],
        "status_disclaimer": paper["status_disclaimer"],
        "total_marks": paper["total_marks"],
        "sections": memo_sections,
        "generation_meta": {
            "provider": provider.name,
            "seed": seed,
        },
    }
    return memo


def write_memo(memo: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(memo, indent=2), encoding="utf-8")
