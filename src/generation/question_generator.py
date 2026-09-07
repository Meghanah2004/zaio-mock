"""Generates the full Mock EISA paper from a blueprint.

For each blueprint section, this module asks the configured LLM provider to
author ONE question's content (scenario/question/sub_questions), then
enforces every governance field itself from the blueprint - ids, section_id,
question_number, marks, difficulty. Provider output is never trusted for
those fields, and mark totals are checked immediately so a bad generation
fails loudly here rather than downstream.

Outcome mapping (``outcomes``/``competencies``) is a partial exception: the
provider DOES declare which outcomes its specific question covers (a
required field in its JSON output), but that declaration is not trusted
blindly either. It is validated against the blueprint section's outcome
universe and required_outcomes list before being accepted - see
_normalize_question below and docs/DESIGN.md, "Outcome mapping: explicit
subsets, not section-wide copies." This replaces an earlier version of this
module that copied the ENTIRE section outcome/competency list onto every
question regardless of content, which made outcome-coverage validation
tautological (a section could "pass" coverage purely because the list was
copied, not because the question genuinely tested those outcomes).
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
from src.models.schemas import question_id, section_question_number
from src.providers.base import LLMProvider


def _build_question_prompt(section: dict[str, Any]) -> tuple[str, str]:
    template = load_prompt_template("generate_questions.txt")
    system_part, _, user_part = template.partition("USER (templated at call time):")
    system_prompt = system_part.replace("SYSTEM:", "", 1).strip()
    outcome_lines = "; ".join(f"{code} ({title})" for code, title in zip(section["outcomes"], section["competencies"]))
    user_prompt = (
        user_part.replace("{section_title}", section["title"])
        .replace("{occupational_context}", section["occupational_context"])
        .replace("{marks}", str(section["marks"]))
        .replace("{difficulty}", section["difficulty"])
        .replace("{question_types}", ", ".join(section["question_types"]))
        .replace("{competencies}", "; ".join(section["competencies"]))
        .replace("{outcome_codes}", outcome_lines)
        .replace("{required_outcome_codes}", ", ".join(section.get("required_outcomes", section["outcomes"])))
        .strip()
    )
    return system_prompt, user_prompt


def _normalize_question(
    raw_content: dict[str, Any],
    section: dict[str, Any],
    question_number: str,
    qid: str,
) -> dict[str, Any]:
    sub_questions = raw_content.get("sub_questions") or []
    for i, sq in enumerate(sub_questions, start=1):
        sq.setdefault("id", str(i))

    computed_marks = sum(sq["marks"] for sq in sub_questions) if sub_questions else section["marks"]
    if computed_marks != section["marks"]:
        raise GenerationError(
            f"{qid}: generated marks ({computed_marks}) do not equal section '{section['id']}' "
            f"target marks ({section['marks']})."
        )

    declared_outcomes = raw_content.get("outcomes")
    if not declared_outcomes:
        raise GenerationError(
            f"{qid}: provider did not declare which outcome(s) this question genuinely covers "
            f"(an 'outcomes' field with at least one code is required - the generator no longer "
            f"defaults this to the section's full outcome list)."
        )
    declared_set = set(declared_outcomes)
    full_outcome_set = set(section["outcomes"])
    required_outcome_set = set(section.get("required_outcomes", section["outcomes"]))

    hallucinated = declared_set - full_outcome_set
    if hallucinated:
        raise GenerationError(
            f"{qid}: declared outcomes {sorted(hallucinated)} are not part of section "
            f"'{section['id']}''s outcome universe {sorted(full_outcome_set)}."
        )
    missing_required = required_outcome_set - declared_set
    if missing_required:
        raise GenerationError(
            f"{qid}: question does not cover required outcome(s) {sorted(missing_required)} for "
            f"section '{section['id']}' (required: {sorted(required_outcome_set)})."
        )

    # Preserve blueprint order and dedupe; derive competency titles from the
    # SAME declared subset - never from the section's full competency list.
    outcome_title_map = dict(zip(section["outcomes"], section["competencies"]))
    ordered_outcomes = [code for code in section["outcomes"] if code in declared_set]
    competencies = [outcome_title_map[code] for code in ordered_outcomes]

    question: dict[str, Any] = {
        "id": qid,
        "section_id": section["id"],
        "question_number": question_number,
        "type": raw_content["type"],
        "scenario": raw_content.get("scenario"),
        "question": raw_content["question"],
        "marks": computed_marks,
        "difficulty": section["difficulty"],
        "outcomes": ordered_outcomes,
        "competencies": competencies,
        "expected_response_type": raw_content["expected_response_type"],
    }
    if sub_questions:
        question["sub_questions"] = sub_questions
    return question


def generate_paper(blueprint: dict[str, Any], provider: LLMProvider, seed: int) -> dict[str, Any]:
    sections_out = []
    for section in blueprint["sections"]:
        system_prompt, user_prompt = _build_question_prompt(section)
        task = {"kind": "generate_section_question", "section": section, "seed": seed}
        raw = call_provider_with_retry(provider, system_prompt, user_prompt, task)
        content = extract_json(raw)

        required = {"type", "question", "expected_response_type"}
        missing = required - content.keys()
        if missing:
            raise GenerationError(f"Section {section['id']}: provider output missing fields: {missing}")

        qnum = section_question_number(section["id"], 1)
        qid = question_id(section["id"], 1)
        question = _normalize_question(content, section, qnum, qid)

        sections_out.append(
            {
                "id": section["id"],
                "title": section["title"],
                "marks": section["marks"],
                "outcomes": section["outcomes"],
                "competencies": section["competencies"],
                "difficulty": section["difficulty"],
                "question_types": section["question_types"],
                "questions": [question],
            }
        )

    paper = {
        "paper_id": blueprint["paper_id"],
        "qualification": blueprint["qualification_title"],
        "nqf_level": blueprint["nqf_level"],
        "status_disclaimer": blueprint["status_disclaimer"],
        "duration_minutes": blueprint["duration_minutes"],
        "total_marks": blueprint["total_marks"],
        "instructions": blueprint["instructions"],
        "sections": sections_out,
        "generation_meta": {
            "provider": provider.name,
            "seed": seed,
            "blueprint_paper_id": blueprint["paper_id"],
        },
    }
    return paper


def write_paper(paper: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(paper, indent=2), encoding="utf-8")
