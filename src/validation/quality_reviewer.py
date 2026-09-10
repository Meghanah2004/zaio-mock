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
import re
from typing import Any

from src.generation.llm_utils import (
    call_provider_with_retry,
    extract_json,
    load_prompt_template,
)
from src.providers.base import LLMProvider

_REVIEW_SECTION_GROUP_SIZE = 2
"""Sections per quality-review LLM call. REWORK (production incident,
2026-09-10): the prior single whole-paper call was proven to exceed Groq's
8000 TPM ceiling unconditionally (~11,435 tokens, a single request that can
never succeed regardless of retries - Requested alone > Limit). Splitting
into grouped calls, each covering only a few sections, keeps every
individual request comfortably under the ceiling (largest real-measured
group, for the current 6-section config: ~5,590 tokens, ~70% of budget).

Grouped POSITIONALLY (in blueprint order), never by hardcoded section-ID
literals ("A", "B", ...): this project's architecture is qualification/N-
agnostic elsewhere (cross-paper novelty, evidence retrieval), and only one
qualification config exists today (software_developer, sections A-F) - for
that config this produces exactly (A,B), (C,D), (E,F), but the same code
stays correct if a future qualification has a different section count or
naming, without needing a change here."""

_REVIEW_GROUNDING_MAX_PASSAGES_PER_QUESTION = 2
_REVIEW_GROUNDING_PASSAGE_MAX_CHARS = 300
"""Bounds on how much question-side grounding evidence is RE-embedded in the
quality-review prompt specifically (see _compact_paper_for_review below) -
independent of, and much smaller than, security_config.
evidence_passages_per_section/max_evidence_passage_chars, which govern the
evidence actually used to GENERATE the question (unaffected by this).

REWORK (production incident, 2026-09-10): a real Groq 429
("rate_limit_exceeded", TPM limit 8000) traced back to this call's prompt -
serializing the ENTIRE paper + ENTIRE memo verbatim, including every
question's full grounding array (up to evidence_passages_per_section=4
passages x max_evidence_passage_chars=900 chars each) AND every memo
entry's full answer-grounding array of the same shape - measured at
~15,800-17,900 tokens combined for a representative paper+memo, over double
the entire per-minute budget in a single request, on top of the ~30,000-
42,000 tokens the paper's other 12 real generation/memo calls already need
in the same window. review.txt's guide_grounding/reads_as_copied criteria
genuinely need to SEE some of each question's grounding text to judge it -
this is not removed, only capped to a small, still-representative sample
(2 passages, 300 chars each) instead of the full retrieval set repeated
verbatim. The memo's OWN grounding/citation array is dropped entirely from
this prompt: no review.txt criterion inspects it (answer-side grounding
correctness is already independently, deterministically re-checked by
src.validation.answer_grounding_validator, which never calls an LLM), so
resending it here is pure duplication with no corresponding review value."""


def _compact_grounding_for_review(grounding: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for entry in (grounding or [])[:_REVIEW_GROUNDING_MAX_PASSAGES_PER_QUESTION]:
        passage = entry.get("passage", "")
        if len(passage) > _REVIEW_GROUNDING_PASSAGE_MAX_CHARS:
            passage = passage[:_REVIEW_GROUNDING_PASSAGE_MAX_CHARS].rsplit(" ", 1)[0] + "..."
        compact.append({"document": entry.get("document"), "page": entry.get("page"), "passage": passage})
    return compact


def _compact_paper_for_review(paper: dict[str, Any], sections: list[dict[str, Any]]) -> dict[str, Any]:
    """Builds the paper representation sent to the quality-review LLM ONLY -
    the real, full ``paper`` (with every question's complete grounding
    array) is untouched and is what actually gets written to
    artifacts/blueprint-adjacent output, validated by the deterministic
    grounding validator, and returned to the API/frontend. This function's
    output is never persisted or returned - see run_quality_review below.

    ``sections`` is the GROUP subset being reviewed in THIS call (see
    _REVIEW_SECTION_GROUP_SIZE) - not necessarily every section in
    ``paper``. Paper-level fields (qualification, nqf_level, total_marks)
    are still taken from the full ``paper`` and included in every group's
    payload, since difficulty_appropriate needs the qualification's NQF
    Level regardless of which sections are in this particular group."""
    return {
        "paper_id": paper["paper_id"],
        "qualification": paper["qualification"],
        "nqf_level": paper["nqf_level"],
        "total_marks": paper["total_marks"],
        "sections": [
            {
                "id": section["id"],
                "title": section["title"],
                "marks": section["marks"],
                "difficulty": section["difficulty"],
                "questions": [
                    {
                        "id": question["id"],
                        "type": question.get("type"),
                        "scenario": question.get("scenario"),
                        "question": question.get("question"),
                        "marks": question.get("marks"),
                        "outcomes": question.get("outcomes"),
                        "expected_response_type": question.get("expected_response_type"),
                        "sub_questions": question.get("sub_questions"),
                        "grounding": _compact_grounding_for_review(question.get("grounding")),
                    }
                    for question in section["questions"]
                ],
            }
            for section in sections
        ],
    }


def _compact_memo_for_review(memo: dict[str, Any], sections: list[dict[str, Any]]) -> dict[str, Any]:
    """Same purpose as _compact_paper_for_review, for the memo side: drops
    only the per-question ``grounding`` (citation) array - unused by any
    review.txt criterion (answer grounding is independently, deterministically
    re-checked elsewhere - see the module-level constants' docstring above).
    Every field a reviewer actually needs to judge markability/technical_
    correctness/consistency (model_answer, criteria, accepted_alternatives,
    partial_credit_guidance, penalties, sub_questions) is preserved exactly.

    ``sections`` is the memo-side GROUP subset matching the paper-side group
    passed to _compact_paper_for_review for the same call - see
    run_quality_review."""
    return {
        "memo_id": memo["memo_id"],
        "paper_id": memo["paper_id"],
        "total_marks": memo["total_marks"],
        "sections": [
            {
                "id": section["id"],
                "questions": [
                    {key: value for key, value in question.items() if key != "grounding"}
                    for question in section["questions"]
                ],
            }
            for section in sections
        ],
    }


def _chunk_sections(sections: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    """Splits ``sections`` (already in blueprint order) into consecutive,
    fixed-size groups - the last group holds the remainder if the count
    isn't evenly divisible. Purely positional; never inspects section id/
    content, so it stays correct for any qualification's section count."""
    return [sections[i : i + size] for i in range(0, len(sections), size)]


_OFFICIAL_STATUS_NEGATION_WORDS = ("not ", "n't", "never", "mock", "practice", "simulat", "mimic")
"""If any of these appear in a candidate match's own span, it is NOT flagged
- covers this pipeline's own honest disclaimer wording ("MOCK / PRACTICE
ASSESSMENT ONLY", "this paper is not an official...", "simulates the
official EISA format") so the check never fires on the project's own
correct, required disclaimers."""

_OFFICIAL_STATUS_PROVENANCE_PHRASES = ("based on", "derived from", "adapted from")
"""If any of these appear in a candidate match's own span, it is NOT flagged
- distinguishes (A) a claim that the generated paper/question/assessment
ITSELF is official ("this paper IS an official QCTO instrument" - flagged)
from (B) a true, ordinary statement that SOURCE MATERIAL is official ("this
paper IS BASED ON an official QCTO scenario" - not flagged, this is exactly
the kind of honest provenance statement a correctly-grounded question
should be able to make). REWORK (final diff review finding, 2026-09-10): a
real false positive - "This examination question is based on an official
QCTO scenario ... adapted for this assessment." - was caught by manual
review of the shipped v1 of this check; this phrase list closes it without
weakening detection of an actual self-status claim (see the regex's own
docstring for why the two are structurally distinguishable, and
test_quality_reviewer_compact_payload.py for both directions verified with
real examples, not just the one that was found)."""

_OFFICIAL_STATUS_CLAIM_RE = re.compile(
    r"\bthis(?:\s+(?:paper|assessment|document|instrument|exam|examination))?\s+"
    r"(?:is|constitutes|represents|serves\s+as)\b"
    r"[^.]{0,30}?\b(?:an?\s+)?(?:official|authentic|genuine|legitimate|accredited)\b"
    r"[^.]{0,40}?\b(?:QCTO|EISA)\b",
    re.IGNORECASE,
)
"""Deterministic replacement for review.txt's former
``inappropriate_claims_of_official_status`` LLM criterion (production
token-budget fix, 2026-09-10) - this is the ONE review.txt criterion that
is a clean pattern match rather than a genuine judgment call, so it is
moved out of the LLM prompt entirely; the other 9 criteria all require real
semantic judgment and are NOT touched.

CONSERVATIVE BY DESIGN: requires an explicit SELF-REFERENTIAL subject -
either bare "this" (a pronoun standing for the paper/question/assessment
itself, e.g. "this IS an official QCTO EISA instrument") or "this" plus
one of six specific nouns immediately before the verb (e.g. "this PAPER
is..."), with NOTHING else permitted in between - never a random noun
("this concept is officially QCTO...") and never a noun separated from the
verb by extra words ("this examination QUESTION is..." - the extra word
"question" between the recognized noun and the verb means the SUBJECT
itself is "question", not "this examination", so it correctly does not
match; see the false-positive fix this specific shape closes, in
_OFFICIAL_STATUS_PROVENANCE_PHRASES's docstring). Followed by
"is/constitutes/represents/serves as", then "official/authentic/genuine/
legitimate/accredited", then "QCTO"/"EISA", all within one sentence
(bounded by the ``[^.]`` gaps) - never fires merely because "QCTO", "EISA",
"assessment", or "official" appear independently in normal contextual text
(e.g. "in line with QCTO's official curriculum", "the official QCTO
learner guide explains...", "this mock paper follows the EISA format" -
none of these match). A matched span containing a negation/disclaimer word
(_OFFICIAL_STATUS_NEGATION_WORDS) or a provenance phrase
(_OFFICIAL_STATUS_PROVENANCE_PHRASES) is discarded, not flagged.

REWORK (final diff review finding, 2026-09-10): the original version of
this regex required the noun to appear (never bare "this"), which missed
the single most natural phrasing of this exact violation - "This IS an
official QCTO EISA instrument." (no noun between "this" and "is"). Fixed
by making the noun optional while keeping it restricted to the same six
specific words when present - this closes the false negative without
loosening what counts as "this" referring to the paper (a random noun like
"this concept/topic/fact is officially QCTO..." still correctly does not
match, since only those six specific nouns are recognized as standing for
the paper/assessment itself).

Real trade-off, stated plainly: a regex has near-perfect PRECISION
(whatever it flags is a genuine hit) but lower RECALL than an LLM's
semantic judgment for a phrasing neither this pattern nor the exclusion
lists anticipated. That trade-off is accepted here only for this one
narrow, mechanically-detectable criterion - not proposed for any of the
other 9."""


def _reviewable_text_by_question_id(paper: dict[str, Any], memo: dict[str, Any]) -> dict[str, str]:
    """Maps question_id -> the combined question+memo text to scan for an
    official-status claim - scenario/question/sub-question prompts (paper
    side) plus model answers/criteria descriptions (memo side), the same
    surfaces a human or the LLM reviewer would actually read."""
    memo_questions_by_id = {
        question["question_id"]: question for section in memo["sections"] for question in section["questions"]
    }
    texts: dict[str, str] = {}
    for section in paper["sections"]:
        for question in section["questions"]:
            parts = [question.get("scenario") or "", question.get("question") or ""]
            parts.extend(sq.get("prompt", "") for sq in question.get("sub_questions", []) or [])

            memo_question = memo_questions_by_id.get(question["id"])
            if memo_question:
                parts.append(memo_question.get("model_answer") or "")
                parts.extend(c.get("description", "") for c in memo_question.get("criteria", []) or [])
                for sub in memo_question.get("sub_questions", []) or []:
                    parts.append(sub.get("model_answer") or "")
                    parts.extend(c.get("description", "") for c in sub.get("criteria", []) or [])

            texts[question["id"]] = " ".join(parts)
    return texts


def _text_makes_an_official_status_claim(text: str) -> bool:
    for match in _OFFICIAL_STATUS_CLAIM_RE.finditer(text):
        span = match.group(0).lower()
        if any(negation in span for negation in _OFFICIAL_STATUS_NEGATION_WORDS):
            continue
        if any(phrase in span for phrase in _OFFICIAL_STATUS_PROVENANCE_PHRASES):
            continue
        return True
    return False


def _check_official_status_claims(paper: dict[str, Any], memo: dict[str, Any]) -> list[str]:
    """Deterministic, zero-token, zero-LLM-call replacement for review.txt's
    former inappropriate_claims_of_official_status criterion - runs once per
    run_quality_review call (not per section group) since it is pure local
    text scanning, no retrieval or generation involved."""
    issues: list[str] = []
    for question_id, text in _reviewable_text_by_question_id(paper, memo).items():
        if _text_makes_an_official_status_claim(text):
            issues.append(
                f"{question_id}: text appears to claim this is an official/authentic QCTO or EISA "
                f"assessment instrument rather than a mock/practice paper (deterministic check)."
            )
    return issues


def run_quality_review(paper: dict[str, Any], memo: dict[str, Any], provider: LLMProvider) -> dict[str, Any]:
    """Runs the LLM quality review in SECTION GROUPS (see
    _REVIEW_SECTION_GROUP_SIZE) instead of one whole-paper call - production
    token-budget fix, 2026-09-10 (see that constant's docstring for the
    full incident). Every group's ``approved``/``issues``/``question_reviews``
    are aggregated into the SAME return shape run_quality_review has always
    had, so callers (api/service.py) need no changes.

    A failure in any group (a raised LLMProviderError/GenerationError from
    call_provider_with_retry/extract_json) propagates out of this function
    immediately, exactly like every other stage in this pipeline - there is
    no try/except here, so a mid-loop failure can never be silently
    swallowed into a false "approved" result; whatever groups already
    succeeded are simply never returned, matching this codebase's existing
    "let failures propagate, never persist partial state" convention (see
    api/service.py's own docstring and tests/test_generation_history_
    resilience.py for the same property elsewhere in the pipeline).
    """
    template = load_prompt_template("review.txt")
    system_part, _, user_part = template.partition("USER (templated at call time):")
    system_prompt = system_part.replace("SYSTEM:", "", 1).strip()

    memo_sections_by_id = {section["id"]: section for section in memo["sections"]}
    section_groups = _chunk_sections(paper["sections"], _REVIEW_SECTION_GROUP_SIZE)

    approved = True
    issues: list[str] = []
    question_reviews: list[dict[str, Any]] = []

    for group in section_groups:
        group_section_ids = [section["id"] for section in group]
        group_memo_sections = [memo_sections_by_id[section_id] for section_id in group_section_ids]

        review_paper = _compact_paper_for_review(paper, group)
        review_memo = _compact_memo_for_review(memo, group_memo_sections)
        user_prompt = (
            user_part.replace("{paper_json}", json.dumps(review_paper))
            .replace("{memo_json}", json.dumps(review_memo))
            .strip()
        )
        # task carries the REAL, full paper/memo (MockProvider-only, see
        # src/providers/base.py's module docstring - never sent to a real
        # provider) plus section_ids so MockProvider's own quality-review
        # fixture (src/providers/mock_provider.py) scopes its response to
        # THIS group only - without that, calling the provider 3x would
        # triple-count every question's review entry in MockProvider-backed
        # tests, since MockProvider would otherwise read the full paper
        # every time regardless of which group is being asked about.
        task = {"kind": "quality_review", "paper": paper, "memo": memo, "section_ids": group_section_ids}
        raw = call_provider_with_retry(provider, system_prompt, user_prompt, task)
        group_review = extract_json(raw)

        approved = approved and bool(group_review.get("approved", False))
        issues.extend(group_review.get("issues") or [])
        question_reviews.extend(group_review.get("question_reviews") or [])

    official_status_issues = _check_official_status_claims(paper, memo)
    if official_status_issues:
        approved = False
        issues.extend(official_status_issues)

    return {"approved": approved, "issues": issues, "question_reviews": question_reviews}
