"""A failed generation must not incorrectly register a paper as
successfully generated in the cross-paper novelty history.

Verified directly by code reading during the final audit:
api.service.generate_paper_and_memo calls generate_paper(...) then
generate_memo(...) BEFORE ever calling write_history(record_paper(...)) -
and does not wrap either call in a try/except (it deliberately lets
GenerationError/LLMProviderError/etc. propagate unchanged - see that
function's own docstring). So a failure anywhere in generation or memo
production means the history write is never reached. src/cli.py's
cmd_generate has the equivalent property via its own try/except returning
early. This was previously unverified by any test - this file closes that
gap.
"""
from __future__ import annotations

import api.service as service_module
from src.generation.llm_utils import GenerationError


def test_a_failed_generation_does_not_write_to_generation_history(monkeypatch):
    """The direct proof: force generate_paper to fail, and confirm the
    history file is left exactly as it was before the attempt - not
    created, not modified, and in particular never recording the failed
    paper_number as if it had succeeded."""
    history_path = service_module._GENERATION_HISTORY_PATH
    assert not history_path.exists(), "expected a fresh, isolated history file for this test (see tests/conftest.py)"

    def failing_generate_paper(*args, **kwargs):
        raise GenerationError("simulated generation failure - e.g. exhausted grounding/novelty retries")

    monkeypatch.setattr(service_module, "generate_paper", failing_generate_paper)

    try:
        service_module.generate_paper_and_memo(
            qualification="software_developer", paper_number=907, seed=1, want_pdf=False
        )
        raise AssertionError("expected GenerationError to propagate, but generate_paper_and_memo returned normally")
    except GenerationError:
        pass

    assert not history_path.exists(), (
        "a failed generation must never create/write the history file - "
        "it would otherwise register a non-existent paper as having succeeded"
    )


def test_a_failed_memo_generation_does_not_write_to_generation_history(monkeypatch):
    """Same property, but the failure happens one step later - AFTER a
    valid question paper exists but BEFORE the memo (and therefore the
    history write, which happens after both) completes. The paper that
    exhausted its grounding/novelty retries successfully must still never
    be recorded if memo generation subsequently fails."""
    history_path = service_module._GENERATION_HISTORY_PATH
    assert not history_path.exists()

    def failing_generate_memo(*args, **kwargs):
        raise GenerationError("simulated memo/answer-grounding failure")

    monkeypatch.setattr(service_module, "generate_memo", failing_generate_memo)

    try:
        service_module.generate_paper_and_memo(
            qualification="software_developer", paper_number=908, seed=1, want_pdf=False
        )
        raise AssertionError("expected GenerationError to propagate, but generate_paper_and_memo returned normally")
    except GenerationError:
        pass

    assert not history_path.exists(), "a failed memo generation must never leave a history write behind either"


def test_a_successful_generation_does_write_to_generation_history():
    """Sanity check that the two tests above are meaningful - i.e. this
    isn't simply "the history file is never written" - a genuinely
    successful generation (MockProvider, real committed corpus) DOES
    record its paper."""
    history_path = service_module._GENERATION_HISTORY_PATH
    assert not history_path.exists()

    service_module.generate_paper_and_memo(
        qualification="software_developer", paper_number=909, seed=1, want_pdf=False
    )

    assert history_path.exists()
    import json

    history = json.loads(history_path.read_text(encoding="utf-8"))
    recorded_paper_ids = {
        entry["paper_id"] for entries in history.get("sections", {}).values() for entry in entries
    }
    assert "mock-eisa-software_developer-paper-909" in recorded_paper_ids
