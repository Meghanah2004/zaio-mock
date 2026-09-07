# Security Audit - Phase 1 Mock EISA Pipeline

Audit date: 2026-09-06. Scope: `src/`, `tests/`, `prompts/`, `schemas/`,
`configs/`, `requirements.txt`, `pyproject.toml`, `.env.example`,
`.gitignore`, `README.md`, `docs/DESIGN.md`, and the installed dependency
tree. This document records what was actually found by inspection and by
running real tools (`pip-audit`, `bandit`, `ruff --select S`, `mypy`) against
this codebase - no finding below is hypothetical or invented.

**Application shape at audit time**: a local, single-user CLI tool. There is
no HTTP server, no network listener, no authentication, and no database.
Every control described as "PREPARED FOR FUTURE API" is implemented and
tested now, but not wired into anything live, because there is nothing live
to wire it into yet. This distinction is maintained throughout this
document and must not be blurred in future reporting.

## 1. Threat model

| Actor | Capability | Motivation |
|---|---|---|
| The operator running the CLI | Full local shell access already | N/A - trusted by definition on a local machine |
| Author of a supplied reference document (`sdev/`) | Can shape file content/names before ingestion | Could attempt prompt injection, resource exhaustion, or malformed-content attacks against the analysis/generation pipeline if a malicious or corrupted file were ever substituted |
| The configured LLM provider (Anthropic API, or a future third-party provider) | Returns arbitrary text in response to prompts | Could return malformed, oversized, or adversarially-crafted JSON (a compromised or buggy provider, or a prompt-injected response) |
| A future API client / frontend user (not yet built) | Would be able to submit qualification/paper-number/seed/paths over HTTP | Could attempt path traversal, oversized payloads, repeated expensive generation calls, or malformed input once that surface exists |

The realistic near-term threat is **not** a remote attacker (there is no
listening service) - it is **malformed or adversarial input reaching a
trust boundary this pipeline does cross today**: reference file content,
provider (LLM) output, and CLI arguments. The audit and hardening below is
weighted accordingly, while also preparing (and testing) the pieces a
future API layer will need.

## 2. Assets

- The supplied reference material (`sdev/`) - read-only, must never be
  modified, deleted, or exfiltrated in an unintended way.
- The generated assessment artifacts (`output/`, `artifacts/`) - integrity
  matters (marks must reconcile, content must be attributable to this
  pipeline, not silently corrupted).
- The `ANTHROPIC_API_KEY` (when configured) - must never be logged,
  echoed, or leaked in an error message.
- The local filesystem outside the project directory - must never be
  written to or read from as a side effect of a crafted path.
- Compute/API budget - unbounded retries or unbounded generation could
  waste real money against a paid LLM API once one is configured.

## 3. Trust boundaries

```
sdev/ (UNTRUSTED CONTENT)  --ingestion-->  extracted text (UNTRUSTED)
                                              |
                                    regex-based analysis (deterministic)
                                              |
                                 artifacts/reference-analysis.json (TRUSTED, derived)
                                              |
                                blueprint (config + analysis, TRUSTED)
                                              |
                          prompts/*.txt (SYSTEM POLICY, TRUSTED, authored by us)
                                              |
                                    LLM provider call
                                              |
                              raw provider output (UNTRUSTED)
                                              |
                json parse -> schema validate -> marks/coverage validate -> novelty screen -> quality review
                                              |
                                  paper/memo JSON (TRUSTED, only after all gates)
                                              |
                                  Markdown / PDF rendering
```

Every arrow crossing from an UNTRUSTED node is a boundary this audit
checked for missing validation. CLI arguments (`--paper`, `--memo`,
`--qualification`, `--paper-number`, `--seed`) are a second, independent
boundary (user input, even though the "user" is the local operator).

## 4. Attack surfaces (current, CLI-only)

1. **File ingestion** (`src/ingestion/pdf_loader.py`) - reads every file
   under `sdev/`, recursively, by extension.
2. **Reference text parsing** (`src/analysis/reference_analyzer.py`) - regex
   extraction over untrusted PDF text.
3. **CLI arguments** (`src/cli.py`) - `--paper`, `--memo`, `--qualification`,
   `--paper-number`, `--seed`.
4. **Provider responses** (`src/providers/*.py`) - both `MockProvider`
   (fixed, trusted fixture content - low risk) and `AnthropicProvider`
   (arbitrary text from a live API - higher risk in principle).
5. **JSON parsing of provider output** (`src/generation/llm_utils.py`).
6. **Config/schema file loading** (`configs/*.json`, `schemas/*.json`) -
   trusted (shipped with the repo), but loaded with the same `json.load`
   path as everything else, so malformed-JSON handling matters here too.
7. **Rendering** (`src/rendering/markdown_renderer.py`,
   `src/rendering/pdf_renderer.py`) - takes validated paper/memo content and
   produces `.md`/`.pdf` files.

**Attack surfaces that do NOT exist yet** (and are explicitly out of scope
to fabricate): HTTP endpoints, authentication, file upload over a network,
CORS, a database. Section 12 below prepares controls for when they arrive.

## 5. Existing controls (present before this hardening pass)

- `src/ingestion/pdf_loader.py` never writes, deletes, or modifies
  anything under its input directory; extraction failures are caught
  per-file (`try/except Exception`) and reported, not raised.
- `src/config.safe_path_within` rejects both relative traversal
  (`../../etc/passwd`) and absolute-path escapes for CLI-supplied paths.
- Extension allow-list (`SUPPORTED_EXTENSIONS`) in ingestion.
- JSON Schema validation (`schemas/paper.schema.json`,
  `schemas/memo.schema.json`) gates every generated paper/memo before any
  other processing.
- Deterministic mark-arithmetic, coverage, and duplicate-ID validators -
  LLM output is never trusted for governance fields (ids, marks, section
  totals); these are computed/assigned by code and cross-checked.
- No `eval`/`exec`/`subprocess`/`os.system`/`pickle`/`yaml.load` anywhere in
  `src/` (confirmed by grep across the whole tree - zero matches).
- `ANTHROPIC_API_KEY` is read once from the environment and never printed;
  `AnthropicProvider` wraps SDK exceptions without including the key.
- `.env` is gitignored; `.env.example` contains placeholders only.
- Reference document text never enters an LLM prompt (analysis is
  regex-based, not LLM-based) - the primary prompt-injection vector is
  structurally absent in Phase 1's actual data flow.

## 6. Vulnerabilities / gaps found, severity, and remediation

Each item below states whether it was **FIXED** in this hardening pass or
is **DOCUMENTED / DEFERRED** with a stated reason.

### 6.1 [MEDIUM] PDF rendering interprets unescaped provider/LLM text as markup

**Finding**: `src/rendering/pdf_renderer.py` passed line text directly into
`reportlab.platypus.Paragraph`, which parses a mini-XML/HTML-like markup
language. Verified empirically:

```
Paragraph("unterminated <tag", ...) -> ValueError: paraparser: syntax error: parse ended with 1 unclosed tags
Paragraph("Tom & Jerry's <script>alert(1)</script>", ...) -> silently accepted, tag characters pass through uninterpreted as markup by this reportlab version, but NOT escaped
```

Two consequences: (a) any generated/candidate-adjacent text containing an
unterminated `<...` sequence crashes PDF rendering with an unhandled
`ValueError` (denial of the rendering feature, and an unhandled exception
propagating to the CLI's top level); (b) text resembling a tag reportlab
*does* recognize (`<b>`, `<br/>`, `<super>`, etc.) could alter rendered
layout in unintended ways if it ever appeared in provider output. This is
markup/template injection into the PDF renderer, not code execution -
reportlab's parser cannot execute code - but it is a real, verified
integrity/availability issue.

**Severity**: Medium (denial of a non-critical feature; no code execution;
no data exfiltration).

**Status**: **FIXED**. All text is now XML-escaped
(`xml.sax.saxutils.escape`) before being handed to `Paragraph`; the
intentional `**bold**` -> `<b>...</b>` conversion is applied *after*
escaping, on the escaped string, so it is the only markup that can ever
reach reportlab's parser. See `src/rendering/pdf_renderer.py`.

### 6.2 [LOW] Reference-derived text (KT titles) can reach a real LLM prompt unsanitized

**Finding**: Knowledge-Topic titles are extracted from `sdev/` PDF text by
regex (`src/analysis/reference_analyzer.py`) and are later interpolated
into `prompts/generate_questions.txt`'s user message (as the
"competencies"/"outcome codes" list) when `AnthropicProvider` is used. The
titles in the actual supplied corpus are benign curriculum text, but the
*mechanism* does not currently cap length, strip control characters, or
resist an adversarially-named knowledge topic in a future/different
reference corpus (e.g. a KT title engineered to look like an instruction).
This is a real, if currently low-probability, prompt-injection surface -
not an invented one, since the code path genuinely exists and genuinely
carries reference-derived text into a real LLM prompt.

**Severity**: Low today (current corpus is benign; MockProvider - what
this project actually runs - never sees this path at all, since it ignores
blueprint competency text and uses its own fixed content). Would become
Medium if a different/adversarial reference corpus were ever ingested and
`AnthropicProvider` used against it.

**Status**: **FIXED**. `_normalize_title` now caps length and strips
control characters (`src/analysis/reference_analyzer.py`); prompts now
wrap reference-derived data in explicit untrusted-data delimiters with a
literal instruction not to follow content inside them (see
`prompts/generate_questions.txt`, `prompts/generate_memo.txt`,
`prompts/review.txt`, and `docs/DESIGN.md` "Prompt-injection defense").

### 6.3 [LOW] No upper bounds in JSON Schema (only lower bounds existed)

**Finding**: `schemas/paper.schema.json` / `schemas/memo.schema.json` had
`minLength`/`minimum` constraints but no `maxLength`/`maximum`/`maxItems`.
A malformed or adversarial provider response (or a corrupted hand-edited
file) with a multi-megabyte string in `question`, or `marks: 999999999`,
would pass schema validation and only be caught later (if at all) by the
marks-reconciliation check, which would then simply fail loudly rather
than reject cleanly at the earliest boundary.

**Severity**: Low (would eventually be caught downstream; this is
defense-in-depth, not a live exploit path in the current single-user CLI).

**Status**: **FIXED**. Added `maxLength` (5000 for question/scenario/model
answers, 3000 for sub-question prompts, 1000 for memo criteria
descriptions), `maximum` (500 for question/section marks, 2000 for
`total_marks`, 100 for a single criterion/sub-question mark), and
`maxItems` (20 for sub_questions/criteria, 100 for outcomes/competencies,
20 for sections, 50 for instructions) to both schemas. Bounds are generous
enough that no legitimate exam content is rejected (see
`tests/test_schema_validator.py` regression tests).

### 6.4 [LOW] Reference ingestion had no cap on file count or filename shape

**Finding**: `load_reference_material` bounded individual file size (100MB
default) but not the total number of files walked, nor filename length or
character content. A reference directory with an extreme number of tiny
files, or a pathologically long filename, would be processed without
limit.

**Severity**: Low (local, single-operator context; `sdev/` is a fixed,
known directory, not user-uploaded over a network today).

**Status**: **FIXED**. `load_reference_material` now enforces a
configurable maximum file count and maximum filename length
(`src/security/config.py`), skipping and reporting (not silently ignoring)
anything over the limit.

### 6.5 [LOW] `AnthropicProvider` passed an unsupported SDK parameter

**Finding** (discovered via `mypy`, not a security tool, but relevant to
"the real provider must fail safely"): the installed `anthropic` SDK
(1.4.0) does not accept a top-level `temperature` keyword argument on
`messages.create()` - confirmed by inspecting the live method signature.
Every real call through `AnthropicProvider` would therefore fail on its
first attempt (caught and re-raised as a clean `LLMProviderError`, so it
would not crash uncontrolled or leak the key - but the real-provider path
was effectively unusable end-to-end, which matters for an LLM security
audit: a provider that always errors also always falls through error
paths, and those need to be as hardened as the success path).

**Severity**: Low/functional (not an exploitable vulnerability - the error
was already caught and sanitized - but a genuine robustness bug worth
fixing while auditing this exact boundary).

**Status**: **FIXED**. Removed the unsupported `temperature` argument from
the `.create()` call; `LLMSettings.temperature` is retained in
configuration (documented as currently unused by this SDK version, kept
for forward-compatibility and because it is a legitimate, harmless setting
to expose) rather than silently dropped from the config surface.

### 6.6 [INFO / false positive] `bandit` and `ruff --select S` both flag a string in `mock_provider.py`

**Finding**: Both tools flag `src/providers/mock_provider.py`'s Section-E
memo content (`B608 / S608 "possible SQL injection"`). Inspected: this is
a hard-coded **teaching string** - the memo text *for a question about
recognizing SQL injection* - which contains an f-string building example
SQL text for display, never executed, never touching a real database
connection anywhere in this codebase (confirmed: zero DB driver imports
anywhere in `src/`). This is a textbook static-analyzer false positive on
pattern-matched syntax, not a real vulnerability.

**Severity**: N/A (not a real finding).

**Status**: **DOCUMENTED, not modified** - changing this content would
degrade the exam question's own teaching material for no security benefit.

**Related false positive, fixed anyway**: `bandit` also flagged
`B406 (blacklist import of xml.sax)` on this pass's initial use of
`xml.sax.saxutils.escape` in `src/rendering/pdf_renderer.py` (section
6.1's fix). That function only substitutes 3 characters in a string - it
performs no XML parsing, so the XXE-class risk the rule exists for does
not apply. Rather than carry a second documented-false-positive line item,
the import was replaced with a 3-line hand-rolled `_xml_escape` helper
(identical behaviour, verified by the same test suite) - this fully
removes the noise rather than just explaining it away, at zero cost.

**Also fixed during this pass**: `bandit`'s `B101 (assert_used)` flagged
the retry loop in `src/generation/llm_utils.call_provider_with_retry`,
which used `assert last_error is not None` before re-raising. `assert` is
stripped under `python -O`, so relying on it for control flow (even
"impossible" defensive control flow) is bad practice. Replaced with an
explicit `if last_error is None: raise LLMProviderError(...)` fallback.

### 6.7 [INFO] No rate limiting, retry bounding, or resource caps existed on generation

**Finding**: There was no limit on how many times a caller could invoke
`generate`, no maximum retry count around provider calls, and no explicit
cap on provider response size before JSON parsing.

**Severity**: Low today (CLI-only, single operator, `MockProvider` makes no
network calls) - becomes real once a future API exists and/or a paid LLM
provider is configured.

**Status**: **PARTIALLY FIXED / PREPARED**:
- **Implemented now**: a bounded retry wrapper around provider calls
  (`src/generation/llm_utils.call_provider_with_retry`, configurable max
  attempts, only retries transient `LLMProviderError`s - never retries
  deterministic `GenerationError`s, since retrying identical invalid
  content cannot succeed and would waste API budget); a maximum raw
  provider-response size check before JSON parsing
  (`src/generation/llm_utils.extract_json`).
- **Prepared, not wired to anything live**: a reusable rate-limiter
  component (`src/security/rate_limiter.py`), fully implemented and
  tested, with no HTTP layer to attach it to yet - see section 12.

### 6.8 [INFO] CLI numeric arguments were unbounded

**Finding**: `--paper-number` and `--seed` accepted any integer, including
negative numbers, with no upper bound.

**Severity**: Low (not a path-traversal vector - these values are only
ever used inside `f"{n:02d}"`-style filename formatting under a fixed,
already-safe output directory, so no directory-escape was possible even
with a negative or huge value - but strict validation over silent
coercion is a stated principle, and unbounded ints are a poor input
contract).

**Status**: **FIXED**. Both arguments now validate against a configurable
range (`src/security/config.py`) and reject out-of-range values with a
clear CLI error before any file I/O happens.

## 7. Dependency audit

Ran `pip-audit` (v2.10.1) against the exact installed environment:

```
$ pip-audit
No known vulnerabilities found
```

Runtime dependencies and installed versions at audit time:

| Package | Installed | Known vulnerabilities |
|---|---|---|
| jsonschema | 4.26.0 | none found |
| pypdf | 6.17.0 | none found |
| python-docx | 1.2.0 | none found |
| anthropic | 1.4.0 | none found |
| reportlab | 5.0.1 | none found |
| pytest | 9.1.1 | none found (dev/test only) |

No dependency changes were made - there is nothing to upgrade. Dev-only
security tooling used for this audit (`pip-audit`, `bandit`, `ruff`,
`mypy`) is recorded in `requirements-dev.txt` with the exact versions used,
so this audit is reproducible; these are NOT added to `requirements.txt`
since they are not runtime dependencies of the application.

## 8. Static analysis results

**Final state, after this hardening pass** (re-run against the final code):

**bandit** (`bandit -r src/`): 1 finding, Medium severity / Low confidence -
the SQL-string false positive documented in 6.6. The `xml.sax` import
finding and the `assert`-in-control-flow finding that this same tool
surfaced against code written *during* this pass were both fixed outright
(see 6.6) rather than left as documented false positives, since fixing
them was free. Final run: **1 finding, a pre-existing documented false
positive, zero new findings**.

**ruff --select S** (flake8-bandit rule set): 1 finding - the same SQL
false positive, corroborating bandit. Zero new findings.

**mypy** (`mypy src/ --ignore-missing-imports`): 6 findings on the
pre-hardening codebase, of which:
- 1 was a real bug, fixed (6.5, the `temperature` argument).
- 2 are type-stub precision gaps in a redundant-but-safe regex pattern in
  `reference_analyzer.py` (mypy cannot correlate two separately-evaluated
  `re.search()` calls on the same immutable string as guaranteed
  consistent; manual review confirms this is not exploitable - the guard
  condition and the guarded access use the same deterministic input).
  Left as-is: fixing it would mean touching reference-analysis logic that
  has no security bearing, outside this task's scope of "don't modify
  unless a security issue directly requires it."
- 1 is a cosmetic `Optional`/lazy-import type-narrowing complaint in
  `pdf_loader.py` for the intentional `PdfReader = None` fallback pattern
  used when the optional dependency is absent - functionally correct,
  already partially suppressed, not a security issue.
- 1 is a return-type annotation looseness in `cli.py` (`ValidationReport`
  vs `dict`) - a type-precision issue with no runtime or security effect.

Re-run against the new/modified security-relevant files after hardening
(`src/security/`, `src/generation/llm_utils.py`,
`src/rendering/pdf_renderer.py`, `src/providers/anthropic_provider.py`,
`src/ingestion/pdf_loader.py`): the same `pdf_loader.py` finding, plus one
new instance of the identical type-narrowing pattern in
`anthropic_provider.py` (mypy cannot narrow the SDK's content-block union
type based on the existing runtime `getattr(block, "type", None) == "text"`
guard) - same category as the pre-existing findings above, not a new class
of issue, not fixed for the same reason (out of this task's scope, no
security bearing).

## 9. Residual risk (explicitly not fixed, and why)

- **Prompt-injection defense is architectural/tested, not battle-tested
  against a live model.** `MockProvider` (what this project actually runs)
  cannot be prompt-injected because it never interprets provider input as
  instructions in the first place - it is a fixed fixture. The delimiter
  and instruction hardening added in section 6.2 is real and testable, but
  its effectiveness against a genuinely adversarial live LLM response has
  never been exercised end-to-end, because no API key is configured in
  this environment. This is stated as a limitation, not resolved.
- **No malware/antivirus scanning of `sdev/` files.** Not available in
  this local environment; documented rather than fabricated (section
  headed "File upload security" below).
- **Rate limiting is implemented and tested but not attached to anything**,
  because nothing exists yet to attach it to. Wiring it in without an API
  would be fabricating a control - explicitly avoided per instructions.
- **mypy's remaining type-precision complaints** (section 8) are left
  unfixed as out-of-scope cosmetic issues with no verified security impact.

## 10. Summary table

| Area | Status |
|---|---|
| Reference isolation (`sdev/` read-only) | Implemented (pre-existing), re-verified |
| Path traversal prevention | Implemented (pre-existing `safe_path_within`), tests added |
| PDF markup injection | **Fixed this pass** |
| Reference-text injection into LLM prompts | **Fixed this pass** (sanitization + prompt delimiters) |
| Schema upper bounds | **Fixed this pass** |
| Ingestion file-count/filename limits | **Fixed this pass** |
| AnthropicProvider `temperature` bug | **Fixed this pass** |
| Bounded retries | **Fixed this pass** |
| Provider-response size cap | **Fixed this pass** |
| CLI numeric bounds | **Fixed this pass** |
| Rate limiting | Implemented + tested, **not wired to any live endpoint** (none exists) |
| Secrets | Clean (verified: no `.env`, no key-shaped strings in the repo) |
| Dependency vulnerabilities | None found (`pip-audit`) |
| Static analysis | Clean except one documented false positive |
