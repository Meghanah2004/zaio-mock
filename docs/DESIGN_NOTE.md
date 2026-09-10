# Design Note: Mock EISA Generation Pipeline

Occupational Certificate: Software Developer (SAQA ID 118707), Phase 1.

**This note replaces the previous version after evaluator feedback**: the
engineering was assessed as solid, but the exam itself did not satisfy the
brief - questions were generated from Knowledge Topic *names* rather than
real learner-guide content, MockProvider's pre-written fixtures were shipped
as if they were AI output, Paper 1 and Paper 2 were byte-for-byte identical,
and the cover stated "NQF Level [4, 5]" instead of a single assessed level.
This note documents what changed and answers the four questions the
evaluator asked for directly, in terms of the actual code (file/line
references throughout), not aspirational description.

See `docs/DESIGN.md` for the full architecture.

## A. Which AI was used, and how

**Model**: `claude-sonnet-5`, via `src/providers/anthropic_provider.py`,
called through the Anthropic Messages API
(`client.messages.create(model=..., system=..., messages=[...])`). This was
already correctly implemented before this rework - the defect was never in
`AnthropicProvider`, it was that `.env` shipped with `LLM_PROVIDER=mock` and
no `ANTHROPIC_API_KEY`, so every artifact under `output/` was produced by
`MockProvider`'s fixed, hand-written content banks
(`src/providers/mock_provider.py`), not by a live model call.

**Current state of this environment**: still no `ANTHROPIC_API_KEY` is
configured here. This rework makes the pipeline capable of real,
learner-guide-grounded generation (sections B-D below), but the actual
Paper 1/Paper 2 regeneration against the live API is a deliberately
separate, explicit step - see "Running real generation" at the end of this
note. Nothing in `output/` has been overwritten by this rework; the
mechanism is proven against the real `sdev/` corpus (real retrieval, real
prompts, real page citations - shown below), with `MockProvider` standing
in for the model call itself until a key is supplied.

`generation_meta.provider` and `generation_meta.grounded` are written onto
every generated paper (`src/generation/question_generator.py`,
`generate_paper`) so it is always possible to tell, from the paper JSON
alone, which provider produced it and whether real evidence retrieval was
used - never asserted in prose only.

## B. How the system finds and retrieves learner-guide pages/passages

Three-stage pipeline, all deterministic, no LLM call:

1. **Ingestion** (`src/ingestion/pdf_loader.py`, unchanged by this rework):
   every PDF under `sdev/` is extracted PAGE BY PAGE - `PageText.page_number`
   was already preserved before this rework; the defect was that nothing
   downstream of it used the page number for anything.

2. **Page-tagged chunking** (`src/analysis/reference_analyzer.py`,
   `extract_corpus_chunks`, rewritten in this rework): every module PDF's
   text follows a rigid, repeated in-body format -
   `SECTION N: KM-xx-KTyy: <title> <weight>%` - that marks exactly which
   page a Knowledge Topic's content begins on (verified against the real
   corpus, e.g. Module 6's `KM-06-KT02` header lands on page 15 and holds
   until `KM-06-KT03`'s header). The chunker walks each document's pages in
   order, tracks "which KT header have I most recently seen," and tags every
   ~50-word chunk it produces with that KT code AND its real page number.
   Nothing here is fabricated: a chunk's `page` is read directly from
   `pdf_loader`'s per-page extraction, never inferred or guessed. (An
   earlier version of this chunker split on single sentences; it was
   discarded because a short, keyword-dense sentence like "CSS allows you to
   apply styles to web pages." can outrank a substantive paragraph in a
   one-sentence TF-IDF ranking purely by keyword repetition, producing
   evidence too shallow to write a real question from - see that function's
   docstring.)

3. **Retrieval** (`src/retrieval/evidence_selector.py`, new): for a
   blueprint section's `required_outcomes` (the same hand-curated KT-code
   list `coverage_validator.py` already enforces question-level coverage
   against), `select_evidence` first filters to chunks STRUCTURALLY tagged
   with that exact KT code (ground truth, not a lexical guess), then ranks
   those by TF-IDF cosine similarity against the topic title + section's
   occupational context (`src/validation/novelty_checker.ReferenceCorpusIndex.
   top_k` - the SAME lightweight index already used for novelty screening,
   reused rather than duplicated). Only if a KT code was never structurally
   tagged (a corpus formatting quirk) does it fall back to an unfiltered
   lexical search, and that fallback is explicitly labelled as such in the
   evidence's `reason` field - never silently indistinguishable from a
   structurally-confirmed match.

Evidence is distributed round-robin across a section's required outcomes so
every required topic is represented, and `seed` picks which of a topic's
top-ranked passages are used (not just their order) - one input to making
Paper 2's evidence, and therefore its questions, genuinely different from
Paper 1's for the same section (see D below).

## C. One real example: passage → generated question

This is a REAL run of the actual retrieval code above, against the real
`sdev/` corpus, for the real Section B ("Front-End Web Development") and
its `KM-06-KT02` (Object-Oriented Programming) required outcome:

**Retrieved evidence** (`Module 6-Learner Guide.pdf`, page 15):

> "Object-oriented programming (OOP) is a computer programming model that
> organizes software design around data, or objects, rather than functions
> and logic."

and (`Module 6-Learner Guide.pdf`, page 17):

> "...subroutines contained in an object are called instance methods.
> Programmers use methods for reusability or keeping functionality
> encapsulated inside one object at a time. Attributes are defined in the
> class template and represent the state of an object..."

**Exactly what reaches the model** - the real, unedited output of
`src/generation/question_generator._build_question_prompt` for this section
with this evidence (verified by `tests/test_question_generator_grounding.py
::test_prompt_actually_contains_the_retrieved_evidence_text_and_page`):

```
GUIDE_EVIDENCE (real passages from the supplied Learner Guides - the source
of truth for this question's syllabus content, per constraint 1 above; each
is labelled [n] SourceDocument, page N):
[1] Module 6-Learner Guide.pdf, page 15: "Object-oriented programming (OOP)
is a computer programming model that organizes software design around
data, or objects, rather than functions and logic."
[2] Module 6-Learner Guide.pdf, page 17: "...subroutines contained in an
object are called instance methods. Programmers use methods for
reusability or keeping functionality encapsulated inside one object at a
time. Attributes are defined in the class template and represent the
state of an object..."
```

**Why this passage supports a question, and what the model is instructed to
do with it**: the evidence establishes that OOP organizes design around
objects (data + behaviour), that methods are how an object's behaviour is
invoked and kept encapsulated, and that attributes hold an object's state.
`prompts/generate_questions.txt` (constraint 1, added in this rework)
explicitly forbids quoting or lightly rewording this text, and instead
requires the model to TRANSFORM it into a workplace scenario - e.g. refactor
a plain data object into a class with encapsulated state and behaviour for a
concrete feature (this is, not coincidentally, the shape of the
`_SECTION_B_VARIANTS` sub-question 4 already in `mock_provider.py`, which
was hand-authored to test exactly this concept before real evidence
retrieval existed - the difference this rework makes is that a REAL model
call now derives that content from THIS cited page instead of the author's
general knowledge, and the paper JSON records the citation instead of
asserting it in a docstring).

The generated question's `grounding` field (attached by
`question_generator._normalize_question`, independently re-verified by
`src/validation/grounding_validator.py` against the ingested corpus) then
carries exactly this document/page/passage/reason - never re-derived or
guessed after the fact, always the literal evidence the model was given.

## C2. Answer-side RAG: the model answer is retrieved and grounded too, not just the question

Sections B and C above describe how a QUESTION is generated from real,
cited learner-guide evidence. Until this rework, that was only HALF of the
source-of-truth guarantee: the marking memo's model answers were generated
from the finished question JSON alone, with no retrieved evidence and no
grounding check - a model answer could freely draw on the model's own
general knowledge instead of the supplied material. Fixed by threading a
SECOND, independent retrieval pass through `src/generation/memo_generator.py`:

1. **Retrieval is targeted at the actual generated question, not its
   section/topic** (`src.retrieval.evidence_selector.select_answer_evidence`).
   Question-side retrieval (B above) only has a section's topic list to work
   from, because no question exists yet. Answer-side retrieval runs AFTER a
   question exists and is validated, so its query is the question's OWN
   declared `outcomes` (already a narrower, validated subset of the
   section's full topic list - see `_normalize_question`) PLUS the
   question's own scenario/stem/sub-question text
   (`select_answer_evidence._question_query_text`) - not just the topic
   title. This reuses the exact same structural-KT-tag-then-TF-IDF-rank
   machinery as question-side retrieval (`_select_evidence_for_topics`,
   extracted as shared code so there is only one retrieval algorithm, not
   two) - only the query text differs.

2. **The retrieved evidence is embedded in the memo prompt**
   (`prompts/generate_memo.txt`'s `ANSWER_EVIDENCE` block, built by
   `memo_generator._build_answer_evidence_block`) with the same explicit
   "this is your only knowledge source, do not assert unsupported facts"
   instruction and the same untrusted-data delimiters as question-side
   evidence (see `docs/DESIGN.md`, "Reference handling and prompt-injection
   defense").

3. **The generated answer is checked against that evidence before
   acceptance** (`memo_generator._answer_grounding_ok`): a MINIMUM cosine-
   overlap floor against the cited evidence (the answer must be DERIVED
   from it, not invented), plus two looser sanity floors - the answer must
   relate to the question it claims to answer, and the marking criteria
   must relate to the answer they grade. Deliberately asymmetric versus
   question-side grounding: there is no MAXIMUM-overlap ("not a near-copy")
   ceiling here, because a model answer is SUPPOSED to closely reflect what
   the guide says - unlike a question, which must be an original scenario.
   A rejected answer triggers the same bounded retry-with-targeted-feedback
   loop already used for marks reconciliation
   (`security_config.memo_max_retries`), never a silent rewrite. If
   retrieval itself finds nothing for a question (a corpus gap), generation
   is refused outright (`GenerationError`) rather than answering ungrounded.

4. **Independently re-verified at `validate` time**
   (`src/validation/answer_grounding_validator.py`, mirroring
   `grounding_validator.py`'s pattern exactly): every memo entry's
   `grounding` citations must exist, cite real corpus pages (anti-
   fabrication), and show sufficient overlap with the answer - re-derived
   from the finished memo JSON alone, never trusting that generation-time
   `_answer_grounding_ok` ran or passed.

**One real example, continuing the same question as section C above** - the
real Paper 1 (Groq-generated) Section B question (`output/mock-eisa-paper-
01.json`, `Q-B1`, outcomes `KM-06-KT02/06/07/08`). Paper 1 was generated
before this rework existed, so its memo has no answer-side grounding yet
(`output/mock-eisa-memo-01.json`'s `generation_meta` has no
`answer_grounded` key) - this is exactly the audit finding that motivated
this rework. What follows is the REAL, unedited output of
`select_answer_evidence` run against the REAL `sdev/` corpus for that real
question (no LLM call - pure deterministic retrieval, reproducible with
`python -m src.cli` or the snippet in this doc's history):

```
[1] Module 6-Learner Guide.pdf, page 17: "What are the main principles of OOP?
Object-oriented programming is based on the following principles: -
Encapsulation. This principle states that all important information is
contained inside an object and only select information is exposed. The
implementation and state of each object are privately held inside a
defined class. Other objects do not have access to this class or the
authority to make changes."
[2] Module 6-Learner Guide.pdf, page 65: "...Programming for HTML5 Web
XPanel uses the same Crestron HTML5 User Interface scripts and components
with the addition of the required HTML5 Web XPanel library..."
[3] Module 6-Learner Guide.pdf, page 74: "CSS lets developers and designers
define how it behaves, including how elements are positioned in the
browser. While html uses tags, css uses rulesets..."
[4] Module 6-Learner Guide.pdf, page 88: "The ECMA-262 Specification
defined a standard version of the core JavaScript language. - JavaScript
is a lightweight, interpreted programming language..."
```

Notice this is NOT the same evidence the question-side retrieval found for
this section (e.g. its `KM-06-KT02` citation was page 16, "classes are
user-defined data types..."; here it is page 17, "principles of OOP...
Encapsulation...") - because the query text is different (the question's
own wording, not just the topic title), confirming retrieval is genuinely
question-specific, not a cached copy of the question-side evidence. A real
model call was deliberately NOT made to produce a "generated model answer"
for this example (see `docs/DESIGN.md`'s testing/real-call policy) - the
point demonstrated here is the real, reproducible RETRIEVAL step; the
generated answer that would follow it is checked by `_answer_grounding_ok`
exactly as described above, exercised end-to-end (question generation
through independent answer-grounding re-validation) with `MockProvider` by
`tests/test_generation_pipeline_mocked.py::
test_full_pipeline_in_real_generation_mode_produces_grounded_paper_and_memo`.

## D. How each new paper avoids repeating ANY earlier one - not just "Paper 2 vs Paper 1"

This is NOT a two-paper special case. Every `generate` run (paper 3, 4, 5,
...) is checked against the FULL accumulated history of every paper
generated before it, not just the immediately preceding one - see
`tests/test_cross_paper_novelty.py::
test_third_paper_is_checked_against_both_prior_papers_not_just_the_latest`
and `tests/test_question_generator_grounding.py::
test_third_generation_is_rejected_for_matching_either_of_two_prior_papers`
for this exercised directly with 3+ papers of history. `paper_number` is
used ONLY to name the output files (`src/cli.py`, `src/generation/
blueprint.py`) - nothing in retrieval, generation, or either novelty check
below branches on which paper number is being generated.

Two independent mechanisms, both enforced automatically by
`src/generation/question_generator.generate_paper` before a question is
ever accepted into the paper - never left to hoping the model varies its
own output:

1. **Grounding check** (`_grounding_overlap_ok`): the generated question's
   text must share at least
   `SecurityConfig.grounding_min_overlap` (default 0.08) cosine similarity
   with its cited evidence (rules out pure invention) but no more than
   `grounding_max_overlap` (default 0.75) with any single passage (rules out
   near-verbatim copying). Independently re-checked from scratch against the
   finished paper by `src/validation/grounding_validator.py` at `validate`
   time - generation-time enforcement is never trusted blindly.

2. **Cross-paper novelty** (`src/validation/cross_paper_novelty.py`):
   `artifacts/generation-history.json` keeps a short text fingerprint of
   EVERY question ever generated for each section, across every paper
   number ever run - not a rolling window of just the last paper. Before a
   new question is accepted, it is compared (`max_similarity_to_history`)
   against EVERY entry accumulated so far for THAT SAME SECTION (could be
   0, 1, 5, or 50 prior papers - the function has no concept of "which
   paper number this is"); above `SecurityConfig.cross_paper_max_similarity`
   (default 0.6) it is rejected and regenerated with a resampled evidence
   rotation. `src/cli.py`'s `generate` command loads this history before
   generating and MERGES the new paper's questions into it after
   acceptance (`record_paper`, never replaces it) - so paper N's run always
   sees the fingerprints of every one of papers 1..N-1, automatically, with
   no code change required as N grows.

Both checks retry up to `SecurityConfig.grounding_max_retries` (default 3)
times per section before failing loudly (`GenerationError`) rather than
silently accepting a duplicate or ungrounded question - "fail loudly, never
paper over a defect" is the same principle the rest of this pipeline already
applies to marks/outcome/schema checks.

Same competency, different question, by construction: the evidence rotation
means Paper 2 can retrieve a different real passage for the same KT code
(e.g. a different page discussing OOP), and even when it retrieves the same
passage, the novelty check forces a structurally different question (a
different scenario, a different task framing) rather than a relabeled
duplicate.

## E. What is never trusted to the LLM unsupervised

Unchanged from the previous version of this note, still true after this
rework - marks, IDs, outcome coverage, official-status claims, memo
completeness, and novelty are all decided/re-checked by deterministic code,
never self-certified by the model. This rework adds grounding and
cross-paper novelty to that same list: a question's `grounding` field is
independently re-verified against the actual ingested corpus
(`grounding_validator.py` checks every cited `(document, page)` pair
actually exists - "do not fabricate page numbers" is a literal, executable
check, not a prompt instruction hoped to be followed), and a paper is never
accepted on the strength of the model saying "this is original."

## Running real generation

Once `ANTHROPIC_API_KEY` is set (`.env`, `LLM_PROVIDER=anthropic`):

```
python -m src.cli analyze
python -m src.cli generate --qualification software_developer --paper-number 1 --seed <seed>
python -m src.cli generate --qualification software_developer --paper-number 2 --seed <different-seed>
python -m src.cli validate --paper output/mock-eisa-paper-01.json --memo output/mock-eisa-memo-01.json
python -m src.cli render --paper output/mock-eisa-paper-01.json --memo output/mock-eisa-memo-01.json --pdf
```

(repeat `validate`/`render` for paper 2). `generate` prints which provider
and how many real evidence passages were retrieved before making any model
call, and refuses to proceed (loudly, not silently) if retrieval finds
nothing for a section's required outcomes - see `src/cli.py:
_build_evidence_by_section`.
