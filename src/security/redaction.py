"""Secret redaction and public-safe error formatting.

``redact_secrets`` is used NOW, on every uncaught exception at the CLI's
top level (src/cli.py:main), as defense-in-depth: even though no code path
is known to put a real secret into an exception message today, an
exception message is attacker- or environment-influenced text by
definition, and secrets must never reach it.

``sanitize_for_public`` is PREPARED FOR A FUTURE API LAYER. It additionally
strips absolute filesystem paths and collapses the message to a generic
form. It is not called anywhere in the current CLI-only application - the
CLI is a trusted local operator interface and is explicitly permitted
(per project instructions) to show more descriptive errors than a public
API boundary would. It is implemented and tested now so that a future API
error handler has a ready, tested function to call rather than needing to
invent one under time pressure.
"""
from __future__ import annotations

import re

from src.config import PROJECT_ROOT

_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"),  # Anthropic-style key
    re.compile(r"sk-or-v1-[A-Za-z0-9_-]{10,}"),  # OpenRouter API key (distinctive prefix)
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),  # generic OpenAI-style key - also matches sk-or-v1-... as a fallback
    re.compile(r"AIza[A-Za-z0-9_-]{35}"),  # Google/Gemini API key (fixed-length, distinctive prefix)
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),  # Groq API key (distinctive prefix)
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),  # GitHub personal access token
    re.compile(r"gh[oprsu]_[A-Za-z0-9]{20,}"),  # other GitHub token prefixes
    re.compile(r"(?i)(api[_-]?key|token|secret|password|bearer)\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+=]{8,}['\"]?"),
    re.compile(r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._\-]+"),
]

_REDACTED = "[REDACTED]"


def redact_secrets(text: str) -> str:
    """Replace anything that looks like a credential with a fixed marker.

    Deliberately broad/over-matching rather than narrow: a false-positive
    redaction (masking something that wasn't actually a secret) is a
    cosmetic cost; a false negative (leaking a real key) is not acceptable.
    """
    if not text:
        return text
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(_REDACTED, redacted)
    return redacted


def _strip_absolute_paths(text: str) -> str:
    """Replace absolute paths under the project root with a relative,
    non-identifying form; replace any other absolute path with a generic
    placeholder. Never expose the operator's home directory or machine
    layout in a message meant for an untrusted/public audience."""
    root_str = str(PROJECT_ROOT)
    text = text.replace(root_str, "<project>")
    # Any remaining absolute POSIX-style path -> generic placeholder.
    return re.sub(r"(?<![\w.])/(?:[^\s'\"]+/)*[^\s'\"]+", "<path>", text)


def sanitize_for_public(text: str) -> str:
    """Best-effort transform of an internal error/exception message into
    something safe to show an untrusted caller: secrets redacted, absolute
    paths stripped. NOT currently wired into the CLI (see module
    docstring) - prepared for a future API error boundary."""
    return _strip_absolute_paths(redact_secrets(text))
