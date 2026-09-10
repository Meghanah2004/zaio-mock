"""Cross-paper novelty: keeps every NEW generation from collapsing into ANY
earlier one - not just "Paper 2 vs Paper 1". This is deliberately an
UNBOUNDED-COUNT design: a candidate question for paper N is checked against
every entry accumulated from papers 1..N-1 for that same section, however
many that is. Nothing in this module or its caller
(src/generation/question_generator.generate_paper) branches on a specific
paper number - see docs/DESIGN_NOTE.md, "Cross-paper novelty works for an
arbitrary number of prior papers," for the full explanation with file/line
references.

src/validation/novelty_checker.py answers a different question - "does this
question resemble the SOURCE CORPUS" (anti-copying from sdev/). This module
answers "does this question resemble a PREVIOUSLY GENERATED PAPER'S
question for the same section" (anti-duplication ACROSS generation runs,
however many runs there have been).

The history is a small, local JSON file
(``artifacts/generation-history.json``) keyed by section id, holding a
short fingerprint (scenario + question + sub-question text) of every
previously generated question for that section, across EVERY paper number
and every seed ever generated - not a rolling "just the last paper" window.
It is deliberately NOT the full paper JSON - just enough text to compute
similarity - and is capped per section (``MAX_HISTORY_ENTRIES_PER_SECTION``)
only so a very long-lived project's history file cannot grow unboundedly on
disk; at one question per section per paper this still retains 50 papers'
worth of history before the oldest entry for a section rolls off, which is
the practical meaning of "arbitrary number of previous papers" here.

Nothing here is LLM-based: it is the same plain, dependency-free cosine
similarity used for grounding (src/retrieval/text_similarity.py), applied
pairwise against however many prior entries a section's history holds, not
a corpus-scale index.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.retrieval.text_similarity import cosine_similarity

MAX_HISTORY_ENTRIES_PER_SECTION = 50


def _question_text(q: dict[str, Any]) -> str:
    parts = [q.get("scenario") or "", q.get("question", "")]
    parts.extend(sq.get("prompt", "") for sq in q.get("sub_questions", []))
    return " ".join(parts)


def load_history(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("sections", {})


def write_history(history: dict[str, list[dict[str, Any]]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sections": history}, indent=2), encoding="utf-8")


def max_similarity_to_history(
    question_text: str, section_id: str, history: dict[str, list[dict[str, Any]]]
) -> tuple[float, str | None]:
    """Highest similarity between ``question_text`` and any prior paper's
    question for ``section_id``. Returns (score, source_paper_id | None)."""
    best_score = 0.0
    best_paper: str | None = None
    for entry in history.get(section_id, []):
        score = cosine_similarity(question_text, entry["text"])
        if score > best_score:
            best_score, best_paper = score, entry.get("paper_id")
    return best_score, best_paper


def record_paper(history: dict[str, list[dict[str, Any]]], paper: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return an updated history including every question in ``paper``.

    Does not mutate ``history`` in place (callers load, record, write as
    separate explicit steps - see src/cli.py cmd_generate).
    """
    updated = {k: list(v) for k, v in history.items()}
    for section in paper["sections"]:
        section_id = section["id"]
        entries = updated.setdefault(section_id, [])
        for q in section["questions"]:
            entries.append(
                {
                    "paper_id": paper["paper_id"],
                    "question_id": q["id"],
                    "text": _question_text(q),
                }
            )
        updated[section_id] = entries[-MAX_HISTORY_ENTRIES_PER_SECTION:]
    return updated
