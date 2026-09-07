"""Tests for secret redaction and public-safe error formatting.

redact_secrets is wired into the CLI's top-level exception handler NOW
(src/cli.py:main) - these tests exercise that real behaviour directly.
sanitize_for_public is PREPARED FOR A FUTURE API layer and is tested here
so it is ready, but it is not called from the CLI today (see module
docstring in src/security/redaction.py).
"""
from __future__ import annotations

from src.security.redaction import redact_secrets, sanitize_for_public


def test_redacts_anthropic_style_key():
    text = "Anthropic API call failed: invalid key sk-ant-api03-abcdefghijklmnopqrstuvwxyz"
    redacted = redact_secrets(text)
    assert "sk-ant-api03" not in redacted
    assert "[REDACTED]" in redacted


def test_redacts_generic_openai_style_key():
    text = "auth error using sk-abcdefghijklmnopqrstuvwxyz1234567890"
    redacted = redact_secrets(text)
    assert "sk-abcdefghijklmnopqrstuvwxyz1234567890" not in redacted


def test_redacts_github_token():
    text = "failed to push using ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    redacted = redact_secrets(text)
    assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" not in redacted


def test_redacts_key_value_style_secrets():
    cases = [
        ("api_key=abcdef1234567890", "abcdef1234567890"),
        ("API-KEY: 'abcdef1234567890'", "abcdef1234567890"),
        ("password=SuperSecretValue123", "SuperSecretValue123"),
        ('token: "abcdef1234567890"', "abcdef1234567890"),
    ]
    for text, secret_value in cases:
        redacted = redact_secrets(text)
        assert secret_value not in redacted, f"secret leaked for input: {text!r}"
        assert "[REDACTED]" in redacted


def test_redacts_bearer_authorization_header():
    text = "Authorization: Bearer abc123.def456.ghi789"
    redacted = redact_secrets(text)
    assert "abc123.def456.ghi789" not in redacted


def test_leaves_ordinary_error_text_unchanged():
    text = "File not found: reference-analysis.json"
    assert redact_secrets(text) == text


def test_empty_and_none_like_input_is_safe():
    assert redact_secrets("") == ""


def test_sanitize_for_public_strips_project_root_path():
    from src.config import PROJECT_ROOT

    text = f"Missing prompt template: {PROJECT_ROOT}/prompts/generate_questions.txt"
    sanitized = sanitize_for_public(text)
    assert str(PROJECT_ROOT) not in sanitized
    assert "<project>" in sanitized


def test_sanitize_for_public_strips_unrelated_absolute_paths():
    text = "Permission denied: /Users/someone/.ssh/id_rsa"
    sanitized = sanitize_for_public(text)
    assert "/Users/someone/.ssh/id_rsa" not in sanitized


def test_sanitize_for_public_also_redacts_secrets():
    text = "Failed using key sk-ant-api03-abcdefghijklmnopqrstuvwxyz at /Users/dev/project/file.py"
    sanitized = sanitize_for_public(text)
    assert "sk-ant-api03" not in sanitized
    assert "/Users/dev/project" not in sanitized
