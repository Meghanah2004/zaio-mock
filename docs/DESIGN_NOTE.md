# Design Note: Mock EISA Generation Pipeline

Occupational Certificate: Software Developer (SAQA ID 118707), Phase 1.
This note summarizes four specific design questions; see `docs/DESIGN.md`
for the full architecture and rationale.

## A. Prompt / output structure

Generation prompts are deliberately narrow: each provider call produces one
artifact, not the whole paper. `prompts/generate_questions.txt` generates
exactly one question for one blueprint section - never "write the whole
paper" in a single call. `prompts/generate_memo.txt` generates the marking
memo for exactly one already-finalized question. `prompts/review.txt`
reviews the complete paper and memo once, for judgement-level issues only.
Each prompt is templated with a small, explicit set of blueprint fields
(section title, marks, difficulty, occupational context, required outcome
codes), not the full reference corpus, so context per call stays small and
a problem in one section never invalidates the other five.

Provider output is parsed as JSON (tolerant of markdown code fences), and
only a fixed, named subset of fields is accepted from it: for a question,
`type`, `scenario`, `question`, `sub_questions`, `expected_response_type`,
`outcomes`; for a memo entry, `model_answer`, `criteria`,
`accepted_alternatives`, `partial_credit_guidance`, `penalties`. Everything
else about a question or memo entry - its ID, section, question number,
marks, difficulty, competencies - is assigned by
`question_generator.py`/`memo_generator.py` from the blueprint, never read
from the model's output.

The resulting artifacts are structured JSON validated against
`schemas/paper.schema.json` and `schemas/memo.schema.json`, plus
human-readable Markdown and PDF renderings produced deterministically from
that same JSON.

## B. Anti-copying / novelty measures

No single mechanism here is treated as proof of originality; three
independent layers combine:

1. **Authorial/prompt discipline** - the mock content bank
   (`src/providers/mock_provider.py`) was written from the qualification's
   knowledge-topic list, not by rewording a reference-guide question; the
   live-provider prompt states the same constraint to the model directly.
2. **Deterministic lexical novelty check**
   (`src/validation/novelty_checker.py`) - TF-IDF plus cosine similarity
   between each generated question and roughly 15,800 chunks of the
   extracted reference corpus (built once from `sdev/`, reused by every
   validation run). Each question receives a `pass` / `flag_for_review` /
   `regenerate` status against configured thresholds.
3. **LLM quality review** (`src/validation/quality_reviewer.py`), run after
   every deterministic check has already passed, asked explicitly to flag
   content that reads as copied even without seeing the source text - a
   softer, semantic check the lexical pass cannot do.

Stated plainly, as the tool itself reports on every run: the novelty
checker catches close wording overlap only. It does not catch paraphrase,
reordering, variable renaming, or copying from material outside `sdev/`. A
`pass` is a screening result, not a certification of originality.

## C. What is never trusted to the LLM unsupervised

Anything with an objectively checkable answer is decided outside the model
and re-checked even when the model got it right:

- **Marks** - how many marks a question is worth, and how sub-question
  marks sum to the section total, come from the blueprint and are checked
  immediately at generation time, not deferred to a later pass.
- **IDs and structure** - question/section IDs and numbering are assigned
  by pipeline code, never read from provider output.
- **Outcome coverage** - the model must declare which outcome codes a
  question genuinely exercises; `coverage_validator.py` rejects any code
  outside the section's outcome universe, rejects a declaration missing a
  required outcome, and rejects a question whose declared outcomes are
  simply a copy of the section's entire outcome list (a regression guard
  against an earlier bug where "coverage" was tautological).
- **Official-status claims** - a dedicated check rejects generated text
  claiming official QCTO/EISA status, since this is a mock assessment.
- **Memo completeness** - `marks_validator.py` checks that the memo covers
  every sub-question and that memo marks equal paper marks; the model is
  never asked to self-certify this.
- **Novelty** - never self-certified by the model, as above.
- **Security** - path handling, ingestion size/type bounds, provider-output
  size limits, and error-message redaction are deterministic code with no
  model involvement.

The quality-review pass is the one place a model's judgement is the final
word, and it runs last, over content that has already passed every
structural and numeric check - it can flag or fail content, but it cannot
introduce or approve an unvalidated mark total, ID, or outcome claim.

## D. Paper 3 regeneration without collapsing into the same questions

No code changes are needed for a new paper. `configs/software_developer.json`
is the single place assessment structure (sections, marks, duration,
required outcomes) lives, and both providers read the same blueprint:

```
python -m src.cli generate --qualification software_developer \
  --paper-number 3 --seed 20270101
```

With the real provider (`LLM_PROVIDER=anthropic`), a new seed and the
model's own generation variance produce new scenario content per call,
while the blueprint keeps marks, outcomes, and structure identical across
papers - Paper 3 differs in content, not in structure. The novelty checker
then screens Paper 3's questions against the same reference corpus used for
Papers 1 and 2, and the full deterministic validation sequence re-runs
regardless of which paper number was requested.

With the default `MockProvider` - what every artifact in this submission
was generated with, since no API key is configured in this environment -
variety is bounded and fixture-based: each section currently holds two
hand-written scenario variants, selected by `seed % 2`. Different seeds
under `MockProvider` alternate between those same two options per section
rather than synthesizing new content; genuine open-ended variety requires a
real provider. This limitation is stated directly in `README.md` and
`docs/DESIGN.md`, not hidden from a reader of the output.
