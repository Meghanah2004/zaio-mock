"""POST /api/generate.

Uses high test-only paper numbers (900+) so test runs never overwrite the
canonical Phase 1 deliverable at paper_number=2 - see docs/API.md.
MockProvider is always used here (see tests/conftest.py's session-wide test
isolation, which forces LLM_PROVIDER=mock regardless of the developer's
local .env), so every call is fast and fully offline.

Since the RAG rework, api/service.py performs real grounding, marks,
coverage, AND lexical novelty screening against the real sdev/ corpus -
"pass" and "flag_for_review" are both non-blocking outcomes of that real
screen (only "regenerate" blocks), so a test asserting an exact status
asserts "flag_for_review" never happens, which is not a guarantee this
pipeline makes or should make - see
src/validation/novelty_checker.py's own docstring.
"""
from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from api.app import app

_VALID_BODY = {"qualification": "software_developer", "paper_number": 901, "seed": 1, "pdf": False}


def test_valid_generation_request_succeeds():
    with TestClient(app) as client:
        response = client.post("/api/generate", json=_VALID_BODY)
    assert response.status_code == 200
    body = response.json()
    assert body["result_id"] == 901
    assert body["qualification"] == "software_developer"
    assert body["total_marks"] == 100
    assert body["validation_passed"] is True
    assert body["deterministic_checks_total"] > 0
    # "regenerate" is the only blocking novelty outcome (see module
    # docstring) - both "pass" and "flag_for_review" mean generation
    # succeeded and validation was not blocked by novelty.
    assert body["novelty_status"] in ("pass", "flag_for_review")
    assert body["quality_review_approved"] is True
    assert body["pdf_available"] is False  # pdf: false was requested


def test_generation_with_pdf_true_produces_pdf():
    with TestClient(app) as client:
        response = client.post(
            "/api/generate", json={"qualification": "software_developer", "paper_number": 902, "seed": 2, "pdf": True}
        )
    assert response.status_code == 200
    assert response.json()["pdf_available"] is True


def test_missing_required_field_rejected():
    with TestClient(app) as client:
        response = client.post("/api/generate", json={"qualification": "software_developer"})
    assert response.status_code == 422


def test_wrong_field_type_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/api/generate", json={"qualification": "software_developer", "paper_number": "not-a-number", "seed": 1}
        )
    assert response.status_code == 422


def test_out_of_range_paper_number_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/api/generate", json={"qualification": "software_developer", "paper_number": 999999, "seed": 1}
        )
    assert response.status_code == 422


def test_negative_paper_number_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/api/generate", json={"qualification": "software_developer", "paper_number": -1, "seed": 1}
        )
    assert response.status_code == 422


def test_out_of_range_seed_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/api/generate", json={"qualification": "software_developer", "paper_number": 903, "seed": -1}
        )
    assert response.status_code == 422


def test_invalid_qualification_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/api/generate", json={"qualification": "cybersecurity", "paper_number": 903, "seed": 1}
        )
    assert response.status_code == 422
    assert "cybersecurity" not in response.text or "Unsupported" in str(response.json())


def test_malformed_json_body_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/api/generate", content=b"{not valid json", headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 422


def test_client_supplied_path_fields_are_rejected_as_unknown():
    """The client must never be able to specify a filesystem path - these
    field names aren't part of the contract at all, so strict
    (extra="forbid") validation rejects them outright."""
    with TestClient(app) as client:
        response = client.post(
            "/api/generate",
            json={
                "qualification": "software_developer",
                "paper_number": 904,
                "seed": 1,
                "reference_path": "/etc/passwd",
                "output_path": "../../../etc",
                "source_path": "/",
            },
        )
    assert response.status_code == 422


def test_oversized_request_body_rejected():
    huge_padding = "x" * 100_000
    with TestClient(app) as client:
        response = client.post(
            "/api/generate",
            json={
                "qualification": "software_developer",
                "paper_number": 905,
                "seed": 1,
                "padding_field_not_in_schema": huge_padding,
            },
        )
    # Rejected by the request-size-limit middleware (413) before Pydantic
    # even runs, or by strict schema validation (422) if the middleware
    # didn't catch it first - either is an acceptable rejection, 200 is not.
    assert response.status_code in (413, 422)


def test_error_response_never_contains_a_traceback_or_filesystem_path():
    with TestClient(app) as client:
        response = client.post("/api/generate", json={"qualification": "software_developer"})
    assert response.status_code == 422
    text = response.text.lower()
    assert "traceback" not in text
    assert "/users/" not in text
    assert "site-packages" not in text


def test_health_endpoint_stays_responsive_during_an_in_flight_generation(monkeypatch):
    """Regression test for a real event-loop-blocking defect found in the
    final audit: POST /api/generate used to be declared `async def` while
    calling fully synchronous, blocking generation work (real file I/O,
    and - with a real provider configured - blocking HTTP calls, since
    none of Groq/Anthropic/Gemini's provider modules uses an async
    client) directly, with no `await`/threadpool dispatch. That blocks the
    ENTIRE asyncio event loop for the whole call - which docs/API.md
    already documents as taking anywhere from a few seconds to several
    minutes with a real provider - stalling every OTHER request sharing
    the same worker, GET /api/health included: exactly what a platform/
    orchestrator polls to decide whether an instance is still alive.

    Fixed by declaring the route a plain `def` (api/routes/generate.py) -
    FastAPI automatically dispatches a `def` path operation to an external
    threadpool, so blocking work there no longer blocks the event loop
    other requests share. This test proves the fix directly: while a
    (stubbed, artificially slow) generation is in flight, a concurrent
    health check must still return promptly, not queue behind it.
    """
    import api.routes.generate as generate_route

    def slow_generate_paper_and_memo(qualification, paper_number, seed, want_pdf):
        time.sleep(1.0)
        raise RuntimeError("test stub - intentionally never produces a real result")

    monkeypatch.setattr(generate_route, "generate_paper_and_memo", slow_generate_paper_and_memo)

    # raise_server_exceptions=False: the stub deliberately raises so this
    # test never depends on real generation succeeding - TestClient's
    # default behavior re-raises an unhandled exception in the calling
    # thread for debugging convenience, which here is a background thread
    # pytest would otherwise report as an unhandled thread exception (see
    # tests/test_api_security.py::test_unexpected_internal_error_never_
    # leaks_details for the same, already-established pattern).
    with TestClient(app, raise_server_exceptions=False) as client:
        generate_done = threading.Event()

        def run_slow_generate():
            client.post(
                "/api/generate",
                json={"qualification": "software_developer", "paper_number": 906, "seed": 1, "pdf": False},
            )
            generate_done.set()

        thread = threading.Thread(target=run_slow_generate)
        thread.start()
        time.sleep(0.2)  # let the generate request actually start and enter the sleep

        assert not generate_done.is_set(), "the slow generate call finished too early for this test to be meaningful"

        health_start = time.monotonic()
        health_response = client.get("/api/health")
        health_duration = time.monotonic() - health_start

        thread.join(timeout=5)

    assert health_response.status_code == 200
    # The health check must complete well before the 1s slow generation
    # does - if the event loop were still blocked, it would have had to
    # wait out the remaining sleep first.
    assert health_duration < 0.5
