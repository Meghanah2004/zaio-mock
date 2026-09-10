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

REWORK (Phase 1 evaluator feedback): generation is now GROUNDED. Each
section's question is generated against real, page-cited learner-guide
passages (``evidence``, retrieved by src/retrieval/evidence_selector.py and
passed in via ``evidence_by_section``) instead of just a topic name -
_build_question_prompt below now embeds those passages, and every generated
question is checked, before being accepted, against that SAME evidence
(grounding - too little overlap means invention, too much means copying)
and against every previous paper's question for the same section
(cross-paper novelty, via ``generation_history`` - keeps Paper 2/3 genuinely
different from Paper 1). Both checks are OPT IN via their parameters
defaulting to ``None``/empty: this is the TEST MODE vs REAL GENERATION MODE
split the project requires (see docs/DESIGN.md) - unit tests that don't
pass evidence/history exercise the unchanged structural pipeline (marks,
outcomes, schema) without needing a retrieval fixture or a history file;
src/cli.py's real ``generate`` command always supplies both.

REWORK (real Groq convergence failure): a real Paper 2 attempt exhausted
all 3 retries for one section, every attempt rejected for the SAME reason:
too similar to Paper 1's question for that section. Root cause: the retry
note on a cross-paper novelty rejection carried only the numeric similarity
score and the prior paper's id ("question is 0.659 similar to a question
already used in paper 'paper-01'...") - no information about WHAT was
similar, so the model had nothing concrete to change and its retries kept
landing on the same scenario/domain. Fixed by _derive_novelty_avoidance_
brief + _build_retry_note: a novelty-specific rejection now also carries a
compact, structured summary of the REJECTED CANDIDATE's own scenario,
task framing, and sub-task shape, with an explicit instruction to change
the domain/entities (and task structure where sensible) while keeping the
same required outcomes and evidence. Grounding and marks/outcome
rejections are unaffected - they already name the specific numeric/
structural problem directly. Nothing about the novelty THRESHOLD, the
retry BOUND, or what counts as a rejection changed - only what the model
is told about a rejection it already received.
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
from src.retrieval.text_similarity import cosine_similarity
from src.security.config import SecurityConfig
from src.validation.cross_paper_novelty import max_similarity_to_history

MAX_EVIDENCE_BLOCK_ITEMS = 12
"""Defense-in-depth cap on how many evidence items _build_question_prompt
will ever interpolate into a single prompt, independent of whatever
security_config.evidence_passages_per_section is configured to - keeps a
misconfigured/oversized evidence_by_section from producing an unbounded
prompt (see src/security/config.py, same discipline as
max_reference_derived_text_length)."""


def _build_question_marks_budget(section: dict[str, Any]) -> str:
    """Renders the section's exact, individually-checkable mark target as
    plain text, computed directly from the blueprint's OWN already-final,
    non-negotiable marks field - never left for the model to notice amid
    everything else in the prompt. Mirrors
    src.generation.memo_generator._build_marks_budget, which fixed the
    same class of defect (a model losing track of an exact number buried
    in a large prompt) for memo criteria - see that function's docstring
    and docs/DESIGN_NOTE.md for the shared root cause.
    """
    marks = section["marks"]
    return (
        f"- This question is worth exactly {marks} mark(s) in total.\n"
        f"- If you write sub_questions, their \"marks\" values MUST sum to EXACTLY {marks} - "
        f"no more, no less. Recount before responding.\n"
        f"- If you do NOT write sub_questions, this question is still worth exactly {marks} "
        f"marks - that is fixed by the blueprint, not something you declare in your response."
    )


def _build_question_prompt(
    section: dict[str, Any], evidence: list[dict[str, Any]], retry_note: str = ""
) -> tuple[str, str]:
    template = load_prompt_template("generate_questions.txt")
    system_part, _, user_part = template.partition("USER (templated at call time):")
    system_prompt = system_part.replace("SYSTEM:", "", 1).strip()
    outcome_lines = "; ".join(f"{code} ({title})" for code, title in zip(section["outcomes"], section["competencies"]))

    if evidence:
        evidence_lines = "\n".join(
            f"[{i}] {e['document']}, page {e['page']}: \"{e['passage']}\""
            for i, e in enumerate(evidence[:MAX_EVIDENCE_BLOCK_ITEMS], start=1)
        )
    else:
        evidence_lines = "(no learner-guide evidence was retrieved for this section's topics)"

    user_prompt = (
        user_part.replace("{section_title}", section["title"])
        .replace("{occupational_context}", section["occupational_context"])
        .replace("{marks_budget}", _build_question_marks_budget(section))
        .replace("{difficulty}", section["difficulty"])
        .replace("{question_types}", ", ".join(section["question_types"]))
        .replace("{competencies}", "; ".join(section["competencies"]))
        .replace("{outcome_codes}", outcome_lines)
        .replace("{required_outcome_codes}", ", ".join(section.get("required_outcomes", section["outcomes"])))
        .replace("{guide_evidence}", evidence_lines)
        .strip()
    )
    if retry_note:
        user_prompt = f"{user_prompt}\n\n{retry_note}"
    return system_prompt, user_prompt


def _grounding_overlap_ok(question: dict[str, Any], evidence: list[dict[str, Any]], security_config: SecurityConfig) -> str | None:
    """Returns None if grounding is acceptable, else a human-readable reason
    it was rejected. See src/validation/grounding_validator.py for the
    independent re-check of this same judgement against the finished paper."""
    if not evidence:
        return None  # caller decides whether empty evidence itself is fatal
    text_parts = [question.get("scenario") or "", question["question"]]
    text_parts.extend(sq.get("prompt", "") for sq in question.get("sub_questions", []) or [])
    question_text = " ".join(text_parts)
    evidence_text = " ".join(e["passage"] for e in evidence)

    overlap = cosine_similarity(question_text, evidence_text)
    if overlap < security_config.grounding_min_overlap:
        return f"question text has only {overlap:.3f} similarity to its supplied evidence (minimum {security_config.grounding_min_overlap}) - reads as invented rather than evidence-derived"

    max_single = max((cosine_similarity(question_text, e["passage"]) for e in evidence), default=0.0)
    if max_single > security_config.grounding_max_overlap:
        return f"question text has {max_single:.3f} similarity to a single cited passage (maximum {security_config.grounding_max_overlap}) - reads as copied rather than transformed"

    return None


_NOVELTY_BRIEF_FIELD_MAX_CHARS = 180
"""Bounds each field of a novelty-avoidance brief (see
_derive_novelty_avoidance_brief) - a compact summary, deliberately not a
copy of the whole rejected question. Independent of, and much smaller
than, max_reference_derived_text_length/max_evidence_passage_chars, which
bound reference-derived text - this bounds MODEL-GENERATED text being fed
back to the same model, a different trust boundary, so it gets its own
constant rather than reusing one of those."""


def _truncate_for_brief(text: str, max_chars: int = _NOVELTY_BRIEF_FIELD_MAX_CHARS) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."


def _derive_novelty_avoidance_brief(candidate: dict[str, Any]) -> str:
    """Builds a compact, structured summary of a REJECTED candidate's
    scenario/domain and task structure, to tell the next attempt exactly
    what pattern to avoid repeating - see generate_paper's module docstring
    for the real failure this fixes: three consecutive real Groq attempts
    for one section all converged on the same "reservation with a
    waitlist" domain, because the only feedback the retry loop gave was a
    bare numeric similarity score ("question is 0.659 similar to a
    question already used in paper 'paper-01'..."). A number alone gives
    the model nothing to actually change; this gives it the specific
    scenario/domain, task framing, and sub-task shape it just used, so it
    has a concrete pattern to diverge from.

    Deliberately built from the REJECTED CANDIDATE itself (what the model
    JUST wrote and had rejected), never from the matched PRIOR PAPER's
    content: the candidate's own text is exactly what triggered the
    similarity in the first place (by construction, near-identical to
    whatever it collided with), so summarizing it is sufficient - and it
    avoids ever exposing one paper's actual content into another paper's
    generation prompt, keeping every paper's generation self-contained
    (papers interact only via similarity SCORES through
    src.validation.cross_paper_novelty, never via raw text).

    Deliberately generic: works from whatever fields are present on
    whatever candidate was rejected, for whatever section - nothing here
    names a section, topic, or scenario. Deliberately compact: this is a
    handful of truncated sentences, never the full question (marks,
    outcomes, and full sub-question text are never included) - see
    requirement "do not copy the entire previous question into the prompt"
    in docs/DESIGN_NOTE.md.
    """
    lines: list[str] = []

    scenario = (candidate.get("scenario") or "").strip()
    if scenario:
        lines.append(
            f'- Scenario/domain used (choose a DIFFERENT organisation, domain, and entities): "{_truncate_for_brief(scenario)}"'
        )

    question_stem = (candidate.get("question") or "").strip()
    if question_stem:
        lines.append(f'- Task framing used (choose a DIFFERENT framing): "{_truncate_for_brief(question_stem)}"')

    sub_questions = candidate.get("sub_questions") or []
    if sub_questions:
        task_shape = "; ".join(_truncate_for_brief(sq.get("prompt", ""), 60) for sq in sub_questions[:4] if sq.get("prompt"))
        if task_shape:
            lines.append(
                f"- Sub-task structure used (vary this sequence of tasks/actions where sensible): {task_shape}"
            )

    return "\n".join(lines)


def _build_retry_note(
    attempt: int,
    max_attempts: int,
    last_rejection_reason: str | None,
    last_novelty_brief: str | None,
) -> str:
    """Builds the note appended to the next attempt's prompt. When the
    previous rejection was a cross-paper novelty collision,
    ``last_novelty_brief`` (see _derive_novelty_avoidance_brief) turns a
    bare similarity score into structured, actionable feedback about WHAT
    to change; other rejection reasons (grounding, marks/outcome defects
    from _normalize_question) keep the plain generic instruction, since
    those already name the specific numeric/structural problem directly.
    """
    if not last_rejection_reason:
        return ""
    note = (
        f"REGENERATION NOTE (attempt {attempt}/{max_attempts}): your previous attempt was "
        f"rejected - {last_rejection_reason}."
    )
    if last_novelty_brief:
        note += (
            "\n\nNOVELTY AVOIDANCE BRIEF (derived from your own rejected attempt - do not repeat "
            "this pattern):\n"
            f"{last_novelty_brief}\n"
            "Write a genuinely different question now: a different scenario, domain, and entities, "
            "and - where the task type allows it - a different task structure, not merely different "
            "wording of the same idea. Keep covering the same required outcomes using the SAME "
            "GUIDE_EVIDENCE below - only the workplace framing needs to change."
        )
    else:
        note += " Write a genuinely different question."
    return note


def _resolve_expected_response_type(
    raw_content: dict[str, Any], sub_questions: list[dict[str, Any]], qid: str
) -> str:
    """Returns the question's top-level ``expected_response_type``, deriving
    it deterministically from ``sub_questions`` when the provider omitted it
    at the top level - never inventing new content, never bypassing the
    schema/validator requirement that this field always be present on the
    final question object (schemas/paper.schema.json still requires it
    unconditionally; this only changes what the PROVIDER is trusted to
    supply directly).

    Root cause this exists for: prompts/generate_questions.txt's own
    example JSON documents this field as "<overall response type IF NO
    sub_questions>" - i.e. it explicitly tells the model the field is
    conditional. A strict instruction-following model that DOES include
    sub_questions (each already carrying its own expected_response_type)
    can reasonably conclude the top-level field is then redundant and omit
    it - which is exactly what happened with a real Gemini call for a
    design_task question (Section C, which always has 2 sub_questions).
    This was previously masked because MockProvider's Python code always
    supplies the top-level field unconditionally regardless of
    sub_questions, so the prompt's own conditional wording was never
    actually exercised against a real model before. Fixed on two sides:
    prompts/generate_questions.txt now states the field is required
    unconditionally (removing the ambiguity for future calls), and this
    function makes the pipeline itself tolerant of a model that still
    follows the old (or a differently-phrased) interpretation, by deriving
    a real value from the sub-questions' own declared types instead of
    failing outright.
    """
    top_level = raw_content.get("expected_response_type")
    if top_level:
        return top_level

    if sub_questions:
        # Dedup while preserving order - several sub-questions commonly
        # share the same type (e.g. two "structured_uml_description" parts).
        sub_types: list[str] = []
        for sq in sub_questions:
            sub_type = sq.get("expected_response_type")
            if sub_type and sub_type not in sub_types:
                sub_types.append(sub_type)
        return "; ".join(sub_types) if sub_types else "see sub_questions"

    raise GenerationError(
        f"{qid}: provider output missing 'expected_response_type' and no sub_questions were provided "
        f"to derive it from - the question has no way to state its expected answer format."
    )


def _normalize_question(
    raw_content: dict[str, Any],
    section: dict[str, Any],
    question_number: str,
    qid: str,
    grounding: list[dict[str, Any]],
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
        "expected_response_type": _resolve_expected_response_type(raw_content, sub_questions, qid),
        "grounding": [
            {"document": e["document"], "page": e["page"], "passage": e["passage"], "reason": e["reason"]}
            for e in grounding
        ],
    }
    if sub_questions:
        question["sub_questions"] = sub_questions
    return question


def generate_paper(
    blueprint: dict[str, Any],
    provider: LLMProvider,
    seed: int,
    evidence_by_section: dict[str, list[dict[str, Any]]] | None = None,
    generation_history: dict[str, list[dict[str, Any]]] | None = None,
    security_config: SecurityConfig | None = None,
) -> dict[str, Any]:
    """Generate one question per blueprint section.

    ``evidence_by_section`` and ``generation_history`` are the REAL
    GENERATION MODE inputs (see module docstring): when both are supplied,
    every question is generated against real learner-guide evidence and
    checked for grounding AND cross-paper novelty before being accepted,
    retrying up to ``security_config.grounding_max_retries`` times with a
    resampled evidence rotation before failing loudly. When either is
    omitted (the TEST MODE default), the corresponding check is skipped
    entirely and behaviour is identical to before this rework - existing
    tests that construct a paper purely to exercise schema/marks/coverage
    checks are unaffected.
    """
    security_config = security_config or SecurityConfig()
    evidence_by_section = evidence_by_section or {}
    sections_out = []

    for section in blueprint["sections"]:
        evidence = evidence_by_section.get(section["id"], [])
        if section["id"] in evidence_by_section and not evidence:
            # Real generation mode was requested (an evidence map was
            # supplied) but retrieval found nothing for this section's
            # required outcomes - a corpus gap, not something to paper
            # over by generating an ungrounded question anyway.
            raise GenerationError(
                f"Section {section['id']}: no learner-guide evidence could be retrieved for its "
                f"required outcomes {section.get('required_outcomes', section['outcomes'])} - "
                f"refusing to generate an ungrounded question. Check artifacts/reference-corpus-chunks.json."
            )

        max_attempts = security_config.grounding_max_retries if (evidence or generation_history is not None) else 1
        last_rejection_reason: str | None = None
        last_novelty_brief: str | None = None
        question: dict[str, Any] | None = None

        for attempt in range(1, max_attempts + 1):
            retry_note = _build_retry_note(attempt, max_attempts, last_rejection_reason, last_novelty_brief)
            system_prompt, user_prompt = _build_question_prompt(section, evidence, retry_note)
            task = {
                "kind": "generate_section_question",
                "section": section,
                "seed": seed + attempt - 1,
                "evidence": evidence,
            }
            raw = call_provider_with_retry(provider, system_prompt, user_prompt, task)
            content = extract_json(raw)

            # NOTE: 'expected_response_type' is deliberately NOT required
            # here unconditionally - it is still always required on the
            # FINAL question object (schemas/paper.schema.json's "required"
            # list is unchanged), but _normalize_question resolves it via
            # _resolve_expected_response_type, which derives it from
            # sub_questions when the provider omits it at the top level
            # (see that function's docstring for why this is necessary and
            # why it is not a validation weakening).
            required = {"type", "question"}
            missing = required - content.keys()
            if missing:
                raise GenerationError(f"Section {section['id']}: provider output missing fields: {missing}")

            qnum = section_question_number(section["id"], 1)
            qid = question_id(section["id"], 1)
            try:
                candidate = _normalize_question(content, section, qnum, qid, evidence)
            except GenerationError as exc:
                # Marks/outcome-declaration defects (e.g. sub-question marks
                # not summing to the section's target - a real Groq failure:
                # "Q-D1: generated marks (25) do not equal section 'D'
                # target marks (20)") are retry-eligible, same as
                # grounding/novelty rejections below - the model gets
                # another attempt with a note naming exactly what was
                # wrong, rather than aborting the whole paper on one bad
                # roll. _normalize_question's checks themselves are
                # unchanged and still run in full on every attempt; no
                # marks/outcome value is ever accepted without passing them.
                last_rejection_reason = str(exc)
                last_novelty_brief = None
                continue

            rejection = _grounding_overlap_ok(candidate, evidence, security_config)
            is_novelty_rejection = False
            if rejection is None and generation_history is not None:
                candidate_text = " ".join(
                    filter(
                        None,
                        [candidate.get("scenario") or "", candidate["question"]]
                        + [sq.get("prompt", "") for sq in candidate.get("sub_questions", []) or []],
                    )
                )
                similarity, prior_paper = max_similarity_to_history(candidate_text, section["id"], generation_history)
                if similarity > security_config.cross_paper_max_similarity:
                    rejection = (
                        f"question is {similarity:.3f} similar to a question already used in paper "
                        f"{prior_paper!r} for this section (maximum {security_config.cross_paper_max_similarity})"
                    )
                    is_novelty_rejection = True

            if rejection is None:
                question = candidate
                break
            last_rejection_reason = rejection
            # Only a cross-paper novelty rejection carries a brief forward -
            # see _derive_novelty_avoidance_brief. A grounding or
            # marks/outcome rejection already names the specific numeric/
            # structural problem directly and doesn't need one.
            last_novelty_brief = _derive_novelty_avoidance_brief(candidate) if is_novelty_rejection else None

        if question is None:
            raise GenerationError(
                f"Section {section['id']}: exhausted {max_attempts} generation attempt(s), all rejected. "
                f"Last reason: {last_rejection_reason}"
            )

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
            "grounded": bool(evidence_by_section),
        },
    }
    return paper


def write_paper(paper: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(paper, indent=2), encoding="utf-8")
