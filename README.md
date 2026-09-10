# Zaio Mock EISA Generation Pipeline - Phase 1 (Software Developer)

An AI-powered pipeline that turns supplied QCTO reference material into a
new, original Mock EISA (External Integrated Summative Assessment) practice
paper and its complete marking memo, for the **Occupational Certificate:
Software Developer** qualification (SAQA ID 118707) only.

## 1. Project purpose

Given a folder of reference training material for a qualification, produce:

1. A structured analysis of what that material actually establishes about
   the qualification and its assessment (facts vs. assumptions vs. unknowns).
2. A machine-readable assessment **blueprint** (sections, marks, duration,
   outcomes) derived from that analysis plus explicitly-documented
   assumptions where the source is silent.
3. One complete, original **Mock EISA paper** and its **marking memo**,
   generated against that blueprint - never copied or lightly reworded from
   the reference material.
4. A battery of deterministic validators plus a novelty/overlap screen and
   an LLM quality-review pass, so nothing ships unchecked.
5. Human-readable Markdown (and optional PDF) renderings of both documents.

## 2. Phase 1 scope

**In scope**: Software Developer qualification only, one qualification
config, one generated paper + memo, the full pipeline architecture,
deterministic validation, a lexical novelty checker, tests, docs.

**Explicitly out of scope** (do not look for these here): Cybersecurity or
Data Science qualifications, student accounts, authentication, a real
database, an admin dashboard, or production deployment.

**Phase 2 addition**: a thin FastAPI HTTP layer (`api/`) around the
still-frozen Phase 1 engine - see `docs/API.md` and §17 below.

**Phase 3 addition**: a React/TypeScript/Vite frontend (`frontend/`) that
talks only to the Phase 2 API - see §18 below.

## 3. Architecture

See [`docs/DESIGN.md`](docs/DESIGN.md) for the full design rationale
(prompt strategy, anti-copying approach, security boundaries, why this
shape fits a Phase 1 timebox). In one line: **deterministic reference
analysis -> deterministic blueprint -> small per-question LLM calls ->
deterministic validation -> LLM quality review -> deterministic rendering.**
Nothing in the deterministic stages ever calls an LLM; nothing in the LLM
stages is trusted for structure (IDs, marks, coverage) without a
downstream check.

## 4. Directory structure

```
sdev/                    # SUPPLIED SOURCE MATERIAL - read-only, never modified, gitignored
src/
  cli.py                 # argparse CLI: analyze / generate / validate / review / render / pipeline
  config.py              # env/config loading, safe path handling
  ingestion/pdf_loader.py        # recursive, read-only PDF/DOCX/TXT extraction
  analysis/reference_analyzer.py # deterministic regex parse of the QCTO Learner Guide format
  analysis/report_writer.py      # writes docs/reference-analysis.md + artifacts/reference-analysis.json
  generation/blueprint.py        # analysis + config -> assessment blueprint
  generation/question_generator.py
  generation/memo_generator.py
  generation/llm_utils.py        # shared prompt-loading / JSON-extraction helpers
  providers/base.py, mock_provider.py, anthropic_provider.py, factory.py
  validation/schema_validator.py, marks_validator.py, coverage_validator.py,
             novelty_checker.py, quality_reviewer.py, types.py
  rendering/markdown_renderer.py, pdf_renderer.py
  models/schemas.py
  security/config.py       # single source of truth for all security thresholds
  security/rate_limiter.py # reusable rate limiter - used by api/, and CLI-safe on its own
  security/redaction.py    # secret redaction (wired into the CLI AND the API's error handlers)
  validation/orchestrator.py  # shared schema->marks->coverage->novelty sequence (used by cli.py AND api/service.py)
api/                       # Phase 2: thin FastAPI layer around src/ - see docs/API.md
  app.py                   # app factory, lifespan, middleware wiring
  service.py                # orchestrates src/ calls for the API (no duplicated logic)
  models.py, dependencies.py, middleware.py, errors.py, results.py
  routes/health.py, generate.py, results.py
prompts/                  # real prompt text sent to the LLM provider (system+user, templated)
schemas/                  # JSON Schema for the paper and the memo
configs/software_developer.json   # the ONLY place numeric assumptions live
artifacts/                # reference-analysis.json, blueprint.json, validation-report.json, ...
output/                   # mock-eisa-paper-02.{json,md,pdf}, mock-eisa-memo-02.{json,md,pdf}
tests/                     # tests/test_api_*.py cover the API layer
frontend/                 # Phase 3: React/TypeScript/Vite SPA - talks only to api/, see §18
  src/{components,pages,services,types,hooks,styles}/
docs/reference-analysis.md, docs/DESIGN.md, docs/SECURITY-AUDIT.md, docs/API.md
requirements.txt          # runtime dependencies (now includes fastapi, uvicorn)
requirements-dev.txt       # dev-only tooling (pytest, httpx, pip-audit, bandit, ruff, mypy, type stubs)
```

## 5. Setup instructions

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 6. Environment variables

Copy `.env.example` to `.env` and edit as needed (never commit `.env`):

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `LLM_PROVIDER` | no | `mock` | `mock` (offline, deterministic - always used by automated tests, regardless of this setting), `groq` (real API, current production provider), `anthropic` (real API), or `gemini` (real API) |
| `GROQ_API_KEY` | only if `LLM_PROVIDER=groq` | - | Groq API key from https://console.groq.com/ |
| `GROQ_MODEL` | no | `openai/gpt-oss-120b` | model id |
| `ANTHROPIC_API_KEY` | only if `LLM_PROVIDER=anthropic` | - | Anthropic API key. **Not** the same thing as a Claude Pro/Max subscription - an API key is a separate, billed credential from https://console.anthropic.com/. |
| `ANTHROPIC_MODEL` | no | `claude-sonnet-5` | model id |
| `GEMINI_API_KEY` | only if `LLM_PROVIDER=gemini` | - | Gemini API key from https://aistudio.google.com/ |
| `GEMINI_MODEL` | no | see `.env.example` | model id |
| `LLM_MAX_TOKENS` | no | `4096` | per-call cap |
| `LLM_TEMPERATURE` | no | `0.4` | per-call sampling temperature |

`.env.example` also documents ~15 security-configuration variables (max
file sizes/counts, retry limits, provider timeout, CLI numeric bounds, and
rate-limit settings) - all optional with safe defaults; see
`src/security/config.py` and `docs/SECURITY-AUDIT.md` for what each one
protects.

Real generation with the configured provider has been exercised
end-to-end (`output/mock-eisa-paper-01.*`/`-02.*` were produced by real
Groq calls, `generation_meta.provider: "groq"`, not `MockProvider`) - see
§16 "Known limitations" for the one real operational constraint this
surfaced (Groq's daily token quota).

## 7. Installation

```bash
pip install -r requirements.txt
```

Installs: `jsonschema`, `pypdf`, `python-docx`, `anthropic`, `reportlab`,
`pytest`. All are needed for the mock-provider path except `anthropic`
(only used if you configure a real key) and `reportlab` (only used for
optional PDF rendering - Markdown/JSON output works without it).

## 8. CLI usage

```bash
python -m src.cli analyze
python -m src.cli generate --qualification software_developer --paper-number 2 --seed 20260906
python -m src.cli validate --paper output/mock-eisa-paper-02.json --memo output/mock-eisa-memo-02.json
python -m src.cli review   --paper output/mock-eisa-paper-02.json --memo output/mock-eisa-memo-02.json
python -m src.cli render   --paper output/mock-eisa-paper-02.json --memo output/mock-eisa-memo-02.json --pdf
python -m src.cli pipeline --qualification software_developer --paper-number 2 --seed 20260906 --pdf
```

`pipeline` runs `analyze -> generate -> validate -> review -> render` in one
command and stops immediately (non-zero exit) if any deterministic stage
fails.

## 9. Generation workflow

1. `analyze` extracts every file under `sdev/` (read-only) and writes:
   - `docs/reference-analysis.md`, `artifacts/reference-analysis.json`
   - `artifacts/reference-corpus-chunks.json` (novelty-checker cache)
2. `generate` merges `artifacts/reference-analysis.json` with
   `configs/software_developer.json` into `artifacts/blueprint.json`, then
   makes one provider call per section (question) and one per question
   (memo), writing `output/mock-eisa-{paper,memo}-NN.json`.

## 10. Validation workflow

`validate` loads a paper+memo pair and runs, in order: JSON Schema
validation, mark-arithmetic and memo-coverage checks, blueprint outcome/
competency coverage, and the lexical novelty screen - writing a single
`artifacts/validation-report.json` with a `passed` flag and a flat list of
named checks. Exit code is non-zero if anything failed. `review` runs the
separate LLM quality-review pass and writes `artifacts/quality-review.json`.

## 11. Output structure

| File | Contents |
|---|---|
| `output/mock-eisa-paper-02.json` | Machine-readable paper (primary artifact) |
| `output/mock-eisa-paper-02.md` / `.pdf` | Human-readable paper |
| `output/mock-eisa-memo-02.json` | Machine-readable memo |
| `output/mock-eisa-memo-02.md` / `.pdf` | Human-readable memo |
| `artifacts/reference-analysis.json` | Compact reference analysis |
| `artifacts/blueprint.json` | Assessment blueprint |
| `artifacts/validation-report.json` | Deterministic validation results |
| `artifacts/quality-review.json` | LLM quality-review results |
| `artifacts/reference-corpus-chunks.json` | Novelty-checker text index |

## 12. Testing

```bash
python -m pytest tests/ -v
```

168 tests (125 engine + 43 API), all offline (`MockProvider` and FastAPI's
`TestClient` only - **the suite runs without any paid API access and
without a running server**). The frontend has its own, separate test
suite - see §18 and `frontend/README.md`. Engine tests cover: reference ingestion
(extraction, corrupt-file handling, never-writes-to-source,
file-count/filename/size bounds), path-traversal safety (including
symlink escapes and the guarantee that no output path can land inside
`sdev/`), qualification config validation/scope enforcement, JSON Schema
validation (including upper bounds on size/length/count), mark arithmetic,
memo/paper consistency, blueprint outcome coverage (including the
regression guard against tautological coverage), duplicate IDs,
malformed/adversarial LLM output handling, bounded retries, secret
redaction, PDF-rendering injection safety, prompt-injection delimiter
presence, and the novelty checker. API tests (`tests/test_api_*.py`) cover
every endpoint's valid/invalid inputs, rate limiting, CORS, security
headers, request IDs, path-traversal/sdev-access attempts, and
secret/traceback-leakage prevention - see `docs/API.md`.

## 13. Security considerations

A dedicated security audit and hardening pass was completed - see
**`docs/SECURITY-AUDIT.md`** for the full threat model, findings (with
severity and remediation), dependency audit (`pip-audit`: no known
vulnerabilities), and static analysis results (`bandit`, `ruff --select S`,
`mypy`). Highlights, all **implemented and tested now**:

- `sdev/` is opened read-only everywhere; ingestion is bounded (max file
  size/count/filename length, all configurable - `src/security/config.py`).
- All CLI-supplied paths are checked against path traversal
  (`src/config.safe_path_within`), including symlink-based escapes.
- No secret is hard-coded or logged; `src/security/redaction.py` strips
  credential-shaped text from every CLI error message, including for
  exception types not explicitly anticipated.
- No generated or candidate code is ever executed by this pipeline; PDF
  rendering XML-escapes all content before it reaches reportlab's markup
  parser (previously a real, verified crash/injection risk - see audit
  6.1).
- Provider output is bounded in size before parsing, and retries around
  provider calls are capped and never applied to deterministic content
  defects (`src/generation/llm_utils.call_provider_with_retry`).
- Reference-derived text (e.g. Knowledge Topic titles) is length-capped and
  control-character-stripped before it can reach an LLM prompt; every
  prompt template delimits untrusted reference data explicitly.
- Network access is opt-in and confined to `AnthropicProvider`.
- The rate limiter (`src/security/rate_limiter.py`), prepared but unwired
  in Phase 1, is now **actively enforced** on every API endpoint (§17,
  `docs/API.md`) - the same component, no second implementation.

## 14. Anti-copying strategy

Three independent layers - authorial discipline in the prompts/mock
content, a local lexical TF-IDF/cosine novelty screen against the full
reference corpus, and an LLM quality-review pass asked to flag anything
that "reads as copied." None of these alone is proof of originality; see
`docs/DESIGN.md`, "Anti-copying approach and its limits," for exactly what
the novelty checker does and does not catch.

Generation is also retrieval-grounded: each question is generated against
real, page-cited passages retrieved from `sdev/` (not just a topic name),
checked for grounding at generation time and independently re-checked at
`validate` time, and checked against every earlier paper's questions for
the same section so a later paper cannot collapse into an earlier one. See
`docs/DESIGN_NOTE.md` for the full mechanism with a real worked example.

## 15. Reproducibility

`configs/software_developer.json` is the only place assessment structure
(sections/marks/duration) is defined; a future paper needs no code changes:

```bash
python -m src.cli generate --qualification software_developer --paper-number 3 --seed 20270101
```

With the real provider, different seeds let the model produce genuinely new
scenario content while marks/outcomes/structure stay governed by the same
blueprint. With the default `MockProvider` (deterministic/offline, no API
access), different seeds instead pick between a small, fixed set of
hand-written fixture variants per section (currently 2) - see
`docs/DESIGN.md`, "Reproducibility," for exactly what that means and its
limits, how to add a real new variant, and how to switch to the real
Anthropic provider (no code change, only `.env`).

## 16. Known limitations

- **Real generation is live.** `LLM_PROVIDER=groq` (model
  `openai/gpt-oss-120b`) is the configured production provider - real Groq
  calls have produced `output/mock-eisa-paper-01.*`/`-02.*` end-to-end
  (question RAG, answer RAG, grounding, marks, coverage, novelty, review,
  rendering all against real model output, not fixtures); their
  `generation_meta.provider` is `"groq"`, never `"mock"`.
  `AnthropicProvider` and `GeminiProvider` are also implemented and wired
  through `src/providers/factory.py` (set `LLM_PROVIDER=anthropic` /
  `gemini` plus the matching API key to use either instead). `MockProvider`
  remains the deterministic, offline, FIXTURE-based provider (2
  hand-written scenario variants per section, selected by `seed % 2`) used
  by every automated test (`tests/conftest.py` forces it regardless of
  `.env`) and by any developer without a configured key - it is not a
  generation engine and is never used for a real paper.
  **Known real-provider constraint**: Groq's free tier enforces a daily
  token quota (observed limit: 200,000 tokens/day); once exhausted,
  `/api/generate` fails safely with a 502 and a generic message (never a
  raw provider error) while the full diagnostic detail, including the
  quota reset ETA Groq reports, is logged server-side only (see
  `api/errors.py`) - this is an external quota limit, not a bug, and
  resolves automatically when the quota resets.
- **No official QCTO assessment specification was supplied.** Exam
  duration, total marks, section count, pass mark, and candidate
  instructions are Phase 1 implementation assumptions
  (`configs/software_developer.json`), not facts from `sdev/`. See
  `docs/reference-analysis.md` sections 5 and 10-11.
- **The novelty checker is a lexical screen, not a copying proof** - see
  `docs/DESIGN.md` for what it does and doesn't catch.
- **PDF rendering is best-effort** (via `reportlab`); Markdown and JSON are
  the primary human/machine-readable artifacts and never depend on PDF
  rendering succeeding.
- **Only one qualification, one paper, one seed's worth of content variants
  per section** are implemented for Phase 1, per the brief's scope. Adding
  a second qualification means adding a `configs/<name>.json` and extending
  `SUPPORTED_QUALIFICATIONS` in `src/config.py` - no other architectural
  change is required, but it has not been done here.

## 17. API layer (Phase 2)

A thin FastAPI HTTP layer (`api/`) around the same, unmodified engine
described above. Full architecture, endpoint reference, security model,
and known limitations: **[`docs/API.md`](docs/API.md)**. Quick start:

```bash
pip install -r requirements.txt -r requirements-dev.txt
uvicorn api.app:app --reload
```

```bash
curl http://127.0.0.1:8000/api/health
curl -X POST http://127.0.0.1:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"qualification": "software_developer", "paper_number": 900, "seed": 20260906, "pdf": true}'
curl http://127.0.0.1:8000/api/results/900
curl http://127.0.0.1:8000/api/results/900/paper.pdf -o paper.pdf
```

Use a high `paper_number` (900+) for ad-hoc/manual testing like the example
above - `paper_number` doubles as the output filename and cross-paper
novelty history key (`mock-eisa-paper-<NN>.json`,
`artifacts/generation-history.json`), so a low number here would overwrite
a real canonical paper and pollute its novelty history; see
`tests/test_api_generate.py`'s module docstring for the same convention
applied to the automated test suite.

`localhost` vs `127.0.0.1`: if another local process is also bound to port
8000 on this machine (a real, observed situation - see
`frontend/.env.example`'s note on this), `http://localhost:8000` can
resolve to the WRONG server depending on IPv4/IPv6 resolution order. Prefer
`127.0.0.1` explicitly, as the examples above do, when in doubt.

The CLI is unaffected and continues to work exactly as before - the API
is an additional way to drive the same engine, not a replacement for it.
`tests/test_api_*.py` covers the API layer independently of the rest of
the engine's tests; run the whole suite with `python -m pytest tests/ -v`
as before (see `docs/API.md` for current counts - not repeated here to
avoid this README going stale every time a test is added).

## 18. Frontend (Phase 3)

A React + TypeScript + Vite single-page app in `frontend/` that talks only
to the API described above - it holds no assessment-generation logic of
its own, no filesystem paths, and no secrets (see `frontend/README.md` for
full setup). Quick start (with the API already running per §17):

```bash
cd frontend
npm install
cp .env.example .env.local   # sets VITE_API_BASE_URL, defaults to http://127.0.0.1:8000
npm run dev                  # http://localhost:5173
```

It lets you generate a new paper+memo (qualification, paper number, seed,
optional PDF), or look up an already-generated result by paper number, and
then browse the paper and marking memo and download their PDFs - all via
the four `/api/*` endpoints in §17, nothing else. `npm run test` runs its
Vitest suite (component + service-layer tests, including error-path
coverage for validation/rate-limit/server/network failures); `npm run
build` produces a static `dist/` bundle.

## 19. Deployment

Local development runs the backend and frontend as two separate processes
(§17-18 above); deploying either beyond your own machine is a separate
concern with its own requirements (environment variables, the `sdev/`
corpus's availability to the deployed backend, persistent storage for
generated results, CORS, request timeouts for real-provider generation) -
see **[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)** for the full
architecture and a from-repo-root `Dockerfile` for the backend.
