# Deployment

This project ships as two independently-deployable pieces - a FastAPI
backend (`api/` + the `src/` engine) and a static Vite/React frontend
(`frontend/`) that talks to it over HTTP. There is no single-process
combined deployment in the traditional sense: the frontend has no server-
side logic of its own, and the backend is not a static site - but see
"Vercel deployment" below for how Vercel's Services model runs both under
one project without changing that fact.

**Live deployment: Vercel**, via `vercel.json`'s `services` split (one
project, `frontend/` and the FastAPI backend as two independently-built
services on a shared domain - see [Services](#vercel-deployment) below for
the full picture, including the filesystem constraints that required real
code changes, not just configuration, to satisfy). The `Dockerfile` at the
repo root remains a valid, fully general alternative for any other platform
(Railway, Render, Fly.io, a plain VPS, ECS, ...) that runs a plain
container - see [Docker / any other platform](#docker--any-other-platform).
Pick whichever applies and read the matching section; both are documented
because both are real, not speculative.

## Vercel deployment

**Production**: `https://zaio-sable.vercel.app` (project `qwertyuiop12/zaio`).
`GET /api/health` and `POST /api/generate` are both live.

### Why this needed real code changes, not just `vercel.json`

Vercel Functions run from a **read-only application filesystem**, with a
writable `/tmp` scratch directory as the only exception (Vercel's own
docs: *"Read-only filesystem with writable /tmp scratch space"*). This
project's engine was written assuming `PROJECT_ROOT/artifacts` and
`PROJECT_ROOT/output` were always writable - true locally and in a
container, false on Vercel. The first real deployment hit exactly this:

```
POST /api/generate
OSError: [Errno 30] Read-only file system: '/var/task/artifacts/blueprint.json'
```

Fixed in `src/config.py` / `api/service.py`, not worked around:

- `IS_VERCEL = bool(os.environ.get("VERCEL"))` (Vercel sets this
  automatically - no manual configuration needed) selects `RUNTIME_ROOT`:
  `/tmp/zaio-mock-eisa` on Vercel, the project root everywhere else (so
  local development and the CLI are completely unaffected - `RUNTIME_ROOT
  == PROJECT_ROOT` locally, meaning every path below resolves to exactly
  where it always did).
- **`ARTIFACTS_DIR`** (`<project>/artifacts`) stays the read-only location
  of the two PREBUILT, git-committed deployment assets -
  `reference-corpus-chunks.json` (the RAG corpus) and
  `reference-analysis.json` (blueprint metadata) - never written to at
  runtime.
- **`RUNTIME_ARTIFACTS_DIR`** / **`OUTPUT_DIR`** (`<RUNTIME_ROOT>/artifacts`
  / `.../output`) are where every runtime-WRITTEN file goes instead:
  `blueprint.json`, `generation-history.json`, `validation-report.json`,
  `quality-review.json`, and every generated paper/memo JSON/MD/PDF.
- `src.config.resolve_readable_artifact(filename)` finds the corpus/
  analysis wherever it actually is - a runtime-built copy (local dev
  before the first `analyze`) takes priority over the prebuilt one, which
  is the normal case everywhere else, Vercel included.
- `api.service.ensure_reference_analysis_ready()` no longer assumes
  `sdev/` is present: it returns immediately once it finds the prebuilt
  analysis (the Vercel case - see below), only falls through to real PDF
  ingestion when `sdev/` genuinely exists (local dev), and raises a clear,
  actionable error - never a confusing raw `FileNotFoundError` from deep
  inside PDF loading, and never silent ungrounded generation - if neither
  is available.

Regression tests: `tests/test_deployment_paths.py`, including one that
runs the **entire** `generate_paper_and_memo()` pipeline against a
`chmod`-genuinely-read-only simulated static directory with `sdev/`
pointed at a nonexistent path - the real Vercel constraint, reproduced for
real, not merely asserted about.

### `sdev/*.pdf` is intentionally NOT deployed to Vercel

`sdev/` stays in `.gitignore` ("never part of the GitHub submission") and
is never part of the Vercel build. This is by design, not an oversight:
the two prebuilt artifacts above (`reference-corpus-chunks.json` /
`reference-analysis.json`, both ~6,123 chunks / ~36KB respectively,
committed as the sole exceptions to `artifacts/` being gitignored) ARE the
production RAG corpus - real PDF ingestion never runs on Vercel, and never
needs to. The learner guides remain the only knowledge source either way:
the corpus IS their extracted, page-cited content, not a substitute for
it. Regenerate both together locally (`python -m src.cli analyze`) and
re-commit them whenever `sdev/` content changes.

### `vercel.json` (Services)

```json
{
  "services": {
    "frontend": { "root": "frontend/", "framework": "vite" },
    "backend": { "root": "./", "entrypoint": "api/app.py" }
  },
  "rewrites": [
    { "source": "/api/:path*", "destination": { "service": "backend" } },
    { "source": "/(.*)", "destination": { "service": "frontend" } }
  ]
}
```

One project, one shared domain, no CORS needed between the two (same-
origin) - `frontend/src/services/api.ts` defaults to same-origin `/api`
in a production build and only falls back to `http://127.0.0.1:8000` in
`vite dev` (`import.meta.env.DEV`), so `VITE_API_BASE_URL` does not need
to be set at all for this Services topology; it exists for a two-project
split or a different platform. `pyproject.toml`'s `[tool.vercel]
entrypoint = "api.app:app"` points Vercel at the FastAPI `app` instance in
`api/app.py`, since Vercel's zero-config entrypoint discovery only checks
the project root, `src/`, or `app/` - not `api/` (this project's `src/` is
the generation engine, not a Vercel entrypoint location, so this explicit
entrypoint avoids any ambiguity between the two).

### Generation history / result retrieval: a real, documented limitation

`/tmp` is per-Function-instance scratch space - not shared across
Vercel's auto-scaled concurrent instances, and not guaranteed to survive a
cold start. This means, on Vercel specifically:

- **Cross-paper novelty** (`artifacts/generation-history.json`, now under
  `/tmp`) is reliable within one warm instance's lifetime (the common
  case for a burst of nearby requests, per Vercel's Fluid compute instance
  reuse) but starts empty on a fresh/different instance - narrowing, never
  breaking, the novelty comparison window on that instance. See
  `api/service.py`'s `_GENERATION_HISTORY_PATH` docstring for the full
  reasoning.
- **`GET /api/results/{id}`** (and PDF downloads) read from the same
  `/tmp`-backed `OUTPUT_DIR` a prior `POST /api/generate` wrote to - a
  follow-up request landing on a different instance will 404 even though
  generation genuinely succeeded. `POST /api/generate`'s own response
  already carries a full summary (marks, validation, novelty, quality
  review status); only the full paper/memo JSON and PDF downloads depend
  on this second, same-instance-scoped request.

**This is stated plainly, not silently degraded or hidden.** Closing it
completely needs an external durable store (Vercel Blob, a KV/Postgres-
style store, ...) - intentionally NOT implemented without explicit
approval, per this deployment's minimal-footprint scope. Nothing above
produces incorrect output, a crash, or a leaked secret - the worst case is
a `GET` landing on the wrong instance and reporting "not found" for a
result that exists elsewhere, or a novelty check with a narrower-than-
ideal comparison set on a fresh instance.

### Required Vercel environment variables (Production)

Set in the Vercel dashboard, never in `vercel.json` or committed code:

| Variable | Value |
|---|---|
| `LLM_PROVIDER` | `groq` |
| `GROQ_API_KEY` | the real key (never printed/logged - see `src/security/redaction.py`) |
| `GROQ_MODEL` | `openai/gpt-oss-120b` |
| `REQUIRE_REAL_PROVIDER` | `true` - makes a missing/misconfigured key a hard failure instead of a silent MockProvider fallback (see `src/providers/factory.py`) |

`CORS_ALLOWED_ORIGINS` is not needed for the single-project Services
topology above (same-origin); set it only if the frontend and backend are
later split into two separate Vercel projects.

## Docker / any other platform

1. **A Python 3.11+ runtime** running `uvicorn api.app:app --host 0.0.0.0
   --port <PORT>` from the repository root (so `api`/`src` resolve as
   top-level importable packages - the same invocation `docs/API.md`'s
   local-development section uses, just bound to `0.0.0.0` instead of
   `127.0.0.1` so it is reachable from outside the container/host).

   A `Dockerfile` is provided at the repo root for this (see its own
   comments for what it copies and why). It runs as a dedicated non-root
   user (write access limited to `artifacts/`/`output/` only - everything
   else stays root-owned and read-only to the process), sets
   `PYTHONUNBUFFERED=1` so logs reach `docker logs` promptly, has no
   `--reload` (a local-dev-only flag), and includes a `HEALTHCHECK` against
   `GET /api/health`.

   **It has not been build-verified in this environment, twice checked** -
   the Docker CLI is installed here but no daemon is reachable
   (`docker build`/`docker info` both fail with "no such file or directory"
   on the daemon socket; no Docker Desktop application is installed
   either), so this remains a carefully-reasoned, STATICALLY-audited
   artifact, not a build- or run-verified one. Build and smoke-test it
   before trusting it in production:
   ```bash
   docker build -t zaio-backend .
   docker run -p 8000:8000 --env-file .env zaio-backend
   curl http://127.0.0.1:8000/api/health
   ```
   This is stated plainly rather than claiming a verification that did not
   happen.

2. **Environment variables** (see `.env.example` for the full documented
   list; never commit an actual `.env` - `git check-ignore -v .env` must
   show it ignored, and `git ls-files .env` must return nothing):
   - `LLM_PROVIDER=groq` (the current production provider) plus
     `GROQ_API_KEY` and `GROQ_MODEL=openai/gpt-oss-120b` - or `anthropic`/
     `gemini` with their matching key, if switching providers.
   - `CORS_ALLOWED_ORIGINS` - must include the frontend's real deployed
     origin (see `src/security/config.py`; defaults to local dev origins
     only, which will silently block a real deployed frontend's requests
     via CORS if left unchanged).
   - Everything else in `.env.example` has a working default; override
     only what the target environment actually requires.

3. **The `sdev/` learner-guide PDFs must be present in the deployed
   backend's filesystem.** They are the only knowledge source for
   generation (see `docs/DESIGN.md`) and are read at ingestion time
   (`src/ingestion/pdf_loader.py`) - if `artifacts/reference-analysis.json`
   does not already exist, the API's startup lifespan
   (`api/service.ensure_reference_analysis_ready`) parses all of `sdev/`
   on first boot (~48s, measured - see `docs/API.md`). The provided
   `Dockerfile` copies `sdev/` into the image (read-only source, copied in
   - never modified) for exactly this reason. **Do not modify, rename, or
   omit any file under `sdev/`** in any deployment path.

4. **Writable storage for `artifacts/` and `output/`.** These are NOT
   shipped in the image/deployment - they are produced at runtime:
   - `artifacts/reference-corpus-chunks.json` /
     `reference-analysis.json` - the parsed-PDF corpus cache. Rebuilt
     automatically on first startup if missing (costs the ~48s analysis
     pass again); persisting it (a mounted volume, or a platform's
     persistent disk) avoids paying that cost on every cold start/restart.
   - `artifacts/generation-history.json` - the cross-paper novelty memory
     (see `docs/DESIGN_NOTE.md` section D). **This one matters more than
     the corpus cache**: losing it on every restart does not break
     anything structurally, but it does silently forget every paper
     generated before the restart for novelty-comparison purposes - a
     real data-durability concern for a long-lived deployment, not just a
     performance one. Use a persistent volume/disk if the platform's
     filesystem is ephemeral across deploys/restarts (many are).
   - `output/` - generated paper/memo JSON, Markdown, and PDF files that
     `GET /api/results/{id}` and its PDF sub-resources serve back. Also
     needs to survive a restart for previously-generated results to
     remain fetchable; also benefits from a persistent volume/disk for the
     same reason.
   - Nothing else needs write access - the rest of the deployed
     filesystem (`sdev/`, `src/`, `api/`, `prompts/`, `schemas/`,
     `configs/`) is read-only at runtime by design.

5. **A generous request timeout on any reverse proxy / platform edge in
   front of this API for `/api/generate` specifically.** With the real
   provider configured, one `/api/generate` call can legitimately take
   anywhere from a few seconds to several minutes (up to 13 sequential
   provider calls with their own bounded retries - see `docs/API.md`,
   "Why generation is synchronous"). A short platform-default timeout
   (many default to 30-60s) will kill a legitimately-still-working request
   before the backend itself gives up, which the client will experience
   indistinguishably from a real failure.

6. **Groq's daily token quota is a real, external constraint** (observed:
   200,000 tokens/day on the tier used during development - see
   `docs/SECURITY-AUDIT.md`'s 2026-09-10 update for a real incident this
   caused). When exhausted, `/api/generate` fails safely and immediately
   with a 502 (`GENERATION_FAILED`/`PROVIDER_ERROR`, a generic client-safe
   message, full diagnostic detail server-side only - see `api/errors.py`)
   until the quota resets; this is not something a deployment can engineer
   around beyond upgrading the Groq tier or switching providers.

## Frontend: what a deployment needs to provide

A static site host serving `frontend/dist/` (produced by `npm run build`
inside `frontend/`) is sufficient - there is no server-side rendering and
no backend logic in the frontend build. One environment variable matters:

- `VITE_API_BASE_URL` - the deployed backend's real, publicly-reachable
  URL (e.g. `https://your-backend.example.com`), set at BUILD time (Vite
  inlines `VITE_`-prefixed variables into the built JS bundle - see
  `frontend/.env.example`). Left unset, `frontend/src/services/api.ts`
  falls back to `http://127.0.0.1:8000` **only in a dev server build**
  (`import.meta.env.DEV`) and to same-origin `/api` in a production
  build - correct, zero-config behavior for the Vercel Services topology
  above (frontend and backend share one domain), where this variable does
  not need to be set at all. Set it explicitly only when the frontend and
  backend are NOT on the same origin (a two-project split, or a non-Vercel
  platform serving them separately).
- If the frontend and backend are NOT same-origin, ensure the backend's
  `CORS_ALLOWED_ORIGINS` (above) includes this frontend's real deployed
  origin, or every request will be blocked by the browser's CORS check
  even though the backend itself is healthy and reachable.

## Local development note: the `localhost` vs `127.0.0.1` failure mode

A real, observed local failure (see `docs/SECURITY-AUDIT.md`'s update and
`frontend/.env.example`): on a machine where another unrelated local
process is already bound to port 8000 on the IPv6/wildcard address,
`http://localhost:8000` can silently resolve to and be answered by that
OTHER process instead of this backend - not a crash, not a CORS error,
just the wrong server responding, which the frontend surfaces as a generic
"Something went wrong" error with no useful detail (see `api.ts`). This is
purely a local-development networking ambiguity - it does not occur in a
real deployment, where the frontend is configured with the backend's real,
specific `VITE_API_BASE_URL` rather than resolving an ambiguous hostname.
Locally, prefer `127.0.0.1` explicitly (both the backend's own
`--host 127.0.0.1` and the frontend's `VITE_API_BASE_URL` already default
to this - see `docs/API.md` and `frontend/.env.example`), and if Generate
ever reaches the backend but consistently fails with no useful detail,
check `lsof -nP -iTCP:8000 -sTCP:LISTEN` for a port collision before
assuming the application code is at fault.

## What is deliberately NOT included here

- No CI/CD pipeline config (GitHub Actions, etc.) - not requested, and
  inventing one against an unconfirmed target platform/registry would be
  exactly the kind of unverified, presumptive addition this document
  avoids elsewhere.
- No deployment manifest for any platform OTHER than Vercel (`render.yaml`,
  a `Procfile`, Kubernetes manifests, ...) - the `Dockerfile` is the one
  artifact general enough to be useful regardless of which non-Vercel
  platform is chosen; a second platform-specific manifest would be exactly
  the kind of unverified, presumptive addition this document avoids.
- No database or other external persistent store - see "Generation
  history / result retrieval" above for the real, documented limitation
  this implies on Vercel specifically, and why closing it needs one.
