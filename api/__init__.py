"""Thin HTTP API layer around the existing assessment-generation engine
(``src/``).

This package owns HTTP concerns only: request/response models, routing,
rate limiting, CORS, security headers, error formatting, request IDs, and
safe result access. It does not implement assessment-generation,
validation, novelty, quality-review, or rendering logic - all of that
stays in ``src/`` and is called into, never duplicated. See
``docs/API.md``.
"""
