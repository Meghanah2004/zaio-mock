"""POST /api/generate.

Uses high test-only paper numbers (900+) so test runs never overwrite the
canonical Phase 1 deliverable at paper_number=2 - see docs/API.md.
MockProvider is always used here (no ANTHROPIC_API_KEY in this
environment), so every call is fast and fully offline.
"""
from __future__ import annotations

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
    assert body["novelty_status"] == "pass"
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
