"""Verifies the pipeline fails loudly (not silently) on bad provider output."""
from __future__ import annotations

import pytest

from src.generation.llm_utils import GenerationError
from src.generation.memo_generator import generate_memo
from src.generation.question_generator import generate_paper
from src.providers.base import LLMProvider


class _NotJsonProvider(LLMProvider):
    name = "broken-not-json"

    def generate(self, system_prompt, user_prompt, task):
        return "Sure, here is your question: I refuse to output JSON today."


class _MissingFieldsProvider(LLMProvider):
    name = "broken-missing-fields"

    def generate(self, system_prompt, user_prompt, task):
        return "{\"type\": \"short_answer\"}"


class _WrongMarksProvider(LLMProvider):
    name = "broken-wrong-marks"

    def generate(self, system_prompt, user_prompt, task):
        return (
            "{\"type\": \"short_answer\", \"question\": \"Q?\", \"expected_response_type\": \"short_answer\", "
            "\"sub_questions\": [{\"id\": \"1\", \"prompt\": \"p\", \"marks\": 1, \"expected_response_type\": \"short_answer\"}]}"
        )


def _blueprint():
    return {
        "sections": [
            {
                "id": "A",
                "title": "Section A",
                "marks": 10,
                "outcomes": ["KM-05-KT01"],
                "competencies": ["Programming basics"],
                "difficulty": "foundational",
                "question_types": ["short_answer"],
                "occupational_context": "Test context.",
            }
        ],
        "paper_id": "mock-eisa-test-paper-01",
        "qualification_title": "Occupational Certificate: Software Developer",
        "nqf_level": [4],
        "status_disclaimer": "MOCK / PRACTICE ASSESSMENT ONLY.",
        "duration_minutes": 60,
        "total_marks": 10,
        "instructions": ["Answer all questions."],
    }


def test_non_json_provider_output_raises_generation_error():
    with pytest.raises(GenerationError):
        generate_paper(_blueprint(), _NotJsonProvider(), seed=0)


def test_missing_required_fields_raises_generation_error():
    with pytest.raises(GenerationError):
        generate_paper(_blueprint(), _MissingFieldsProvider(), seed=0)


def test_marks_not_matching_section_target_raises_generation_error():
    with pytest.raises(GenerationError):
        generate_paper(_blueprint(), _WrongMarksProvider(), seed=0)


def test_memo_generator_rejects_mismatched_question_id():
    class _WrongIdMemoProvider(LLMProvider):
        name = "broken-memo-id"

        def generate(self, system_prompt, user_prompt, task):
            return (
                '{"question_id": "Q-WRONG", "total_marks": 10, "model_answer": "x", '
                '"criteria": [{"description": "d", "marks": 10}]}'
            )

    paper = {
        "sections": [
            {
                "id": "A",
                "questions": [
                    {
                        "id": "Q-A1",
                        "section_id": "A",
                        "marks": 10,
                        "question": "Q?",
                    }
                ],
            }
        ]
    }
    with pytest.raises(GenerationError):
        generate_memo(paper, _WrongIdMemoProvider(), seed=0)
