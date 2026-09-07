"""Cross-cutting API security behaviour: rate limiting, security headers,
CORS, request IDs, path-traversal/sdev-access attempts, and
secret/traceback leakage prevention.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import RATE_LIMITER
from src.security.rate_limiter import TokenBucketRateLimiter

# ---------------------------------------------------------------------------
# Rate limiting (reuses the existing src/security/rate_limiter.py component)
# ---------------------------------------------------------------------------


def test_rate_limit_allows_requests_up_to_capacity_then_returns_429(monkeypatch):
    # A tiny, dedicated limiter so this test is fast and deterministic,
    # independent of the real default thresholds - exercises the SAME
    # dependency function (enforce_read_rate_limit) the app uses for real.
    monkeypatch.setattr(RATE_LIMITER, "read", TokenBucketRateLimiter(rate=2, window_seconds=60, burst=0))
    with TestClient(app) as client:
        first = client.get("/api/health")
        second = client.get("/api/health")
        third = client.get("/api/health")
    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert "Retry-After" in third.headers
    body = third.json()
    assert body["error"]["code"] == "RATE_LIMITED"


def test_rate_limit_disabled_flag_allows_unlimited_requests(monkeypatch):
    monkeypatch.setattr(RATE_LIMITER, "enabled", False)
    with TestClient(app) as client:
        responses = [client.get("/api/health") for _ in range(10)]
    assert all(r.status_code == 200 for r in responses)


def test_generation_and_read_rate_limits_are_independent_buckets(monkeypatch):
    monkeypatch.setattr(RATE_LIMITER, "read", TokenBucketRateLimiter(rate=1, window_seconds=60, burst=0))
    with TestClient(app) as client:
        client.get("/api/health")
        exhausted = client.get("/api/health")
        assert exhausted.status_code == 429
        # A different endpoint class (generation) must be unaffected.
        generate_response = client.post(
            "/api/generate", json={"qualification": "software_developer", "paper_number": 920, "seed": 1}
        )
    assert generate_response.status_code == 200


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------


def test_security_headers_present_on_success_response():
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["content-security-policy"] == "default-src 'none'"


def test_security_headers_present_on_error_response():
    with TestClient(app) as client:
        response = client.get("/api/results/8888")
    assert response.status_code == 404
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "default-src 'none'"


def test_hsts_not_sent_over_plain_http():
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert "strict-transport-security" not in response.headers


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


def test_cors_allows_configured_localhost_origin():
    with TestClient(app) as client:
        response = client.options(
            "/api/health",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
        )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_rejects_unrecognized_origin():
    with TestClient(app) as client:
        response = client.options(
            "/api/health",
            headers={"Origin": "http://evil.example.com", "Access-Control-Request-Method": "GET"},
        )
    assert response.headers.get("access-control-allow-origin") != "http://evil.example.com"


def test_cors_does_not_allow_credentials():
    with TestClient(app) as client:
        response = client.options(
            "/api/health",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
        )
    assert response.headers.get("access-control-allow-credentials") != "true"


def test_cors_is_not_wildcard():
    from api.dependencies import SECURITY_CONFIG

    assert "*" not in SECURITY_CONFIG.cors_origins_list()


# ---------------------------------------------------------------------------
# Request IDs
# ---------------------------------------------------------------------------


def test_request_id_present_and_unique_per_request():
    with TestClient(app) as client:
        first = client.get("/api/health")
        second = client.get("/api/health")
    assert "x-request-id" in first.headers
    assert "x-request-id" in second.headers
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


def test_client_supplied_request_id_is_not_trusted():
    """A client-supplied X-Request-ID must never be echoed back verbatim -
    the server always generates its own (log-injection defense)."""
    with TestClient(app) as client:
        response = client.get("/api/health", headers={"X-Request-ID": "attacker-controlled\nFAKE LOG LINE"})
    assert response.headers["x-request-id"] != "attacker-controlled\nFAKE LOG LINE"


def test_error_response_includes_request_id():
    with TestClient(app) as client:
        response = client.get("/api/results/8888")
    assert response.json()["error"]["request_id"] is not None
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


# ---------------------------------------------------------------------------
# Path traversal / sdev access attempts
# ---------------------------------------------------------------------------


def test_traversal_in_result_id_path_segment_does_not_resolve():
    with TestClient(app) as client:
        response = client.get("/api/results/../../../etc/passwd")
    assert response.status_code == 404


def test_encoded_traversal_in_result_id_does_not_resolve():
    with TestClient(app) as client:
        response = client.get("/api/results/%2e%2e%2f%2e%2e%2fetc%2fpasswd")
    assert response.status_code in (404, 422)


def test_absolute_path_as_result_id_rejected():
    with TestClient(app) as client:
        response = client.get("/api/results//etc/passwd")
    assert response.status_code in (404, 422)


def test_no_endpoint_exposes_sdev_contents():
    with TestClient(app) as client:
        for attempt in (
            "/api/sdev",
            "/api/results/sdev",  # rejected by int type validation before any path is touched
            "/api/../sdev/Module%202-Learner%20Guide.pdf",
            "/sdev/Module 2-Learner Guide.pdf",
        ):
            response = client.get(attempt)
            # Never 200, and never anything resembling PDF/file content -
            # 404 (no matching route) and 422 (failed type validation, e.g.
            # "sdev" is not a valid int result_id) are both safe rejections.
            assert response.status_code in (404, 422)
            assert b"%PDF" not in response.content


def test_generate_request_cannot_smuggle_a_path_via_any_field():
    with TestClient(app) as client:
        response = client.post(
            "/api/generate",
            json={
                "qualification": "../../sdev",
                "paper_number": 921,
                "seed": 1,
            },
        )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Secret / traceback leakage prevention
# ---------------------------------------------------------------------------


def test_unexpected_internal_error_never_leaks_details(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError(
            "internal failure using key sk-ant-api03-abcdefghijklmnopqrstuvwxyz "
            "at /Users/someone/Desktop/zaio/secret_module.py"
        )

    import api.routes.generate as generate_route

    monkeypatch.setattr(generate_route, "generate_paper_and_memo", _boom)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/generate", json={"qualification": "software_developer", "paper_number": 922, "seed": 1}
        )
    assert response.status_code == 500
    text = response.text
    assert "sk-ant-api03" not in text
    assert "/Users/someone" not in text
    assert "Traceback" not in text
    assert "RuntimeError" not in text
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"


def test_health_and_results_responses_never_contain_env_var_names():
    with TestClient(app) as client:
        responses = [client.get("/api/health"), client.get("/api/results/8888")]
    for response in responses:
        text = response.text
        assert "ANTHROPIC_API_KEY" not in text
        assert "LLM_PROVIDER" not in text
