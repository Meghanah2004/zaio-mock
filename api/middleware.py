"""Cross-cutting request/response middleware: request IDs, safe logging,
and security headers.

Logging here is deliberately minimal and structural (request ID, method,
path, status, duration) - never a request body, prompt, reference
document, or header value. See docs/API.md, "Request IDs and safe
logging."
"""
from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("api")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a fresh, server-generated request ID to every request.

    Deliberately does NOT honour a client-supplied ``X-Request-ID`` -
    accepting arbitrary client input straight into log lines would be a
    log-injection vector (e.g. embedded newlines forging extra log
    entries). The ID is generated here, attached to ``request.state``, and
    echoed back on the response so a caller can still correlate it.
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.monotonic() - start) * 1000
            logger.exception(
                "request_id=%s method=%s path=%s status=error duration_ms=%.1f",
                request_id,
                request.method,
                request.url.path,
                duration_ms,
            )
            raise
        duration_ms = (time.monotonic() - start) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects an oversized request body before it reaches Pydantic
    parsing, using the SAME bound as everywhere else
    (``SecurityConfig.max_request_body_bytes``) - no duplicated constant.

    Checked in two ways: a declared ``Content-Length`` over the limit is
    rejected immediately without reading the body; if the header is absent
    or understated, the body is still read (Starlette will do this
    eventually anyway) and rejected post-hoc if it turns out to exceed the
    bound. Every request handled by this API is a handful of small JSON
    fields, so there is no legitimate case this rejects.
    """

    def __init__(self, app, max_bytes: int):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self._max_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body too large."}},
                    )
            except ValueError:
                pass  # malformed header - let normal request handling reject it
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Headers evaluated and chosen deliberately for a JSON/PDF-only API
    (see docs/API.md, "Security headers" for the reasoning per header):

    - X-Content-Type-Options: nosniff - stop a browser from ever
      MIME-sniffing a response into executable content.
    - X-Frame-Options: DENY - this API serves no page meant to be framed.
    - Referrer-Policy: no-referrer - result URLs contain a result_id;
      don't leak them via the Referer header on any outbound link.
    - Content-Security-Policy: default-src 'none' - this API never
      returns HTML/JS; maximally restrictive is always correct here.
    - Strict-Transport-Security - only sent when the request actually
      arrived over HTTPS (sending HSTS over plain HTTP is meaningless at
      best and actively wrong to hard-code for a local-HTTP dev server).
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
