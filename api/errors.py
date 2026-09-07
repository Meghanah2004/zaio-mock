"""Centralized error handling: the client NEVER receives a traceback, an
absolute filesystem path, a raw provider/exception message, or a secret.

Every handler logs a sanitized detail server-side (via the existing
``src.security.redaction`` utilities - no second redaction implementation)
and returns a small, generic, safely-worded JSON body to the client. Only
FastAPI's own request-validation errors and our own explicitly-raised
HTTPExceptions (404/429) carry a message written for a client audience;
everything from the engine (GenerationError, LLMProviderError, ValueError,
or any other exception) is deliberately generic on the wire.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.models import ErrorDetail, ErrorResponse
from src.generation.llm_utils import GenerationError
from src.providers.base import LLMProviderError
from src.security.redaction import sanitize_for_public

logger = logging.getLogger("api")


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _error_response(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message, request_id=_request_id(request)))
    return JSONResponse(status_code=status_code, content=body.model_dump())


async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # exc.errors() can echo back submitted values; never forward it
    # verbatim to the client, only log it (sanitized) server-side.
    logger.info("validation_error request_id=%s detail=%s", _request_id(request), sanitize_for_public(str(exc.errors())))
    return _error_response(request, status.HTTP_422_UNPROCESSABLE_CONTENT, "VALIDATION_ERROR", "Invalid request.")


async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code_by_status = {
        status.HTTP_404_NOT_FOUND: "NOT_FOUND",
        status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMITED",
    }
    code = code_by_status.get(exc.status_code, "HTTP_ERROR")
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    response = _error_response(request, exc.status_code, code, message)
    if exc.headers:
        for key, value in exc.headers.items():
            response.headers[key] = value
    return response


async def handle_generation_error(request: Request, exc: GenerationError) -> JSONResponse:
    logger.error("generation_error request_id=%s detail=%s", _request_id(request), sanitize_for_public(str(exc)))
    return _error_response(
        request, status.HTTP_502_BAD_GATEWAY, "GENERATION_FAILED", "Assessment generation failed. Please try again."
    )


async def handle_provider_error(request: Request, exc: LLMProviderError) -> JSONResponse:
    logger.error("provider_error request_id=%s detail=%s", _request_id(request), sanitize_for_public(str(exc)))
    return _error_response(
        request, status.HTTP_502_BAD_GATEWAY, "PROVIDER_ERROR", "The generation provider failed. Please try again."
    )


async def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
    logger.warning("value_error request_id=%s detail=%s", _request_id(request), sanitize_for_public(str(exc)))
    return _error_response(request, status.HTTP_400_BAD_REQUEST, "INVALID_REQUEST", "The request could not be processed.")


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unexpected_error request_id=%s type=%s detail=%s",
        _request_id(request),
        type(exc).__name__,
        sanitize_for_public(str(exc)),
    )
    return _error_response(
        request, status.HTTP_500_INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "An unexpected error occurred."
    )


def register_exception_handlers(app: FastAPI) -> None:
    # Uses the @app.exception_handler(...) decorator's registration path
    # (via the equivalent functional form) rather than the lower-level
    # Starlette Application.add_exception_handler: the latter's type stub
    # is invariant in the handler's exception parameter (it wants exactly
    # Callable[[Request, Exception], ...]), which rejects every handler
    # below typed to its specific exception subclass even though Starlette
    # dispatches by MRO lookup (src: starlette._exception_handler
    # ._lookup_exception_handler) and is verifiably runtime-safe. FastAPI's
    # own decorator form types its handler parameter as an unconstrained
    # TypeVar and has no such issue - this is the genuinely clean fix, not
    # a suppression.
    app.exception_handler(RequestValidationError)(handle_validation_error)
    app.exception_handler(StarletteHTTPException)(handle_http_exception)
    app.exception_handler(GenerationError)(handle_generation_error)
    app.exception_handler(LLMProviderError)(handle_provider_error)
    app.exception_handler(ValueError)(handle_value_error)
    app.exception_handler(Exception)(handle_unexpected_error)
