"""FastAPI application factory.

Run locally with:

    uvicorn api.app:app --reload

See docs/API.md for the full architecture, security model, and endpoint
reference.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.dependencies import SECURITY_CONFIG
from api.errors import register_exception_handlers
from api.middleware import (
    RequestContextMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from api.routes import generate, health, results
from api.service import ensure_reference_analysis_ready

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Runs the (slow, ~seconds-to-a-minute) reference-analysis step once,
    # before the app starts accepting requests, if it hasn't already been
    # run (via a prior CLI `analyze` or a prior server start) - see
    # api/service.py and docs/API.md, "Why analysis runs once at startup."
    ensure_reference_analysis_ready()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Zaio Mock EISA API",
        description=(
            "Thin API layer around the existing Software Developer Mock EISA "
            "generation engine. See docs/API.md."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # Middleware executes outermost-first for requests, innermost-first for
    # responses - added here innermost -> outermost, so CORS (and its
    # preflight handling) sees every request before anything else, and
    # security headers are stamped on every response including error ones.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=SECURITY_CONFIG.max_request_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=SECURITY_CONFIG.cors_origins_list(),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    register_exception_handlers(app)

    app.include_router(health.router, prefix="/api")
    app.include_router(generate.router, prefix="/api")
    app.include_router(results.router, prefix="/api")

    return app


app = create_app()
