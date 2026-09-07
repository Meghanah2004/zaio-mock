"""GET /api/results/{result_id} and its PDF sub-resources.

Uses a dedicated high test-only paper_number (910) generated once per
test module run - see docs/API.md for why result_id reuses paper_number
as its identity.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import app

_RESULT_ID = 910


@pytest.fixture(scope="module", autouse=True)
def _seed_one_result():
    with TestClient(app) as client:
        response = client.post(
            "/api/generate",
            json={"qualification": "software_developer", "paper_number": _RESULT_ID, "seed": 7, "pdf": True},
        )
    assert response.status_code == 200


def test_valid_result_lookup_returns_paper_and_memo():
    with TestClient(app) as client:
        response = client.get(f"/api/results/{_RESULT_ID}")
    assert response.status_code == 200
    body = response.json()
    assert body["result_id"] == _RESULT_ID
    assert body["paper"]["total_marks"] == 100
    assert body["memo"]["total_marks"] == 100
    assert set(body["available_formats"]) == {"json", "md", "pdf"}


def test_nonexistent_result_returns_safe_404():
    with TestClient(app) as client:
        response = client.get("/api/results/8888")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert "traceback" not in response.text.lower()


def test_invalid_result_id_type_rejected():
    with TestClient(app) as client:
        response = client.get("/api/results/not-a-number")
    assert response.status_code == 422


def test_negative_result_id_rejected():
    with TestClient(app) as client:
        response = client.get("/api/results/-5")
    assert response.status_code == 422


def test_out_of_range_result_id_rejected():
    with TestClient(app) as client:
        response = client.get("/api/results/99999999")
    assert response.status_code == 422


def test_paper_pdf_download_succeeds():
    with TestClient(app) as client:
        response = client.get(f"/api/results/{_RESULT_ID}/paper.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:4] == b"%PDF"


def test_memo_pdf_download_succeeds():
    with TestClient(app) as client:
        response = client.get(f"/api/results/{_RESULT_ID}/memo.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:4] == b"%PDF"


def test_pdf_for_nonexistent_result_returns_safe_404():
    with TestClient(app) as client:
        response = client.get("/api/results/8888/paper.pdf")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_pdf_for_result_generated_without_pdf_returns_404():
    with TestClient(app) as client:
        gen = client.post(
            "/api/generate",
            json={"qualification": "software_developer", "paper_number": 911, "seed": 1, "pdf": False},
        )
        assert gen.status_code == 200
        response = client.get("/api/results/911/paper.pdf")
    assert response.status_code == 404
