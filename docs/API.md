# API Layer (Phase 2)

A thin FastAPI HTTP layer around the existing, unchanged assessment-
generation engine (`src/`). This document covers the API specifically;
see `docs/DESIGN.md` for the engine's own architecture and
`docs/SECURITY-AUDIT.md` for the Phase 1 security audit this layer builds
on without regressing.

```
Frontend (not built yet)
   |
FastAPI API (api/)          <- HTTP, validation, rate limiting, CORS,
   |                            security headers, safe errors, request IDs
API security boundary
   |
Existing Python engine (src/)  <- generation, validation, novelty,
   |                               quality review, rendering (UNCHANGED)
Assessment + Memo + Validation + PDF
```

## Reuse over duplication

`api/service.py` is the only place the API sequences engine calls, and it
calls the exact same functions `src/cli.py` calls, in the same order,
writing to the same `artifacts/`/`output/` locations - a paper generated
via the API is byte-for-byte indistinguishable from one generated via the
CLI with the same qualification/paper-number/seed. The one refactor this
required: `src/cli.py`'s validator-orchestration logic (schema -> marks ->
coverage -> novelty) was promoted from a private CLI-only function into
`src/validation/orchestrator.run_all_validators`, so both the CLI and the
API call one real implementation instead of two copies. Nothing else in
`src/` changed to accommodate the API - it is otherwise frozen, per
project instructions.

## Endpoints

| Method | Path | Purpose | Rate-limit tier |
|---|---|---|---|
| GET | `/api/health` | Liveness check | LOOSER (read) |
| POST | `/api/generate` | Generate one paper + memo | STRICT-ish (generation) |
| GET | `/api/results/{result_id}` | Fetch a generated paper + memo | LOOSER (read) |
| GET | `/api/results/{result_id}/paper.pdf` | Download the paper PDF | LOOSER (read) |
| GET | `/api/results/{result_id}/memo.pdf` | Download the memo PDF | LOOSER (read) |

No authentication endpoints exist, because no authentication was
introduced - per explicit instruction, not fabricated for its own sake.
If authentication is added later, its endpoints belong in the STRICT tier
described in `src/security/rate_limiter.py`'s docstring.

### No client-supplied paths, ever

`POST /api/generate` accepts exactly `qualification`, `paper_number`,
`seed`, `pdf` (`api/models.GenerateRequest`, `extra="forbid"` - any other
field, including anything shaped like `reference_path`/`output_path`/
`source_path`, is rejected with 422 before it reaches any handler code).
The server alone controls `sdev/`, `configs/`, `prompts/`, `schemas/`, and
where output is written.

`result_id` is a bounded `int` (reusing the exact same
`paper_number` range the CLI already validates, from the shared
`SecurityConfig`), enforced at the FastAPI routing layer before a request
handler ever runs - it cannot contain `/`, `..`, or any other
traversal-shaped character by construction. `api/results.py` still routes
every derived path through `src/config.safe_path_within` anyway, as
defense-in-depth consistent with the rest of the codebase.

### Why `result_id` reuses `paper_number` (no database)

The CLI already names its output files `mock-eisa-paper-{NN}.json` /
`mock-eisa-memo-{NN}.json` by paper number. Reusing that exact number as
the public `result_id` means a paper generated via the CLI and one
generated via the API share one identity scheme, and no database or
separate ID registry is needed at all - `GET /api/results/{id}` just
checks whether the corresponding files exist. This is a deliberate
"simplest safe architecture" choice, not an oversight.

## Why analysis runs once at startup, not per request

`analyze` (parsing all 60 PDFs in `sdev/`) takes **~48 seconds**; every
other stage (`generate`, `validate`, `review`, `render`) completes in
**under half a second** with `MockProvider`. Measured directly:

```
python -m src.cli analyze     -> ~48s
python -m src.cli generate    -> ~0.3s
python -m src.cli validate    -> ~0.4s
```

Running `analyze` inside a request would make the first (or every)
`/api/generate` call unacceptably slow and would let a client trigger an
expensive PDF-parsing pass repeatedly. Instead, the API's FastAPI
`lifespan` (`api/app.py`) calls `ensure_reference_analysis_ready()`
(`api/service.py`) once at startup, which is a no-op if
`artifacts/reference-analysis.json` already exists - exactly mirroring how
the CLI's own `generate`/`validate` commands already assume `analyze` was
run earlier and never re-run it themselves. `sdev/` is immutable supplied
material for the life of a deployment, so a cached analysis never goes
stale.

## Why generation is synchronous (no queue)

With `MockProvider` (the default; no `ANTHROPIC_API_KEY` is configured in
this environment), `/api/generate` completes in well under a second, so a
plain synchronous request/response is the simplest correct design - adding
Celery/Redis/a job queue for sub-second work would be pure over-engineering,
explicitly against this project's instructions.

**Documented limitation**: with a real `AnthropicProvider` configured, one
`/api/generate` call issues 13 sequential provider calls for the current
blueprint (6 question-generation + 6 memo-generation + 1 quality-review),
which could take tens of seconds to a few minutes depending on API
latency. This is synchronous today. If real-provider usage in production
becomes the common case, a background-job pattern would be the natural
next step - not built here, because no real-provider run has ever been
exercised in this environment to justify it, and the instructions are
explicit not to add a queue without proven need. A reverse proxy placed in
front of this API in that scenario would need a generous request timeout.

## Rate limiting

Reuses the existing `src/security/rate_limiter.py` component exactly as
built during the Phase 1 security-hardening pass - **no second rate
limiter was created**. `api/dependencies.py` builds one process-wide
`RateLimiterRegistry` from `SecurityConfig.from_env()` and exposes two
FastAPI dependencies:

- `enforce_generation_rate_limit` - the `generation` bucket (default: 5
  requests/60s + burst 2), applied to `POST /api/generate`.
- `enforce_read_rate_limit` - the `read` bucket (default: 60
  requests/60s), applied to `/api/health` and every `/api/results/*` route.

Exceeding a limit returns `429` with a `Retry-After` header and a
structured `RATE_LIMITED` error body. The limiter key is the raw
connecting-peer address (`request.client.host`) - deliberately **not**
`X-Forwarded-For`/`X-Real-IP`, which a caller controls and could spoof to
pick their own bucket; a trusted reverse proxy, if one is ever added in
front of this API, is the correct place to establish the real client
address, not this application parsing a client-supplied header. All
thresholds are configurable via the same `.env` variables the CLI already
documents (`GENERATION_RATE_LIMIT`, `GENERATION_RATE_WINDOW_SECONDS`,
`GENERATION_BURST`, `READ_RATE_LIMIT`, `READ_RATE_WINDOW_SECONDS`,
`RATE_LIMIT_ENABLED`) - see `.env.example`.

## CORS

Configured explicitly in `api/app.py` via `CORSMiddleware`, sourced from
`SecurityConfig.cors_allowed_origins` (comma-separated,
`CORS_ALLOWED_ORIGINS` env var) - **never `allow_origins=["*"]`**.
Defaults to the two common local frontend dev ports
(`http://localhost:3000`, `http://localhost:5173`) so a future React dev
server works out of the box; a real deployment must set
`CORS_ALLOWED_ORIGINS` to its actual frontend origin(s).
`allow_credentials=False` (no cookies/auth headers are used, so there is
no reason to allow credentialed cross-origin requests); only `GET`/`POST`
and the `Content-Type` header are allowed.

## Security headers

Applied to every response, including error responses, by
`SecurityHeadersMiddleware` (`api/middleware.py`). Chosen deliberately for
a JSON/PDF-only API, not copied from an HTML-site checklist:

| Header | Value | Why |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | Never let a browser MIME-sniff a JSON/PDF response into something executable. |
| `X-Frame-Options` | `DENY` | Nothing here is meant to be framed. |
| `Referrer-Policy` | `no-referrer` | Result URLs contain a `result_id`; don't leak them via outbound `Referer`. |
| `Content-Security-Policy` | `default-src 'none'` | This API never returns HTML/JS - maximally restrictive is always correct. |
| `Strict-Transport-Security` | only when the request arrived over HTTPS | Sending HSTS over plain HTTP (this is a local-dev HTTP server today) is meaningless at best; sent conditionally, not hard-coded. |

`X-XSS-Protection` was deliberately **not** added - it's deprecated,
superseded by CSP, and modern browsers ignore it.

## Error handling

Centralized in `api/errors.py`. The client never receives a traceback, an
absolute filesystem path, a raw provider/exception message, or a secret -
every handler logs a sanitized detail server-side (via the existing
`src.security.redaction.sanitize_for_public`, wired into a live boundary
for the first time - no second redaction implementation) and returns a
small, generic, JSON body:

```json
{"error": {"code": "NOT_FOUND", "message": "Result not found.", "request_id": "..."}}
```

| Situation | Status | Code |
|---|---|---|
| Request validation failure (Pydantic) | 422 | `VALIDATION_ERROR` |
| Rate limit exceeded | 429 | `RATE_LIMITED` |
| Result/PDF not found | 404 | `NOT_FOUND` |
| Deterministic content-generation failure (`GenerationError`) | 502 | `GENERATION_FAILED` |
| LLM provider failure (`LLMProviderError`) | 502 | `PROVIDER_ERROR` |
| Other rejected input (`ValueError`) | 400 | `INVALID_REQUEST` |
| Anything unanticipated | 500 | `INTERNAL_ERROR` |

Only FastAPI's own validation errors and our explicitly-raised 404/429s
carry a message actually written for a client audience; every message
from the engine layer is deliberately generic on the wire, regardless of
what the underlying exception said.

## Request IDs and logging

Every request gets a server-generated UUID (`api/middleware.py`,
`RequestContextMiddleware`) - **a client-supplied `X-Request-ID` header is
never trusted or echoed back**, to close a log-injection vector (a client
could otherwise embed newlines to forge fake log lines). The ID is
attached to `request.state`, included in every error body, and echoed on
the response as `X-Request-ID` so a real caller can still correlate a
request end-to-end.

Logging is structural only: `request_id`, method, path, status, duration.
Never a request body, a full prompt, reference-document content, or a
secret.

## Resource limits

- Request body size: capped by `SecurityConfig.max_request_body_bytes`
  (default 16KB - generous for 4 small JSON fields), enforced by
  `RequestSizeLimitMiddleware` before Pydantic even parses the body.
- `paper_number`/`seed` bounds: the exact same `SecurityConfig` bounds the
  CLI already enforces (`MIN_PAPER_NUMBER`/`MAX_PAPER_NUMBER`/`MIN_SEED`/
  `MAX_SEED`) - not duplicated constants.
- Provider retries, provider response size, and reference-ingestion bounds:
  unchanged from Phase 1 - the API triggers the exact same engine code
  path, so it inherits every existing limit for free.
- Generation rate limiting (see above) is itself the primary defense
  against a client creating unbounded expensive workload via repeated
  calls.

## Secrets

`ANTHROPIC_API_KEY` (and every other secret) stays server-side. It is
read once by `src/config.LLMSettings` from the environment, never appears
in a request or response model, and is never logged - unchanged from
Phase 1. `tests/test_api_security.py` includes a regression test proving
an unexpected internal error containing a credential-shaped string never
reaches the client.

## Local development

```bash
pip install -r requirements.txt -r requirements-dev.txt
uvicorn api.app:app --reload
# GET  http://127.0.0.1:8000/api/health
# POST http://127.0.0.1:8000/api/generate
```

Interactive docs (Swagger UI / ReDoc) are available at `/docs` and `/redoc`
- FastAPI's default behaviour, left enabled since this is a Phase 2
developer-facing API with no sensitive data exposed by its schema.

## Known limitations

- Generation is synchronous (see above) - acceptable today, documented as
  a limitation for a real-provider production deployment.
- No authentication exists. Every rate-limit bucket is keyed by IP only.
  If/when auth is introduced, it belongs in the STRICT tier
  (`src/security/rate_limiter.py`'s docstring already reserves this).
- The rate limiter is in-process/single-node (unchanged from Phase 1 - see
  `docs/SECURITY-AUDIT.md`); a multi-worker or multi-instance deployment
  would need a shared store, not built here per explicit scope.
- No result deletion/expiry endpoint exists; generated files under
  `output/` accumulate until manually cleaned up (same as the CLI today).
- `GET /docs`/`/redoc`/`/openapi.json` are enabled by default (FastAPI's
  standard behaviour) and are not behind the read rate limiter; they
  expose the API's schema (not data) and were left enabled as a
  Phase-2/developer convenience - revisit before any public deployment.
