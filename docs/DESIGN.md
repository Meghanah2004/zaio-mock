# DESIGN.md - Phase 1 Mock EISA Pipeline

Scope: Software Developer qualification only. See `docs/reference-analysis.md`
for what the supplied reference material does and does not establish.

## Pipeline shape

```
sdev/ (read-only)
  -> ingestion (src/ingestion/pdf_loader.py)          - extract text per PAGE, never write to sdev/
  -> reference analysis (src/analysis/)                - deterministic regex/heuristic parse
  -> artifacts/reference-analysis.json                 - compact, reusable intermediate
  -> page-tagged chunks (src/analysis/reference_analyzer.extract_corpus_chunks)
       -> artifacts/reference-corpus-chunks.json        - page + Knowledge-Topic-tagged passages
  -> blueprint (src/generation/blueprint.py)            - config + analysis -> assessment spec
  -> artifacts/blueprint.json
  -> evidence retrieval (src/retrieval/evidence_selector.py) - per section, real page-cited
       passages retrieved from the chunks above (NEW - see docs/DESIGN_NOTE.md section B)
  -> question generation (src/generation/question_generator.py)  - 1 provider call per section,
       prompt carries real evidence; grounding + cross-paper novelty checked before acceptance
  -> memo generation (src/generation/memo_generator.py)           - 1 provider call per question
  -> validation (src/validation/*)                      - schema, marks, coverage, grounding, novelty
  -> quality review (src/validation/quality_reviewer.py) - 1 provider call, judgement-only
  -> rendering (src/rendering/*)                        - Markdown (+ optional PDF)
```

Each arrow is a real module boundary with its own CLI subcommand
(`analyze`, `generate`, `validate`, `review`, `render`, or `pipeline` to run
all of them). Nothing upstream of `generate` calls an LLM - evidence
retrieval included, it is pure deterministic TF-IDF ranking over
already-extracted, already-paginated text (see docs/DESIGN_NOTE.md, "How
the system finds and retrieves learner-guide pages/passages").

## Why reference analysis is deterministic, not LLM-based

The supplied Learner Guides use a rigid, repeated front-matter format
(`Module #`, `NQF Level`, `Credit(s)`, `SECTION N: KM-xx-KTyy: <title> <w>%`,
...) across all 11 modules. That is structured data, not prose to be
summarized - a regex parser extracts it exactly and reproducibly, and never
hallucinates a credit value or a knowledge-topic weight. An LLM would be
strictly worse here: slower, non-deterministic, and capable of inventing a
plausible-looking but wrong number. `src/analysis/reference_analyzer.py`
documents every field it could and could not find (see
`docs/reference-analysis.md`, sections 9-11: facts / inferences / unknowns).

## Prompt strategy: small, specialized prompts

`prompts/generate_questions.txt`, `generate_memo.txt`, and `review.txt` are
each scoped to one call producing one artifact:

- One call generates ONE question's content for ONE blueprint section (never
  "write the whole paper").
- One call generates ONE question's memo, given that exact question's final,
  already mark-checked JSON (never "write the whole memo").
- One call reviews the finished paper+memo for judgement-level quality
  issues only (ambiguity, realism, technical correctness) - never asked to
  also fix structural/numeric problems, which stay deterministic.

This keeps each prompt's context small (a handful of blueprint fields, or
one question), keeps failures localized (a bad section doesn't invalidate
the whole paper), and enables *targeted* regeneration - if quality review or
a validator rejects Question C1, only Section C's provider call needs to
re-run, not the other five.

`prompts/analyze.txt` and `prompts/blueprint.txt` are placeholders,
deliberately not invoked in Phase 1 - see the note inside each file for why.

## Structured outputs and what the LLM is never trusted with

Provider output is parsed as JSON (`src/generation/llm_utils.extract_json`,
tolerant of markdown fences) and then only a fixed, explicit subset of
fields is accepted from it: `type`, `scenario`, `question`, `sub_questions`,
`expected_response_type`, `outcomes` for a question; `model_answer`,
`criteria`, `accepted_alternatives`, `partial_credit_guidance`, `penalties`
for a memo entry. Every governance field - `id`, `section_id`,
`question_number`, `marks`, `difficulty`, `competencies` - is assigned by
`src/generation/question_generator.py`/`memo_generator.py` from the
blueprint, never read from provider output, and mark totals are checked
immediately (`GenerationError` raised on mismatch) rather than deferred to
the validation stage. Concretely, the LLM is never trusted to:

- decide how many marks a question is worth, or how marks split across
  sub-questions relative to the section total (checked, not assumed);
- assign IDs, or guarantee they're unique across the paper;
- claim official EISA/QCTO status (checked by
  `coverage_validator._check_official_status_claims`);
- self-certify that a memo covers every sub-question (checked by
  `marks_validator._check_memo_coverage_and_marks`);
- self-certify novelty (a separate, non-LLM lexical check exists precisely
  because "trust me, it's original" is not verifiable from the model alone);
- freely choose its own outcome labels (see below - `outcomes` is provider-
  declared but structurally validated, not assigned wholesale from the
  blueprint and not accepted unchecked either).

### Outcome mapping: explicit subsets, not section-wide copies

An earlier version of this pipeline assigned a question's `outcomes` and
`competencies` fields directly from its section's ENTIRE blueprint outcome
list, regardless of what the question's content actually tested. This made
`coverage_validator`'s outcome-coverage check tautological: it always
passed, because the "coverage" it measured was just the blueprint copying
itself, not evidence that any question genuinely exercised those outcomes
(e.g. Section E's single question was labelled with all 19 of KM-09's
knowledge topics, though it substantively tests about 4 of them).

This was fixed by splitting each section's outcome data into two lists in
`configs/<qualification>.json`:

- `outcomes` (derived from `km_refs` as before) - the section's full
  thematic scope, for documentation/human context only.
- `required_outcomes` - a small, hand-curated subset that a generated
  question for this section MUST demonstrably cover. Chosen by inspecting
  what the section's actual question content tests, not by formula.

The provider must now declare, in an `outcomes` field on its question JSON,
exactly which outcome codes its content genuinely exercises.
`question_generator._normalize_question` then:

1. rejects any declared code that isn't part of the section's outcome
   universe (no hallucinated/unrelated codes),
2. rejects the declaration if it doesn't cover every code in
   `required_outcomes` (missing required coverage caught at generation
   time, not just downstream),
3. derives `competencies` from the SAME declared subset (never the
   section's full competency list), so the two fields can never drift.

`coverage_validator._check_outcome_and_competency_coverage` re-checks all of
this structurally against the final paper (independent of whether
generation-time checks ran, e.g. for a hand-edited paper JSON), and adds one
more check with no generation-time equivalent: `no_tautological_full_list_copy`
explicitly fails a question whose `outcomes` are identical to its section's
entire thematic list when that list is broader than `required_outcomes` -
this is the direct regression guard against the original bug. Coverage
counting uses set union, so duplicate or redundant codes in a question's
declared list can never manufacture credit for a genuinely-uncovered
required outcome.

This is a structural/set-membership contract, not an NLP or semantic check
- deliberately so, per the same "don't trust what a schema can't verify"
principle used everywhere else in this pipeline.

## Retrieval-grounded generation (Phase 1 evaluator rework)

An earlier version of this pipeline sent the LLM only a section's title,
occupational context, and Knowledge Topic CODE/TITLE labels (e.g.
"KM-06-KT02 (Object-Oriented Programming)") and let it invent the actual
technical content from general knowledge - the model never saw a single
sentence of the supplied Learner Guides. An evaluator correctly rejected
this: it does not satisfy "generate from the reference material," and it
also meant Papers 1 and 2 were identical (MockProvider's fixed 2-variant
fixture bank, selected by `seed % 2`, with no evidence input to vary on),
and the cover stated `NQF Level [4, 5]` (the raw per-module span) instead of
the qualification's single assessed level.

The fix, in full, is documented in **`docs/DESIGN_NOTE.md`** (which
evaluator feedback specifically asks for and which repeats none of this
section's detail): page-tagged corpus chunking, TF-IDF evidence retrieval
scoped to each section's required outcomes, evidence embedded in the
generation prompt with real page citations, grounding checked both at
generation time and independently re-verified at `validate` time
(`src/validation/grounding_validator.py`), cross-paper novelty tracked in
`artifacts/generation-history.json` so a later paper cannot collapse into an
earlier one, and the cover's NQF level fixed to a single config value
(`configs/software_developer.json`'s `nqf_level`) rather than derived from
the reference analysis's per-module span.

No new dependency was introduced for any of this - retrieval reuses the
same lightweight, dependency-free TF-IDF index already built for novelty
screening (`src/validation/novelty_checker.ReferenceCorpusIndex`).

**This was still only half the source-of-truth guarantee**: the above
grounds the QUESTION, but the memo's model ANSWERS were generated from the
finished question JSON alone, with no retrieved evidence and no grounding
check - a later audit found the API layer (`api/service.py`) was also
calling the engine with none of this wired in at all (no evidence, no
cross-paper history), so a real Generate-button request produced an
entirely ungrounded paper and memo despite the CLI path being correct. Both
gaps are fixed: `api/service.py` now calls the SAME shared retrieval/
history functions `src/cli.py` uses
(`src.retrieval.evidence_selector.load_retrieval_index`/
`build_evidence_by_section`, `src.validation.cross_paper_novelty.
load_history`/`record_paper`/`write_history`), and a second, independent
retrieval pass grounds every model answer in real, question-targeted
learner-guide evidence, checked before acceptance and independently
re-verified at `validate` time - see **`docs/DESIGN_NOTE.md` section C2**
for the full answer-side design and a real worked example, and
`src/validation/answer_grounding_validator.py` for the re-check.

## Reference handling and prompt-injection defense

Reference documents are UNTRUSTED DATA end-to-end. Four channels are kept
structurally separate (updated after the Phase 1 security hardening pass -
see `docs/SECURITY-AUDIT.md` 6.2 for the finding that corrected this):

1. **System policy** - the fixed instruction text in `prompts/*.txt`,
   written by this project, sent as the `system` message to the LLM. Not
   overridable by anything in categories 2-4.
2. **Reference-derived data** - text mechanically extracted from `sdev/`
   PDFs. Two pieces genuinely reach an LLM prompt when `AnthropicProvider`
   is used: Knowledge Topic titles/codes (the section's outcome/competency
   list), and - since the retrieval-grounded generation rework - the
   retrieved GUIDE_EVIDENCE passages themselves
   (`src/retrieval/evidence_selector.py`). Both are bounded before they can
   reach a prompt: KT titles by `_normalize_title`
   (`MAX_REFERENCE_DERIVED_TEXT_LENGTH`, strips control characters at
   extraction time), evidence passages by `SecurityConfig.
   max_evidence_passage_chars` (truncated in `evidence_selector._truncate`)
   and capped in count by `MAX_EVIDENCE_BLOCK_ITEMS` /
   `evidence_passages_per_section`. The prompt wraps ALL of this in
   explicit `<<REFERENCE_DATA>>...<<END_REFERENCE_DATA>>` delimiters with a
   literal instruction that content inside them is never a command,
   regardless of phrasing.
3. **Application-generated task data** - the question/paper/memo JSON
   passed between generation stages (e.g. into `generate_memo.txt`,
   `review.txt`). This originates from this pipeline's own prior stage, but
   is still delimited and labeled as untrusted DATA in the same way,
   because a scenario string could, in principle, contain imperative-
   sounding fictional dialogue.
4. **Generated content** - LLM output. Treated as untrusted until it passes
   JSON parsing, then schema validation, then the deterministic validators.

`MockProvider` (the offline default, and the only provider automated tests
are ever allowed to use - see `tests/conftest.py`'s test-environment
isolation) never sends anything to a real model, so this defense is inert
during tests by design. Real generation - `LLM_PROVIDER=anthropic`/
`gemini`/`groq` with a real key configured, used for the actual Paper 1/2
runs - does send channel 2 content to a real model, which is exactly why
this defense is real and tested
(`tests/test_security_prompt_injection.py`), not speculative. The
delimiter/instruction pattern is applied consistently across all three real
prompt templates (`generate_questions.txt`, `generate_memo.txt`,
`review.txt`), not just the one where the gap was originally found.

## Anti-copying approach and its limits

Three independent layers, none of which alone is sufficient:

1. **Authorial discipline**: `src/providers/mock_provider.py`'s content was
   written from the qualification's knowledge-topic list and general
   software-development practice, never by opening a reference PDF question
   and rewording it. The real-provider prompt (`generate_questions.txt`)
   states the same constraint explicitly to a live LLM.
2. **Lexical novelty screening** (`src/validation/novelty_checker.py`): pure
   Python TF-IDF + cosine similarity against ~15,800 chunks of the extracted
   reference corpus (`artifacts/reference-corpus-chunks.json`, built once by
   `analyze`, reused by every `validate` run). Per-question status is
   `pass` / `flag_for_review` / `regenerate` against configurable thresholds
   (`configs/software_developer.json`'s `novelty` block).
3. **LLM quality review** (`src/validation/quality_reviewer.py`): asked
   explicitly to flag anything that "reads as copied" even without seeing
   the source text, as a softer, semantic-level check the lexical pass
   can't do.

**Limitations, stated plainly**: the novelty checker catches close wording
overlap only. It does NOT catch paraphrase, translation, reordering,
variable renaming, or copying from anything outside `sdev/`. A `pass` is a
screening result, not a certification of originality - this is stated in
the tool's own output (`limitations` field) every time it runs, not just in
this document.

## Validation strategy

Deterministic, ordered, fail-fast:

1. `schema_validator` - JSON syntax + JSON Schema (structure must be sound
   before anything else is checked, or later checks would throw confusing
   `KeyError`s instead of a clear message).
2. `marks_validator` - unique IDs, section/paper mark totals, sub-question
   sums, memo coverage, memo-vs-paper mark equality.
3. `coverage_validator` - blueprint outcome/competency coverage, expected
   question counts, empty/malformed fields, duplicate question text, and the
   "no false official-status claim" check.
4. `novelty_checker` - lexical overlap screening against the source corpus
   (see above).
5. `grounding_validator` - independent re-check that every question's
   `grounding` citations actually exist in the ingested corpus (no
   fabricated pages) and that the question's overlap with its cited
   evidence falls in the expected range (derived, not invented; transformed,
   not copied) - see docs/DESIGN_NOTE.md section D.
6. `quality_reviewer` - the one LLM-judgement stage, run last, over content
   that has already passed every deterministic gate.

`python -m src.cli validate` runs 1-5 and writes
`artifacts/validation-report.json` with a `passed: bool` and a flat list of
named `checks`, each independently inspectable - exactly the shape asked
for in the brief. The CLI exits non-zero on any failed check.

## Reproducibility: how a future Paper 3 works

No code changes are needed. `configs/software_developer.json` is the single
place the assessment structure (sections, marks, duration, question types,
required outcomes) lives, and generation reads it through the same
provider-agnostic path regardless of which provider is configured.

**With the real provider** (`LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` in
`.env` - zero code changes needed either way):

```
python -m src.cli generate --qualification software_developer --paper-number 3 --seed 20270101
```

sends the same blueprint-derived prompts to the live model, together with
freshly retrieved evidence for seed 20270101 (`src/cli.py:
_build_evidence_by_section`), and now ALSO checks the result against
`artifacts/generation-history.json` (every question from Paper 1 and Paper
2's runs) before accepting it - see docs/DESIGN_NOTE.md section D. A
collision is rejected and regenerated automatically, not left to the
model's own variance alone.

**With MockProvider**: still a deterministic, offline, FIXTURE-based
stand-in, not a generation engine - see `src/providers/mock_provider.py`'s
module docstring, and never presented as evidence a paper is AI-generated
(the paper JSON's `generation_meta.provider` always says `"mock"`). Each
section still holds exactly 2 hand-written scenario variants, selected by
`seed % len(bank)`, so genuine open-ended content variety still requires a
real provider. What DOES change under this rework: when real evidence is
supplied (the CLI's normal `generate` path always supplies it), MockProvider
weaves the retrieved passage into its fixture output so the SAME grounding
and cross-paper-novelty checks described above apply uniformly to every
provider, not just the real one - see `mock_provider.py._generate_question`
and `tests/test_question_generator_grounding.py`.

## Security boundaries

A full, dedicated security audit and hardening pass lives in
**`docs/SECURITY-AUDIT.md`** (threat model, per-finding severity and
remediation, dependency audit, static analysis results). This section
summarizes the controls that boundary touches; treat SECURITY-AUDIT.md as
authoritative for anything more detailed.

- `sdev/` is only ever opened for reading (`src/ingestion/pdf_loader.py`
  never calls a write/delete API); ingestion is additionally bounded by
  configurable max file size, max file count, and max filename length
  (`src/security/config.py`) so a pathological input directory cannot
  cause unbounded processing time.
- All user-supplied paths (`--paper`, `--memo`) are resolved through
  `src/config.safe_path_within`, which rejects any path (relative `../..`,
  absolute, or symlink-based) that resolves outside the project root -
  verified against all three escape shapes in
  `tests/test_security_path_traversal.py`, including the specific
  guarantee that no resolvable path can land inside `sdev/`.
- File ingestion checks extension against an allow-list
  (`SUPPORTED_EXTENSIONS`) and a size bound before parsing.
- No secret is ever hard-coded; `ANTHROPIC_API_KEY` is read once from the
  environment (`src/config.py`) and never logged or printed -
  `AnthropicProvider` catches SDK exceptions and re-raises a redacted
  message (`src/security/redaction.redact_secrets`) that cannot include the
  key even if some future SDK version's exception text ever echoed it.
  The CLI's top-level exception handler (`src/cli.py:main`) applies the
  same redaction to every uncaught exception, of any type, and never
  prints a raw Python traceback (which would expose absolute filesystem
  paths) - it prints the exception type and a redacted message only.
- No generated content is ever executed - `code_writing`/`code_analysis`
  question types produce text describing/containing code for a human
  candidate to write or read; nothing in this pipeline runs candidate or
  LLM-generated code. PDF rendering XML-escapes all such text before it
  reaches reportlab's markup parser, closing a verified injection/crash
  path where unescaped `<`/`&` could break or redirect rendering (see
  SECURITY-AUDIT.md 6.1).
- Provider output is size-bounded before JSON parsing
  (`MAX_PROVIDER_RESPONSE_CHARS`), and every provider call goes through a
  bounded retry wrapper (`src/generation/llm_utils.call_provider_with_retry`)
  that only retries transient provider-level failures, never deterministic
  content/schema defects - generation always terminates, never loops.
- Reference-derived text that can reach a real LLM prompt (Knowledge Topic
  titles) is length-capped and control-character-stripped at the point of
  extraction (`src/analysis/reference_analyzer._normalize_title`), and
  every prompt template wraps such data in explicit
  `<<REFERENCE_DATA>>...<<END_REFERENCE_DATA>>` delimiters with a literal
  instruction not to follow content found inside them.
- Network access only happens inside `AnthropicProvider`, and only when
  explicitly configured; `MockProvider` makes zero network calls, which is
  what every artifact under `output/` in this submission was generated with.
- The rate limiter (`src/security/rate_limiter.py`) and the public-error
  sanitizer (`src/security/redaction.sanitize_for_public`), built ahead of
  time for a future API layer, are now **actively wired in**: the Phase 2
  API (`api/`) enforces the rate limiter on every endpoint and uses the
  sanitizer in its error handlers - see `docs/API.md`. Neither gained a
  second implementation; the API calls the exact same components this
  paragraph originally described as prepared-but-unused.

## Why this architecture fits a Phase 1 timebox

Every module boundary above maps to one file and one CLI subcommand -
there's no framework, no queue, no database, no orchestration layer beyond
argparse. The parts that *do* carry real engineering weight - deterministic
reference parsing, mark-arithmetic validation, memo/paper consistency,
provider abstraction, novelty screening - are exactly the parts a hiring
challenge titled "Mock EISA generation pipeline" is testing, and are also
the parts that are hardest to bolt on later if skipped now. Everything else
(a queue, a database, multi-qualification support, a web UI) is explicitly
out of Phase 1 scope per the brief and is not stubbed out here.
