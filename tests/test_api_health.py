"""GET /api/health."""
from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import app


def test_health_returns_ok():
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "zaio-mock-eisa-api"}


def test_health_response_never_contains_filesystem_or_secret_hints():
    with TestClient(app) as client:
        response = client.get("/api/health")
    body_text = response.text.lower()
    for forbidden in ("/users/", "sdev", "anthropic_api_key", "sk-ant", "/desktop/zaio"):
        assert forbidden not in body_text
