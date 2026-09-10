"""Selects real, page-cited learner-guide passages for a blueprint section.

This is the module that makes generation "learner-guide-grounded" rather
than "topic-name-grounded": instead of handing the LLM a Knowledge Topic
CODE and TITLE (e.g. "KM-06-KT06 (HTML5)") and letting it invent content
from general knowledge, ``select_evidence`` retrieves actual passages of
the supplied Learner Guide text - each carrying its real source document
and page number, never fabricated - for the model to read and transform
into an original workplace question. See docs/DESIGN.md and
prompts/generate_questions.txt's GUIDE_EVIDENCE block.

Retrieval strategy, cheapest-and-most-reliable signal first:
  1. STRUCTURAL: every chunk from ``src.analysis.reference_analyzer.
     extract_corpus_chunks`` is tagged with the Knowledge Topic code that
     was actually in force on its page (from the corpus's own
     "SECTION N: KM-xx-KTyy: <title> <weight>%" headers - see that
     module). For a required outcome code, chunks tagged with that exact
     code are the ground truth: they ARE that topic's guide content, not a
     lexical guess.
  2. LEXICAL RANKING within that structural set: src.validation.
     novelty_checker.ReferenceCorpusIndex.top_k ranks those chunks by
     TF-IDF cosine similarity against the topic title + section's
     occupational context, so the passages chosen are the most
     specifically relevant ones on that topic, not just the first page.
  3. FALLBACK (rare - only if a required KT code was never tagged to any
     page, e.g. a corpus formatting quirk): an unfiltered corpus-wide
     lexical search on the topic title, explicitly marked as a fallback in
     the returned evidence's ``reason`` field so it is never silently
     indistinguishable from a structurally-confirmed match.

No LLM call happens in this module - it is pure deterministic retrieval
over the already-extracted, already-paginated corpus, exactly like the
rest of src/analysis/ and src/validation/novelty_checker.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.security.config import SecurityConfig
from src.validation.novelty_checker import ReferenceCorpusIndex


def load_retrieval_index(corpus_chunks_path: Path) -> tuple[ReferenceCorpusIndex, list[dict[str, Any]]]:
    """Loads and indexes ``artifacts/reference-corpus-chunks.json`` ONCE,
    for reuse by BOTH question-side retrieval (build_evidence_by_section
    below) AND answer-side retrieval
    (src.generation.memo_generator.generate_memo) - the token/compute-
    efficiency point: a real generation run parses and indexes the
    ~6,000-chunk corpus exactly once, never once per section and once per
    memo call. Shared by src/cli.py and api/service.py so both real entry
    points build the SAME index the SAME way, rather than each re-
    implementing it (see api/service.py's own "reuse over duplication"
    docstring)."""
    if not corpus_chunks_path.exists():
        raise FileNotFoundError(
            f"{corpus_chunks_path} not found. Run `python -m src.cli analyze` first - real generation "
            f"requires the retrieval corpus built from sdev/, it cannot proceed on topic names alone."
        )
    chunks = json.loads(corpus_chunks_path.read_text(encoding="utf-8"))
    return ReferenceCorpusIndex(chunks), chunks


def build_evidence_by_section(
    blueprint_dict: dict[str, Any],
    index: ReferenceCorpusIndex,
    chunks: list[dict[str, Any]],
    security_config: SecurityConfig,
    seed: int,
) -> dict[str, list[dict[str, Any]]]:
    """Real-generation-mode QUESTION-side evidence retrieval: for every
    blueprint section, retrieve real, page-cited learner-guide passages for
    its required outcomes (select_evidence below) - this is what makes
    question generation grounded rather than topic-name-only; see
    docs/DESIGN.md. Shared by src/cli.py and api/service.py."""
    evidence_by_section: dict[str, list[dict[str, Any]]] = {}
    for section in blueprint_dict["sections"]:
        outcome_title_map = dict(zip(section["outcomes"], section["competencies"]))
        evidence_by_section[section["id"]] = select_evidence(
            index,
            chunks,
            required_outcomes=section.get("required_outcomes", section["outcomes"]),
            outcome_title_map=outcome_title_map,
            occupational_context=section["occupational_context"],
            seed=seed,
            security_config=security_config,
        )
    return evidence_by_section


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."


def _topic_query(title: str, occupational_context: str) -> str:
    return f"{title} {occupational_context}"


def _select_evidence_for_topics(
    index: ReferenceCorpusIndex,
    topics: list[tuple[str, str, str]],
    seed: int,
    security_config: SecurityConfig,
) -> list[dict[str, Any]]:
    """Shared retrieval core for both select_evidence (question-time) and
    select_answer_evidence (answer-time) - ``topics`` is a list of
    ``(code, title, query_text)``, the only thing that differs between the
    two callers (question-time queries on "title + occupational context";
    answer-time queries on "title + the actual generated question text" -
    see select_answer_evidence). Everything else - structural KT-tag
    filtering, lexical ranking, seed rotation, round-robin budget
    distribution, dedup - is identical and lives here once.
    """
    budget = security_config.evidence_passages_per_section
    max_chars = security_config.max_evidence_passage_chars

    if not topics:
        return []

    per_topic_pool = max(2, (budget * 2) // max(1, len(topics)) + 1)
    evidence: list[dict[str, Any]] = []
    seen_chunk_keys: set[tuple[str, int, str]] = set()

    for code, title, query in topics:
        if len(evidence) >= budget:
            break

        structural = index.top_k(query, per_topic_pool, chunk_filter=lambda c, code=code: c.get("kt_code") == code)
        fallback_used = False
        if not structural:
            # No chunk was ever tagged with this KT code (corpus formatting
            # quirk) - fall back to an unfiltered lexical search, clearly
            # marked as such. Still real corpus text with a real page
            # number; only the "we're sure this IS the right topic"
            # structural guarantee is weaker here.
            structural = index.top_k(query, per_topic_pool)
            fallback_used = True

        if not structural:
            continue  # nothing in the corpus matches this topic at all

        # Seed picks WHICH ranked candidates are used (not just their order),
        # so different seeds for the same topic can surface different real
        # passages - see select_evidence's docstring.
        rotation = seed % len(structural)
        rotated = structural[rotation:] + structural[:rotation]

        taken_for_topic = 0
        for score, chunk in rotated:
            if taken_for_topic >= max(1, budget // max(1, len(topics)) or 1):
                break
            key = (chunk["source"], chunk["page"], chunk["text"][:80])
            if key in seen_chunk_keys:
                continue
            seen_chunk_keys.add(key)
            reason = f"Retrieved for {code} ({title})"
            if fallback_used:
                reason += " - fallback lexical match, not structurally KT-tagged"
            evidence.append(
                {
                    "document": chunk["source"],
                    "page": chunk["page"],
                    "kt_code": code,
                    "passage": _truncate(chunk["text"], max_chars),
                    "reason": reason,
                    "relevance": round(score, 4),
                }
            )
            taken_for_topic += 1
            if len(evidence) >= budget:
                break

    return evidence


def select_evidence(
    index: ReferenceCorpusIndex,
    chunks: list[dict[str, Any]],
    required_outcomes: list[str],
    outcome_title_map: dict[str, str],
    occupational_context: str,
    seed: int,
    security_config: SecurityConfig | None = None,
) -> list[dict[str, Any]]:
    """Return a small, page-cited evidence list for one blueprint section -
    the QUESTION-side of retrieval, used before a question exists.

    ``required_outcomes`` are the section's hand-curated required outcome
    codes (same list src/validation/coverage_validator.py enforces
    question-level coverage against - see configs/software_developer.json).
    Evidence is distributed round-robin across them so every required topic
    is represented (budget permitting), rather than letting one topic's
    passages crowd out the others.

    ``seed`` varies WHICH of a topic's top-ranked passages are chosen
    (not just their order), which is one input to making Paper 2's evidence
    - and therefore its questions - genuinely different from Paper 1's for
    the same section (see src/generation/question_generator.py and
    docs/DESIGN.md, "How Paper 2 differs from Paper 1").

    ``chunks`` is accepted for interface symmetry with select_answer_evidence
    and historical callers, but is not read directly here - all lookups go
    through ``index``, which was built from the same chunks.
    """
    security_config = security_config or SecurityConfig()
    topics = [
        (code, outcome_title_map.get(code, code), _topic_query(outcome_title_map.get(code, code), occupational_context))
        for code in required_outcomes
    ]
    return _select_evidence_for_topics(index, topics, seed, security_config)


def select_answer_evidence(
    index: ReferenceCorpusIndex,
    chunks: list[dict[str, Any]],
    question: dict[str, Any],
    seed: int,
    security_config: SecurityConfig | None = None,
) -> list[dict[str, Any]]:
    """Return a small, page-cited evidence list to support ANSWERING a
    specific, already-generated, already-validated question - the ANSWER
    side of retrieval (src/generation/memo_generator.py), which can only
    run AFTER a question exists, unlike select_evidence above.

    Query text per outcome is the outcome's title PLUS the question's own
    scenario/stem/sub-question text (see _question_query_text) - not just
    the section's occupational context - so retrieval is targeted at what
    THIS question actually asks, per the requirement that answer evidence
    must be based on the generated question, not merely its section/topic.
    Reuses the exact same structural-KT-tag-then-lexical-rank machinery as
    select_evidence (via _select_evidence_for_topics) - no second retrieval
    algorithm, no second index.

    Outcome codes come from ``question["outcomes"]`` - the question's OWN
    declared, already-validated subset (see
    src.generation.question_generator._normalize_question) - which is
    typically narrower than a whole section's required_outcomes, so answer
    retrieval is naturally more targeted than question-time retrieval was.
    """
    security_config = security_config or SecurityConfig()
    outcomes = question.get("outcomes") or []
    if not outcomes:
        return []
    competencies = question.get("competencies") or []
    outcome_title_map = dict(zip(outcomes, competencies))
    question_text = _truncate(_question_query_text(question), 400)

    topics = [
        (code, outcome_title_map.get(code, code), f"{outcome_title_map.get(code, code)} {question_text}")
        for code in outcomes
    ]
    return _select_evidence_for_topics(index, topics, seed, security_config)


def _question_query_text(question: dict[str, Any]) -> str:
    parts = [question.get("scenario") or "", question.get("question", "")]
    parts.extend(sq.get("prompt", "") for sq in question.get("sub_questions", []) or [])
    return " ".join(parts)
