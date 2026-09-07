# Code Quality Audit - Repository Minimization Pass

Date: 2026-09-06. Companion to `docs/DEPENDENCY-AUDIT.md`. Covers dead
code, duplicate logic, unused imports, configuration, performance, and
test consolidation found and fixed during this pass. Every item below was
verified by inspection before being changed, and the full test suite plus
full pipeline were re-run after each meaningful change.

## Files removed

| File | Reason |
|---|---|
| `tests/test_path_safety.py` | Fully superseded by `tests/test_security_path_traversal.py`, which covers every scenario it tested (nested-relative-path-allowed, relative-traversal-blocked, absolute-escape-blocked) plus more (symlink escapes, sdev protection, encoded-string handling). Its one non-duplicate test (`allows_absolute_path_inside_base`) was migrated into the newer file before deletion - zero coverage lost, 3 duplicate tests removed. |

No other file was removed. `artifacts/`, `output/`, and `docs/` were
inspected for redundant/obsolete generated files - none were found (see
"Files inspected and kept" below).

## Code removed (dead/unused code)

1. **`src/ingestion/pdf_loader.py`: unused SHA-256 hashing.** Every
   ingested file (including an 18MB PDF in the real `sdev/` corpus) had its
   full contents hashed via `_sha256_of()`, and the result was stored on
   `SourceDocument.sha256` - but nothing anywhere in `src/`, in any output
   artifact (`reference-analysis.json` never included it), or in any test
   ever read that field. Verified via grep across the entire tree before
   removal. Removed: `_sha256_of()`, the `sha256` field, its call site, and
   the now-unused `hashlib` import. This eliminates real, non-trivial I/O
   and CPU work (a full-file read-and-hash pass) on every single `analyze`
   run, for a value that was always immediately discarded.

   This is a different situation from `src/security/rate_limiter.py`,
   which was correctly NOT removed: the rate limiter is a documented,
   tested, intentionally-prepared-for-the-future component (explicit
   module docstring, 8 dedicated tests, referenced from `docs/DESIGN.md`
   and `docs/SECURITY-AUDIT.md`). The SHA-256 computation had none of
   that - no documentation of future intent, no tests, no consumer,
   anywhere. It read as an incidental leftover, not a reserved capability.

2. **Unused imports** (found via `ruff check src tests`, the exact command
   this pass specified):
   - `tests/conftest.py`: `import copy` - zero `copy.` usages in the file.
   - `tests/test_security_cli_bounds_and_errors.py`: `main` imported from
     `src.cli` but never called directly (all call sites use
     `cli_module.main(...)` via the module reference obtained through
     `import src.cli as cli_module`).
   - `tests/test_security_pdf_rendering.py`: `from pathlib import Path` -
     never referenced.

## Duplicate logic consolidated

- **`src/cli._run_all_validators`**: returned a 3-tuple
  `(report, coverage_report, novelty_result)`, but the single call site
  (`cmd_validate`) discarded the second element entirely
  (`report, _coverage, novelty_result = ...`). The coverage checks
  themselves were never lost - `validate_coverage`'s individual `checks`
  were already folded into `report` via `report.add(c)` - only the
  redundant standalone `coverage_report` return value was dead output
  plumbing. Simplified the function to return a 2-tuple. This also fixed a
  genuine type-annotation bug `mypy` had flagged (the declared return type
  said `dict | None` for a value that was actually `ValidationReport |
  None`) - fixed by removing the inaccurate type entirely rather than
  correcting the annotation to match code nobody needed.

- **`src/analysis/reference_analyzer.analyze_reference_material`**: the
  same `re.search(r"\d+", m.source_file)` pattern was evaluated **twice**
  in each of two separate expressions (once in a sort key, once in a
  module-numbers comprehension) - 4 redundant regex evaluations per module
  where 1 would do. Extracted a small `_extract_module_number()` helper
  (single regex call, returns `int | None`) and used a walrus operator in
  the comprehension to avoid re-evaluating it there too. This was flagged
  as a `mypy` "Item None has no attribute" warning during the prior
  security-hardening pass and left as documented-but-unfixed then (out of
  that pass's scope); fixed here since code-quality cleanup is this pass's
  explicit remit. Reduces regex evaluations from 4N to 2N for N modules
  (N=11 in the real corpus - the performance effect is negligible; the
  real benefit is removing both the redundant computation and the
  associated type-checker noise in one small, safe change).

## Imports removed

3 genuine unused imports (listed above under "Code removed"). No other
unused imports were found by `ruff check src tests` - the remaining 21
findings are import-ordering (`I001`) and Python-version-modernization
suggestions (`UP017`, `UP037`, e.g. "use `datetime.UTC` alias"), which are
style preferences, not unused/dead code; left unchanged to avoid
unnecessary bulk reformatting diffs across files that are otherwise
correct (see "Findings not acted on" below).

## Configuration simplified

- **`requirements.txt` / `requirements-dev.txt`**: `pytest` moved from the
  former to the latter - see `docs/DEPENDENCY-AUDIT.md` for the full
  reasoning and clean-environment proof. This is the only configuration
  change; `pyproject.toml`'s `[tool.pytest.ini_options]` was inspected and
  is unchanged (it configures test discovery, not dependencies, and every
  setting in it is used).
- **`.gitignore`**: added `build/`, `dist/`, and coverage-artifact patterns
  (`.coverage`, `.coverage.*`, `htmlcov/`, `coverage.xml`) that this pass's
  own checklist called for but were not previously present, even though no
  such files currently exist in the repository (defensive, not reactive).
- **Schemas, prompts, configs**: `schemas/paper.schema.json` and
  `schemas/memo.schema.json` are both loaded and used
  (`src/validation/schema_validator.py`); `configs/software_developer.json`
  is the only file in `configs/` and is loaded by `src/cli.py`. All three
  of `prompts/generate_questions.txt`, `generate_memo.txt`, and
  `review.txt` are loaded by name from `src/generation/` and
  `src/validation/quality_reviewer.py` respectively. `prompts/analyze.txt`
  and `prompts/blueprint.txt` are **not** loaded by any code path -
  verified by grep - but were **kept**: both carry an explicit
  "NOTE: Not currently invoked" header explaining they document why
  analysis/blueprint-building are deterministic rather than LLM-based, and
  `docs/DESIGN.md` cross-references them by name. This is the same
  "intentionally prepared, not currently wired in" category this pass
  explicitly protects for `src/security/rate_limiter.py` - removing them
  would delete documented architectural reasoning, not dead weight.

## Performance improvements

1. Removed the unused SHA-256 hash computation (see above) - the most
   significant real performance change in this pass, since it was O(file
   size) work on every ingested file, including large ones, for a
   completely discarded result.
2. Removed the 2x-redundant regex evaluation in module-number extraction
   (see above) - negligible real-world impact (11 modules) but a genuine,
   verified fix, not a hypothetical one.
3. **Investigated and NOT changed**: schema loading
   (`src/validation/schema_validator._load_schema`) re-reads its JSON file
   from disk on every call. This looked like a candidate for caching, but
   each schema is loaded at most once per CLI invocation in every actual
   call path in this codebase (`validate_paper_schema` /
   `validate_memo_schema` are each called exactly once per `validate`
   command run) - there is no loop or repeated-call site anywhere that
   would benefit. Added caching here would be speculative complexity with
   zero measured benefit, which this pass's own instructions caution
   against ("do not micro-optimize simple code").
4. **Investigated and NOT changed**: the novelty checker's reference
   corpus (`artifacts/reference-corpus-chunks.json`, ~15,842 chunks) is
   already built once by `analyze` and reused by every `validate` call
   rather than being re-derived from the raw PDFs each time - this was
   already the correct, efficient design from the prior implementation
   pass and needed no further change.

## Tests consolidated

- 3 tests removed as exact-behavior duplicates (see "Files removed"
  above); 1 unique test migrated to the surviving file. Net: 128 -> 125
  tests, with the same or greater coverage (the 3 removed tests tested
  scenarios also covered, more thoroughly, by the surviving file: e.g. the
  old file's single "blocks relative traversal" case is now covered by
  three more specific tests - single-level, nested, and hidden-inside-a-
  longer-path).
- No other duplicate tests were found. `tests/test_ingestion.py` and
  `tests/test_security_ingestion_bounds.py` were specifically checked for
  overlap (both touch `load_reference_material`): one incidental shared
  assertion exists (both confirm an unsupported extension is skipped), but
  each test's *primary* purpose is materially different (general
  extraction correctness with real text-content verification, vs.
  security-bound enforcement) - not "two tests verifying exactly the same
  behavior," so both were kept per this pass's explicit instruction to
  consolidate only in that narrower case.

## Dependency reductions

See `docs/DEPENDENCY-AUDIT.md` in full. Summary: 0 packages removed, 1
reclassified (`pytest`: runtime -> dev), proven sufficient and correct via
a from-scratch clean-environment rebuild (25 packages for runtime-only,
full pipeline passing; 64 with dev tooling added, full test suite
passing).

## Security controls preserved (explicitly verified, not assumed)

Every item below was re-run after all changes in this pass and confirmed
still present/passing:

- `safe_path_within` path-traversal protection - unchanged, still tested.
- `sdev/` isolation - unchanged; file count/size verified identical
  before and after this pass.
- Ingestion size/count/filename limits (`src/security/config.py`) -
  unchanged.
- Schema `maxLength`/`maxItems`/`maximum` bounds - unchanged.
- Secret redaction (`src/security/redaction.py`) - unchanged, still wired
  into `src/cli.py`'s top-level handler.
- Provider response size cap and bounded retries
  (`src/generation/llm_utils.py`) - unchanged.
- Prompt-injection delimiters in all three real prompt templates -
  unchanged.
- Safe PDF rendering (XML-escaping) - unchanged.
- Safe, redacted exception handling in the CLI - unchanged.
- No `eval`/`exec`/`subprocess`/`os.system`/`pickle`/`yaml.load` anywhere
  in `src/` - re-verified by grep after this pass's changes (still zero
  matches).
- `src/security/rate_limiter.py` - untouched, all 8 of its tests still
  pass. Not removed despite having no live caller, per this pass's
  explicit instruction.
- All security regression tests (`tests/test_security_*.py`, 67 tests
  minus the 3 duplicates removed from the superseded file = still full
  coverage) - all still present and passing.

## Findings not acted on (and why)

- **21 remaining `ruff check` findings**: import-block ordering (`I001`)
  and Python modernization suggestions (`UP017` `datetime.UTC`, `UP037`
  quoted-annotation removal). These are style preferences with zero
  functional or security effect. Auto-fixing them would touch import
  blocks in ~10 files purely cosmetically; left alone to keep this pass's
  diff focused on genuine dead code, duplication, and dependency issues,
  per "do not blindly suppress warnings" cutting both ways - these aren't
  warnings to suppress, but also aren't defects to chase for their own
  sake.
- **`bandit` B608 SQL-injection false positive** in
  `src/providers/mock_provider.py` - unchanged from the prior security
  audit; it is exam-question teaching content about SQL injection, never
  executable code, confirmed by the continued absence of any DB driver
  import anywhere in `src/`.
- **`mypy` union-attr noise** in `src/providers/anthropic_provider.py` -
  mypy cannot statically narrow the Anthropic SDK's response-content union
  type based on the existing runtime `getattr(block, "type", None) ==
  "text"` guard. The guard is correct at runtime; this is a type-stub
  precision limitation, not a bug, and touching the SDK's response-parsing
  logic to appease a type checker for zero behavioral change was judged
  out of scope.
