"""Shared constants and small helpers for the paper/memo JSON shapes.

The paper and memo are plain ``dict`` objects validated against
``schemas/paper.schema.json`` / ``schemas/memo.schema.json`` at the
boundaries (see src/validation/schema_validator.py) rather than modeled as
heavyweight classes - the JSON Schema is the single source of truth for
structure, so we don't duplicate it here as a parallel class hierarchy.
"""
from __future__ import annotations

DIFFICULTIES = ("foundational", "intermediate", "advanced")

QUESTION_TYPES = (
    "scenario_short_answer",
    "scenario_extended",
    "code_analysis",
    "code_writing",
    "design_task",
    "short_answer",
)


def question_id(section_id: str, question_number: int) -> str:
    return f"Q-{section_id}{question_number}"


def section_question_number(section_id: str, index: int) -> str:
    return f"{section_id}{index}"
