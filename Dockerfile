# Backend-only image (FastAPI + generation engine). The frontend
# (frontend/) is a static Vite build with no server-side logic of its own
# (see frontend/README.md) - it deploys to any static host/CDN and does
# not need a container; this Dockerfile is deliberately scoped to the one
# piece that actually needs a long-running process.
#
# This is intentionally the MINIMUM viable container, not a guess at any
# specific hosting platform (Railway/Render/Fly/ECS/a plain VPS can all run
# a plain Dockerfile identically) - see docs/DEPLOYMENT.md for the full
# deployment architecture, required environment variables, and the
# reasoning behind not committing to one platform's config format here.
FROM python:3.13-slim

# PYTHONUNBUFFERED: without this, Python buffers stdout/stderr when it's
# not an interactive TTY (always true in a container) - uvicorn's and this
# project's own logging (api/middleware.py, api/errors.py) would sit in a
# buffer instead of reaching `docker logs`/the platform's log collector
# promptly, which matters for diagnosing a failure in something closer to
# real time.
# PYTHONDONTWRITEBYTECODE: no .pyc files written into the image's writable
# layer - a short-lived container gains nothing from caching bytecode
# across a restart, and it's noise in `docker diff`/layer inspection.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first (own layer) so an application code change doesn't
# invalidate the (slow) dependency-install layer on every rebuild.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code and the static resources the engine reads at runtime -
# never a wildcard `COPY . .`, so nothing outside this explicit list
# (notably .env, .git, node_modules, artifacts/, output/, tests/) ever
# enters the image, secrets included.
COPY api/ api/
COPY src/ src/
COPY configs/ configs/
COPY prompts/ prompts/
COPY schemas/ schemas/
COPY docs/ docs/

# sdev/ - the learner-guide PDFs - IS copied in: real ingestion/retrieval
# at runtime needs them present in the deployed container (see
# docs/DEPLOYMENT.md, "Learner-guide corpus availability"). They are
# read-only source material to this pipeline both locally and here; this
# COPY does not modify sdev/ in the repository, it only places a copy of
# its current committed contents into the image.
COPY sdev/ sdev/

# artifacts/ (corpus cache + generation history) and output/ (generated
# papers/memos) are produced at runtime, not shipped in the image - see
# docs/DEPLOYMENT.md for why a persistent volume matters for these on a
# real deployment (an ephemeral filesystem means a container restart loses
# both the corpus cache, which just gets rebuilt on next startup at the
# cost of the ~48s analysis pass, and generation history, which is a real
# loss of cross-paper novelty memory - not a correctness bug, a data-
# durability one).
RUN mkdir -p artifacts output

# Run as a dedicated non-root user, not the image default (root) - standard
# container hardening: a compromised or misbehaving process inside the
# container gets only this user's privileges, not root's. Ownership is
# granted ONLY over the two directories this process actually writes to at
# runtime (artifacts/, output/) - deliberately `chown` of just those two,
# not a recursive `chown -R /app`, so every other copied-in path (sdev/,
# src/, api/, prompts/, schemas/, configs/, docs/) stays owned by root and
# genuinely read-only to appuser (world-readable from COPY's default
# permissions is enough for this process to read them; it never needs to
# write to them - see docs/DEPLOYMENT.md, "Writable storage").
RUN useradd --create-home --uid 1000 appuser && chown appuser:appuser artifacts output
USER appuser

EXPOSE 8000

# A liveness check any orchestrator (Docker Compose, Kubernetes, a
# platform's own health probe) can use out of the box - hits the same
# GET /api/health real clients/the frontend use, which by design returns
# only a fixed, safe status string (see api/routes/health.py) and touches
# no external dependency (no Groq call, no filesystem read), so it never
# reports "unhealthy" merely because Groq's quota is exhausted or a real
# generation is slow - see docs/API.md's "Why generation is synchronous"
# for why /api/generate itself would be the wrong endpoint for this.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status == 200 else 1)"

# --host 0.0.0.0: required for the process to be reachable from outside
# the container at all (unlike local development's deliberate
# `--host 127.0.0.1`, which exists specifically to avoid the port-
# collision failure mode documented in docs/DEPLOYMENT.md and README.md
# #17 - that reasoning is about avoiding an ambiguous *host machine*
# loopback address, not about container networking, where 0.0.0.0 inside
# the container is the normal and necessary choice). No --reload: that
# flag is strictly a local-development convenience (re-imports the app on
# every file change, via a separate watcher process) and has no place in a
# production container - deliberately absent here, not merely defaulted.
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
