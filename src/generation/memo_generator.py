"""Generates the complete marking memo corresponding to a finalized paper.

One provider call per question (never a bulk "write the whole memo" call) so
each question's marking guidance is grounded in that exact question's final,
already-mark-checked content - this is the "small, specialized prompts over
one giant prompt" principle from docs/DESIGN.md.

REWORK (real Groq generation failure): a real memo-generation call returned
a sub-question whose "criteria" marks summed to 5 instead of the 4 the
sub-question was actually worth - a free-text-arithmetic slip, not a
structural defect (see _validate_memo_marks, unchanged and still exactly as
strict). Root cause: the prompt only ever embedded the question's full JSON
verbatim and stated the marks-must-reconcile requirement as a single
whole-question constraint; a model composing several paragraphs of model
answer/criteria text per part can lose track of one specific part's target
number buried inside a large JSON blob. Fixed on two sides, mirroring the
grounding/novelty retry pattern already used in
src/generation/question_generator.py: (1) _build_marks_budget renders each
part's exact mark target as an explicit, individually-checkable line the
prompt puts front and center (prompts/generate_memo.txt), and (2)
generate_memo now retries a REJECTED memo (bounded by
SecurityConfig.memo_max_retries) with a note naming exactly what was wrong,
before failing loudly - never accepting or silently correcting a bad sum.

REWORK (answer-side RAG): question generation was already grounded in real
learner-guide evidence (src/retrieval/evidence_selector.select_evidence,
used before a question exists). The ANSWER side was not: the memo prompt
only ever received the finished question JSON, so a model answer could
freely draw on the model's own general knowledge instead of the supplied
material - the source-of-truth rule was only being enforced for HALF of
what this pipeline produces. Fixed by threading a second, independent
retrieval pass through this module: ``generate_memo`` optionally accepts a
prebuilt retrieval index (built once from artifacts/reference-corpus-
chunks.json, the same file question-side retrieval uses - no second corpus,
no re-parsing PDFs); for each question, src.retrieval.evidence_selector.
select_answer_evidence retrieves real, page-cited passages targeted at
THAT SPECIFIC question's own text (not just its section/topic - see that
function's docstring), which are embedded in the memo prompt and checked
against the generated answer by _answer_grounding_ok before acceptance,
with the same bounded-retry-then-fail-loudly shape as the marks check.
When no retrieval index is supplied (TEST MODE - the existing unit-test
call pattern, and the current API layer, see api/service.py), answer-side
grounding is skipped entirely and behaviour is byte-identical to before
this rework.
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
from src.retrieval.evidence_selector import select_answer_evidence
from src.retrieval.text_similarity import cosine_similarity
from src.security.config import SecurityConfig
from src.validation.novelty_checker import ReferenceCorpusIndex

MAX_ANSWER_EVIDENCE_BLOCK_ITEMS = 12
"""Defense-in-depth cap on how many answer-evidence items
_build_memo_prompt will ever interpolate into a single prompt, mirroring
src.generation.question_generator.MAX_EVIDENCE_BLOCK_ITEMS for the same
reason - keeps a misconfigured/oversized evidence list from producing an
unbounded prompt regardless of what security_config.
evidence_passages_per_section is configured to."""


def _build_marks_budget(question: dict[str, Any]) -> str:
    """Renders the exact, individually-checkable mark target for every part
    of ``question`` as plain text, computed from the question's OWN already
    - final, non-negotiable - marks fields, never left for the model to
    extract correctly from the embedded JSON blob on its own."""
    sub_questions = question.get("sub_questions") or []
    if sub_questions:
        return "\n".join(
            f"- Sub-question {sq['id']}: exactly {sq['marks']} mark(s) - the \"criteria\" list you write "
            f"for sub-question {sq['id']} MUST have \"marks\" values summing to EXACTLY {sq['marks']}, "
            f"no more and no less."
            for sq in sub_questions
        )
    return (
        f"- This question has no sub-parts: exactly {question['marks']} mark(s) - your top-level "
        f"\"criteria\" list's \"marks\" values MUST sum to EXACTLY {question['marks']}."
    )


def _build_answer_evidence_block(answer_evidence: list[dict[str, Any]]) -> str:
    if not answer_evidence:
        return "(no learner-guide evidence was retrieved to support answering this question)"
    return "\n".join(
        f"[{i}] {e['document']}, page {e['page']}: \"{e['passage']}\""
        for i, e in enumerate(answer_evidence[:MAX_ANSWER_EVIDENCE_BLOCK_ITEMS], start=1)
    )


def _question_for_memo_prompt(question: dict[str, Any]) -> dict[str, Any]:
    """Strips the question's own ``grounding`` (citation) array before it is
    echoed into the memo-generation prompt - production-incident fix (real
    Groq 429s, TPM limit 8000): this field is question-provenance metadata,
    already independently checked at generation time
    (src.generation.question_generator._grounding_overlap_ok), and
    prompts/generate_memo.txt never references or instructs the model to
    use it - the model's stated knowledge source for THIS call is the
    separate {answer_evidence} block below, retrieved specifically to
    support answering this question. Re-sending the question's own
    grounding array here was pure duplicate payload with no effect on
    answer quality or grounding: the memo's own final ``grounding`` field
    (see _generate_memo_for_question below) is built from
    ``answer_evidence``, never from this echoed question JSON, so removing
    it here does not touch RAG, answer grounding, or answer-grounding
    validation in any way."""
    return {key: value for key, value in question.items() if key != "grounding"}


def _build_memo_prompt(
    question: dict[str, Any], answer_evidence: list[dict[str, Any]], retry_note: str = ""
) -> tuple[str, str]:
    template = load_prompt_template("generate_memo.txt")
    system_part, _, user_part = template.partition("USER (templated at call time):")
    system_prompt = system_part.replace("SYSTEM:", "", 1).strip()
    user_prompt = (
        user_part.replace("{question_json}", json.dumps(_question_for_memo_prompt(question)))
        .replace("{marks_budget}", _build_marks_budget(question))
        .replace("{answer_evidence}", _build_answer_evidence_block(answer_evidence))
        .strip()
    )
    if retry_note:
        user_prompt = f"{user_prompt}\n\n{retry_note}"
    return system_prompt, user_prompt


def _ensure_top_level_criteria_present(memo_question: dict[str, Any], question: dict[str, Any]) -> None:
    """When ``question`` has sub_questions, schemas/memo.schema.json still
    requires the memo's TOP-LEVEL ``criteria`` array to be non-empty
    (``minItems: 1``) - the real, detailed marking guidance lives in
    ``sub_questions[].criteria`` (checked separately, unaffected by this
    function), so the top-level field here is a purely structural
    summary/pointer, never a second independent marks breakdown. There is
    nothing for a model to judge in this field - it is always exactly one
    entry pointing to the per-part breakdown, with marks equal to the
    question's total - so it is filled in deterministically here rather
    than retried, exactly like
    src.generation.question_generator._resolve_expected_response_type
    derives an omitted top-level ``expected_response_type`` from
    sub_questions. This is the SAME convention every
    src.providers.mock_provider memo builder already hard-codes
    (``[{"description": "See per-part criteria in sub_questions.", "marks":
    question["marks"]}]``) - a real Groq call left this field as ``[]``
    instead, which is what this normalizes, never overwriting a non-empty
    value the provider already supplied.
    """
    if question.get("sub_questions") and not memo_question.get("criteria"):
        memo_question["criteria"] = [
            {"description": "See per-part criteria in sub_questions.", "marks": question["marks"]}
        ]


def _validate_memo_marks(memo_question: dict[str, Any], question: dict[str, Any]) -> None:
    qid = question["id"]
    if memo_question.get("question_id") != qid:
        raise GenerationError(f"Memo question_id mismatch: expected {qid}, got {memo_question.get('question_id')!r}")

    _ensure_top_level_criteria_present(memo_question, question)

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


def _memo_answer_text(memo_question: dict[str, Any]) -> str:
    parts = [memo_question.get("model_answer") or ""]
    parts.extend(sq.get("model_answer", "") for sq in memo_question.get("sub_questions", []) or [])
    return " ".join(parts)


def _memo_criteria_text(memo_question: dict[str, Any]) -> str:
    parts = [c.get("description", "") for c in memo_question.get("criteria", []) or []]
    for sq in memo_question.get("sub_questions", []) or []:
        parts.extend(c.get("description", "") for c in sq.get("criteria", []) or [])
    return " ".join(parts)


def _answer_grounding_ok(
    memo_question: dict[str, Any],
    question: dict[str, Any],
    answer_evidence: list[dict[str, Any]],
    security_config: SecurityConfig,
) -> str | None:
    """Returns None if the generated answer is acceptably grounded, else a
    human-readable reason it was rejected. See
    src/validation/answer_grounding_validator.py for the independent
    re-check of this same judgement against the finished memo.

    Deliberately asymmetric versus question-side grounding
    (src.generation.question_generator._grounding_overlap_ok): there is a
    MINIMUM overlap floor against the cited evidence (an answer must be
    DERIVED from it, not invented), but no MAXIMUM ceiling. A question must
    be an original workplace scenario - closely echoing its source passage
    is a copying defect. A memo's model answer is the opposite: it is
    supposed to state the correct technical facts the guide establishes,
    so closely reflecting what the guide actually says is the goal, not a
    defect. Penalizing high answer/evidence overlap would push the model
    toward LESS accurate, more paraphrased-for-its-own-sake answers - the
    wrong incentive for a marking memo.

    Two additional loose sanity floors, both using the same plain cosine
    metric: the answer must bear SOME relation to the question it claims to
    answer (catches a wildly off-topic answer), and the marking criteria
    must bear SOME relation to the model answer they are supposedly grading
    (catches criteria disconnected from what was actually written).
    """
    if not answer_evidence:
        return None  # caller decides whether empty evidence itself is fatal

    answer_text = _memo_answer_text(memo_question)
    evidence_text = " ".join(e["passage"] for e in answer_evidence)

    overlap = cosine_similarity(answer_text, evidence_text)
    if overlap < security_config.answer_grounding_min_overlap:
        return (
            f"model answer has only {overlap:.3f} similarity to its supplied answer evidence "
            f"(minimum {security_config.answer_grounding_min_overlap}) - reads as drawing on general "
            f"knowledge rather than the supplied learner-guide evidence"
        )

    question_text = " ".join(
        filter(
            None,
            [question.get("scenario") or "", question.get("question", "")]
            + [sq.get("prompt", "") for sq in question.get("sub_questions", []) or []],
        )
    )
    relevance = cosine_similarity(answer_text, question_text)
    if relevance < security_config.answer_relevance_min_overlap:
        return (
            f"model answer has only {relevance:.3f} similarity to the question it claims to answer "
            f"(minimum {security_config.answer_relevance_min_overlap}) - does not appear to actually "
            f"address what was asked"
        )

    criteria_text = _memo_criteria_text(memo_question)
    if criteria_text:
        criteria_groundedness = cosine_similarity(criteria_text, answer_text)
        if criteria_groundedness < security_config.answer_relevance_min_overlap:
            return (
                f"marking criteria have only {criteria_groundedness:.3f} similarity to the model answer "
                f"they are supposedly grading (minimum {security_config.answer_relevance_min_overlap}) - "
                f"criteria do not appear grounded in the actual answer given"
            )

    return None


def _generate_memo_for_question(
    question: dict[str, Any],
    provider: LLMProvider,
    seed: int,
    security_config: SecurityConfig,
    answer_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate and validate one question's memo, retrying a REJECTED
    memo (bounded by ``security_config.memo_max_retries``) with a note
    naming exactly what was wrong before failing loudly. Never accepts,
    silently corrects, or relaxes the marks/answer-grounding checks
    themselves (_validate_memo_marks and _answer_grounding_ok run
    unchanged on every attempt) - a retry only gives the model another
    chance to produce a genuinely correct memo, the same shape as the
    grounding/novelty retry loop in
    src/generation/question_generator.generate_paper.
    """
    qid = question["id"]
    evidence = answer_evidence or []
    max_attempts = max(1, security_config.memo_max_retries)
    last_error: str | None = None

    for attempt in range(1, max_attempts + 1):
        retry_note = (
            f"REGENERATION NOTE (attempt {attempt}/{max_attempts}): your previous attempt was "
            f"rejected - {last_error}. Recount every part's criteria marks against the MARK BUDGET, "
            f"and make sure every substantive claim in your answer is supportable from the "
            f"ANSWER_EVIDENCE, before responding again."
            if last_error
            else ""
        )
        system_prompt, user_prompt = _build_memo_prompt(question, evidence, retry_note)
        task = {"kind": "generate_memo_for_question", "question": question, "seed": seed + attempt - 1, "answer_evidence": evidence}
        raw = call_provider_with_retry(provider, system_prompt, user_prompt, task)
        memo_question = extract_json(raw)
        try:
            _validate_memo_marks(memo_question, question)
        except GenerationError as exc:
            last_error = str(exc)
            continue

        rejection = _answer_grounding_ok(memo_question, question, evidence, security_config)
        if rejection is not None:
            last_error = rejection
            continue

        memo_question["grounding"] = [
            {"document": e["document"], "page": e["page"], "passage": e["passage"], "reason": e["reason"]}
            for e in evidence
        ]
        return memo_question

    raise GenerationError(
        f"{qid}: exhausted {max_attempts} memo generation attempt(s), all rejected. Last reason: {last_error}"
    )


def generate_memo(
    paper: dict[str, Any],
    provider: LLMProvider,
    seed: int,
    security_config: SecurityConfig | None = None,
    retrieval_index: ReferenceCorpusIndex | None = None,
    corpus_chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """``retrieval_index``/``corpus_chunks`` are the REAL ANSWER-RAG MODE
    inputs (see module docstring): when both are supplied, every memo entry
    is generated against real, question-targeted learner-guide evidence
    (src.retrieval.evidence_selector.select_answer_evidence) and checked
    for answer grounding before being accepted. When either is omitted (the
    TEST MODE default), answer grounding is skipped entirely and behaviour
    is identical to before this rework - this is the same TEST MODE vs REAL
    GENERATION MODE split src.generation.question_generator.generate_paper
    already uses for question-side evidence/history.

    Built ONCE by the caller (src/cli.py, api/service.py) and passed in
    rather than rebuilt per question or per section - the corpus is ~6,000
    chunks; parsing/indexing it once and reusing the index across all of a
    paper's ~6 memo calls (plus the question-side calls that already share
    it) is the token/compute-efficiency point, not something this function
    repeats per call.
    """
    security_config = security_config or SecurityConfig()
    answer_grounded = retrieval_index is not None and corpus_chunks is not None
    memo_sections = []

    for section in paper["sections"]:
        memo_questions = []
        for question in section["questions"]:
            answer_evidence: list[dict[str, Any]] | None = None
            if answer_grounded:
                assert retrieval_index is not None and corpus_chunks is not None  # narrows for mypy
                answer_evidence = select_answer_evidence(
                    retrieval_index, corpus_chunks, question, seed, security_config
                )
                if not answer_evidence:
                    raise GenerationError(
                        f"{question['id']}: no learner-guide evidence could be retrieved to support "
                        f"answering this question - refusing to generate an ungrounded answer. "
                        f"Check artifacts/reference-corpus-chunks.json."
                    )
            memo_question = _generate_memo_for_question(
                question, provider, seed, security_config, answer_evidence=answer_evidence
            )
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
            "answer_grounded": answer_grounded,
        },
    }
    return memo


def write_memo(memo: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(memo, indent=2), encoding="utf-8")
