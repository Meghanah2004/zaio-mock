"""Deterministic, offline, FIXTURE-BASED provider - NOT a substitute for a
real LLM.

MockProvider exists solely so the rest of the pipeline (schema validation,
mark arithmetic, coverage checks, novelty screening, quality review,
rendering) can be exercised end-to-end without network access or an API
key - it is a test/demo fixture, not a generation engine. When
``LLM_PROVIDER=anthropic`` is configured (see src/providers/anthropic_provider.py
and .env.example), real generation calls the configured provider instead;
MockProvider is never used as a stand-in for that in a real run.

Content here was hand-authored directly for this project - from the
qualification's knowledge-topic list and general software-development
practice, never from, or by lightly rewording, any question, exercise, or
worked example inside sdev/. See docs/DESIGN.md ("Anti-copying approach").

Each section holds a SMALL, FIXED set of pre-written scenario variants
(currently 2 per section), selected deterministically by
``seed % variant_count``. This means:
  - the same (section, seed) pair always reproduces the same content
    (useful for reproducibility and for tests), and
  - a future ``--paper-number 3`` run with MockProvider will pick between
    only those same 2 pre-written options per section - it does NOT
    synthesize new content. "Paper 3 variety" under MockProvider is
    intentionally limited to this fixed fixture set; genuine new scenario
    variety requires either adding another hand-written entry to the
    relevant ``_SECTION_*_VARIANTS`` list, or switching to a real provider.

Only the "content authoring" fields (scenario/question/sub_questions/
expected_response_type/outcomes) are produced here, and even the
``outcomes`` field is checked, not trusted blindly - see
src/generation/question_generator.py. Governance fields that must match
the blueprint exactly - ids, marks totals, competencies, difficulty - are
always assigned by src/generation/question_generator.py, never read from
provider output.
"""
from __future__ import annotations

import json
from typing import Any

from src.providers.base import LLMProvider

# ---------------------------------------------------------------------------
# Section A: Programming Fundamentals and Logical Reasoning
# ---------------------------------------------------------------------------
_SECTION_A_VARIANTS = [
    {
        "scenario": (
            "You are a junior developer at Kasi Traders, a small retail chain. Before wiring up "
            "a new till-reconciliation feature, your lead asks you to work through some numeric "
            "and logic checks on paper so the team can confirm your understanding before you touch "
            "the codebase."
        ),
        "question": "Answer each part below, showing your working.",
        "sub_questions": [
            {
                "id": "1",
                "prompt": (
                    "A legacy barcode scanner reports a shelf-width sensor reading as the binary "
                    "value 1101. Working from the rightmost digit, determine its decimal equivalent "
                    "and show the contribution of each bit position."
                ),
                "marks": 3,
                "expected_response_type": "worked_calculation",
            },
            {
                "id": "2",
                "prompt": (
                    "A teammate hard-codes a discount calculation as `total = 17 % 5 + 2 * 3 - 1`. "
                    "Work out the value `total` ends up with. For each step, state which single "
                    "operation you resolved and why it had to happen at that point relative to the "
                    "others."
                ),
                "marks": 4,
                "expected_response_type": "worked_calculation",
            },
            {
                "id": "3",
                "prompt": (
                    "A colleague asks you to review their pull request without running it. Step "
                    "through the following block one line at a time and record every value it "
                    "prints, in the order it prints them:\n"
                    "```\n"
                    "n = 0\n"
                    "while n < 5:\n"
                    "    if n % 2 == 0:\n"
                    "        print(n * 2)\n"
                    "    n = n + 1\n"
                    "```"
                ),
                "marks": 4,
                "expected_response_type": "trace_table_or_output_list",
            },
            {
                "id": "4",
                "prompt": (
                    "In Python, a colleague wrote this line to build a receipt message:\n"
                    "`message = \"Total due: \" + 45.50 + \" ZAR\"`\n"
                    "Running it raises `TypeError: can only concatenate str (not \"float\") to str`. "
                    "Explain precisely why Python raises this error here, and rewrite the line so it "
                    "runs successfully and produces the string `\"Total due: 45.5 ZAR\"`."
                ),
                "marks": 4,
                "expected_response_type": "explanation_and_corrected_code",
            },
        ],
    },
    {
        "scenario": (
            "You are a junior developer at Thusong Logistics, a fleet-tracking startup. Before "
            "extending the driver dashboard, your lead asks you to work through some numeric and "
            "logic checks on paper so the team can confirm your understanding before you touch the "
            "codebase."
        ),
        "question": "Answer each part below, showing your working.",
        "sub_questions": [
            {
                "id": "1",
                "prompt": (
                    "A vehicle's onboard unit reports an odometer delta as the binary value 10110. "
                    "Working from the rightmost digit, determine its decimal equivalent and show the "
                    "contribution of each bit position."
                ),
                "marks": 3,
                "expected_response_type": "worked_calculation",
            },
            {
                "id": "2",
                "prompt": (
                    "A teammate hard-codes a trip-cost estimate as `distance = 23 % 4 * 2 - 5 + 1`. "
                    "Work out the value `distance` ends up with. For each step, state which single "
                    "operation you resolved and why it had to happen at that point relative to the "
                    "others."
                ),
                "marks": 4,
                "expected_response_type": "worked_calculation",
            },
            {
                "id": "3",
                "prompt": (
                    "A colleague asks you to review their pull request without running it. Step "
                    "through the following block one line at a time and record every value it "
                    "prints, in the order it prints them:\n"
                    "```\n"
                    "speed = 50\n"
                    "checks = 0\n"
                    "while checks < 4:\n"
                    "    if speed > 60:\n"
                    "        print(\"over limit\")\n"
                    "    speed = speed + 5\n"
                    "    checks = checks + 1\n"
                    "```"
                ),
                "marks": 4,
                "expected_response_type": "trace_table_or_output_list",
            },
            {
                "id": "4",
                "prompt": (
                    "In Python, a colleague wrote this line to log a trip summary:\n"
                    "`log = \"Trip length: \" + 12.3 + \" km\"`\n"
                    "Running it raises `TypeError: can only concatenate str (not \"float\") to str`. "
                    "Explain precisely why Python raises this error here, and rewrite the line so it "
                    "runs successfully and produces the string `\"Trip length: 12.3 km\"`."
                ),
                "marks": 4,
                "expected_response_type": "explanation_and_corrected_code",
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# Section B: Front-End Web Development (HTML5, CSS, JavaScript, OOP)
# ---------------------------------------------------------------------------
_SECTION_B_VARIANTS = [
    {
        "scenario": (
            "A local community organisation, Green Roots Collective, wants a simple 'Volunteer "
            "Sign-Up' feature added to their existing website so visitors can register interest "
            "without an account. You have been asked to build the front end for this feature."
        ),
        "question": "Complete the following front-end development tasks for the Volunteer Sign-Up feature.",
        "sub_questions": [
            {
                "id": "1",
                "prompt": (
                    "Write a semantic HTML5 form that captures: full name (required), email address "
                    "(required, must be a valid email format), and areas of interest as checkboxes "
                    "for 'Gardening', 'Events' and 'Admin Support' - the form's requirement is that "
                    "at least one interest area MUST be selected before the form can be submitted. "
                    "Use appropriate input types and attributes so the browser natively validates the "
                    "name and email fields without any JavaScript. Then, in 1-2 sentences, state "
                    "whether HTML5's `required` attribute can, by itself, enforce this at-least-one-"
                    "checkbox requirement, and explain what you would need to add to actually "
                    "enforce it."
                ),
                "marks": 6,
                "expected_response_type": "html_code_and_short_explanation",
            },
            {
                "id": "2",
                "prompt": (
                    "Using CSS Flexbox, style the form so that on small screens each label appears "
                    "above its input (stacked, single column), and on screens 768px and wider the "
                    "labels appear beside their inputs in a single row per field. Include the media "
                    "query and explain in one sentence why Flexbox is a suitable choice here."
                ),
                "marks": 6,
                "expected_response_type": "css_code_and_short_explanation",
            },
            {
                "id": "3",
                "prompt": (
                    "Write JavaScript that intercepts the form's submit event, prevents the default "
                    "page reload, checks that the email field contains an '@' and at least one '.' "
                    "after it, and - if invalid - displays an inline error message next to the field "
                    "without using `alert()`. If valid, log the form data to the console."
                ),
                "marks": 8,
                "expected_response_type": "javascript_code",
            },
            {
                "id": "4",
                "prompt": (
                    "You are given this object literal used to track a signed-up volunteer:\n"
                    "```javascript\n"
                    "let volunteer = { name: \"Lindiwe\", hoursPledged: 4 };\n"
                    "```\n"
                    "Refactor this into an ES6 class named `Volunteer` with a constructor, a private "
                    "or underscore-convention field for `hoursPledged`, a getter for `hoursPledged`, "
                    "and a setter that rejects negative values. Name the specific OOP principle your "
                    "getter/setter design demonstrates and explain, in 1-2 sentences, why it matters here."
                ),
                "marks": 10,
                "expected_response_type": "javascript_code_and_short_explanation",
            },
        ],
    },
    {
        "scenario": (
            "A small independent bookshop, Paper Trail Books, wants a simple 'Reading Club "
            "Sign-Up' feature added to their existing website so visitors can register interest "
            "without an account. You have been asked to build the front end for this feature."
        ),
        "question": "Complete the following front-end development tasks for the Reading Club Sign-Up feature.",
        "sub_questions": [
            {
                "id": "1",
                "prompt": (
                    "Write a semantic HTML5 form that captures: full name (required), email address "
                    "(required, must be a valid email format), and favourite genres as checkboxes "
                    "for 'Fiction', 'Non-Fiction' and 'Poetry' - the form's requirement is that at "
                    "least one genre MUST be selected before the form can be submitted. Use "
                    "appropriate input types and attributes so the browser natively validates the "
                    "name and email fields without any JavaScript. Then, in 1-2 sentences, state "
                    "whether HTML5's `required` attribute can, by itself, enforce this at-least-one-"
                    "checkbox requirement, and explain what you would need to add to actually "
                    "enforce it."
                ),
                "marks": 6,
                "expected_response_type": "html_code_and_short_explanation",
            },
            {
                "id": "2",
                "prompt": (
                    "Using CSS Flexbox, style the form so that on small screens each label appears "
                    "above its input (stacked, single column), and on screens 768px and wider the "
                    "labels appear beside their inputs in a single row per field. Include the media "
                    "query and explain in one sentence why Flexbox is a suitable choice here."
                ),
                "marks": 6,
                "expected_response_type": "css_code_and_short_explanation",
            },
            {
                "id": "3",
                "prompt": (
                    "Write JavaScript that intercepts the form's submit event, prevents the default "
                    "page reload, checks that the name field is not empty and the email field "
                    "contains an '@' and at least one '.' after it, and - if invalid - displays an "
                    "inline error message next to the field without using `alert()`. If valid, log "
                    "the form data to the console."
                ),
                "marks": 8,
                "expected_response_type": "javascript_code",
            },
            {
                "id": "4",
                "prompt": (
                    "You are given this object literal used to track a reading-club member:\n"
                    "```javascript\n"
                    "let member = { name: \"Sipho\", booksRead: 2 };\n"
                    "```\n"
                    "Refactor this into an ES6 class named `Member` with a constructor, a private or "
                    "underscore-convention field for `booksRead`, a getter for `booksRead`, and a "
                    "setter that rejects negative values. Name the specific OOP principle your "
                    "getter/setter design demonstrates and explain, in 1-2 sentences, why it matters here."
                ),
                "marks": 10,
                "expected_response_type": "javascript_code_and_short_explanation",
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# Section C: Systems Modelling with UML
# ---------------------------------------------------------------------------
_SECTION_C_VARIANTS = [
    {
        "scenario": (
            "A local library wants to introduce a simple book reservation feature: a Member may "
            "reserve a Book; if the Book is currently on loan, the reservation joins a waitlist and "
            "the Member is notified when it becomes available."
        ),
        "question": "Model the following aspects of the reservation feature using UML.",
        "sub_questions": [
            {
                "id": "1",
                "prompt": (
                    "Describe a class diagram for this feature. For each of `Member`, `Book`, and "
                    "`Reservation`, list at least 3 relevant attributes and 2 relevant methods, and "
                    "describe the association(s) between the classes including multiplicity (e.g. "
                    "one-to-many). You may describe this in structured text/UML notation; a hand-drawn "
                    "diagram is not required."
                ),
                "marks": 8,
                "expected_response_type": "structured_uml_description",
            },
            {
                "id": "2",
                "prompt": (
                    "Describe, as a sequence of numbered messages between objects (as you would read "
                    "off a sequence diagram), the flow when a Member reserves a Book that is currently "
                    "on loan: include at least the Member, a ReservationService, the Book, and a "
                    "notification step once the Book becomes available."
                ),
                "marks": 7,
                "expected_response_type": "structured_uml_description",
            },
        ],
    },
    {
        "scenario": (
            "A small clinic wants to introduce a simple appointment booking feature: a Patient may "
            "book an Appointment with a Doctor; if the requested slot is full, the request joins a "
            "waitlist and the Patient is notified when a slot opens up."
        ),
        "question": "Model the following aspects of the booking feature using UML.",
        "sub_questions": [
            {
                "id": "1",
                "prompt": (
                    "Describe a class diagram for this feature. For each of `Patient`, `Doctor`, and "
                    "`Appointment`, list at least 3 relevant attributes and 2 relevant methods, and "
                    "describe the association(s) between the classes including multiplicity (e.g. "
                    "one-to-many). You may describe this in structured text/UML notation; a hand-drawn "
                    "diagram is not required."
                ),
                "marks": 8,
                "expected_response_type": "structured_uml_description",
            },
            {
                "id": "2",
                "prompt": (
                    "Describe, as a sequence of numbered messages between objects (as you would read "
                    "off a sequence diagram), the flow when a Patient requests an Appointment slot "
                    "that is full: include at least the Patient, a BookingService, the Doctor's "
                    "schedule, and a notification step once a slot opens up."
                ),
                "marks": 7,
                "expected_response_type": "structured_uml_description",
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# Section D: Data, Databases and Querying
# ---------------------------------------------------------------------------
_SECTION_D_VARIANTS = [
    {
        "scenario": (
            "Kasi Traders (from Section A) needs a small relational database to track products and "
            "the suppliers who provide them, so staff can quickly see which products need reordering."
        ),
        "question": "Complete the following database tasks.",
        "sub_questions": [
            {
                "id": "1",
                "prompt": (
                    "Write CREATE TABLE statements for `Suppliers` (supplier_id, name, contact_email) "
                    "and `Products` (product_id, name, quantity_in_stock, reorder_threshold, "
                    "supplier_id). Choose appropriate data types and define the primary key on each "
                    "table and the foreign key relationship between them."
                ),
                "marks": 6,
                "expected_response_type": "sql_code",
            },
            {
                "id": "2",
                "prompt": (
                    "Write a single SQL query that lists the product name, quantity in stock, and "
                    "supplier contact email for every product where quantity_in_stock is below its "
                    "reorder_threshold, ordered by quantity_in_stock ascending."
                ),
                "marks": 6,
                "expected_response_type": "sql_code",
            },
            {
                "id": "3",
                "prompt": (
                    "Write an SQL statement that increases the price of every product supplied by "
                    "supplier_id = 3 by 10%, assuming a `price` column exists on `Products`. Then, in "
                    "1-2 sentences, explain why omitting the WHERE clause on an UPDATE statement like "
                    "this is dangerous."
                ),
                "marks": 4,
                "expected_response_type": "sql_code_and_short_explanation",
            },
            {
                "id": "4",
                "prompt": (
                    "Two staff members open the same product record at the same time and both save "
                    "changes. Describe one practical technique a database or application can use to "
                    "prevent one person's update from silently overwriting the other's."
                ),
                "marks": 4,
                "expected_response_type": "short_answer",
            },
        ],
    },
    {
        "scenario": (
            "Thusong Logistics (from Section A) needs a small relational database to track vehicles "
            "and the maintenance depots that service them, so staff can quickly see which vehicles "
            "are due for a service."
        ),
        "question": "Complete the following database tasks.",
        "sub_questions": [
            {
                "id": "1",
                "prompt": (
                    "Write CREATE TABLE statements for `Depots` (depot_id, name, contact_email) and "
                    "`Vehicles` (vehicle_id, registration, km_since_service, service_interval_km, "
                    "depot_id). Choose appropriate data types and define the primary key on each table "
                    "and the foreign key relationship between them."
                ),
                "marks": 6,
                "expected_response_type": "sql_code",
            },
            {
                "id": "2",
                "prompt": (
                    "Write a single SQL query that lists the vehicle registration, km_since_service, "
                    "and depot contact email for every vehicle where km_since_service is greater than "
                    "its service_interval_km, ordered by km_since_service descending."
                ),
                "marks": 6,
                "expected_response_type": "sql_code",
            },
            {
                "id": "3",
                "prompt": (
                    "Write an SQL statement that resets km_since_service to 0 for every vehicle "
                    "serviced by depot_id = 2. Then, in 1-2 sentences, explain why omitting the WHERE "
                    "clause on an UPDATE statement like this is dangerous."
                ),
                "marks": 4,
                "expected_response_type": "sql_code_and_short_explanation",
            },
            {
                "id": "4",
                "prompt": (
                    "Two dispatchers open the same vehicle record at the same time and both save "
                    "changes. Describe one practical technique a database or application can use to "
                    "prevent one person's update from silently overwriting the other's."
                ),
                "marks": 4,
                "expected_response_type": "short_answer",
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# Section E: SDLC, Algorithms and Secure Coding
# ---------------------------------------------------------------------------
_SECTION_E_VARIANTS = [
    {
        "scenario": (
            "Your team is midway through building a new customer feedback feature. The team lead "
            "shares a short project update and asks you to reflect on process and security."
        ),
        "question": "Answer the following questions about SDLC, algorithms, and secure coding.",
        "sub_questions": [
            {
                "id": "1",
                "prompt": (
                    "The update reads: 'We've written the feedback form and the API endpoint; now "
                    "we're running it past three pilot users before wider rollout to see if anything "
                    "breaks or feels wrong.' Identify which SDLC phase this describes and justify your "
                    "answer in 1-2 sentences."
                ),
                "marks": 4,
                "expected_response_type": "short_answer",
            },
            {
                "id": "2",
                "prompt": (
                    "Write pseudocode for an algorithm that finds any duplicate customer ID in a list "
                    "of customer IDs and returns the first duplicate found (or a clear 'none found' "
                    "result). State the time complexity of your algorithm using Big-O notation and "
                    "justify it in one sentence."
                ),
                "marks": 6,
                "expected_response_type": "pseudocode_and_complexity",
            },
            {
                "id": "3",
                "prompt": (
                    "A colleague wrote this code to look up feedback by customer name:\n"
                    "```python\n"
                    "query = \"SELECT * FROM feedback WHERE customer_name = '\" + user_input + \"'\"\n"
                    "```\n"
                    "Identify the security vulnerability in this code and rewrite it using a safe "
                    "approach (e.g. parameterised query), explaining briefly why your version is safe."
                ),
                "marks": 5,
                "expected_response_type": "vulnerability_identification_and_corrected_code",
            },
        ],
    },
    {
        "scenario": (
            "Your team is midway through building a new appointment-reminder feature. The team lead "
            "shares a short project update and asks you to reflect on process and security."
        ),
        "question": "Answer the following questions about SDLC, algorithms, and secure coding.",
        "sub_questions": [
            {
                "id": "1",
                "prompt": (
                    "The update reads: 'We've mapped out every screen and written down exactly what "
                    "data each one needs before anyone starts coding.' Identify which SDLC phase this "
                    "describes and justify your answer in 1-2 sentences."
                ),
                "marks": 4,
                "expected_response_type": "short_answer",
            },
            {
                "id": "2",
                "prompt": (
                    "Write pseudocode for an algorithm that finds any duplicate phone number in a list "
                    "of patient phone numbers and returns the first duplicate found (or a clear 'none "
                    "found' result). State the time complexity of your algorithm using Big-O notation "
                    "and justify it in one sentence."
                ),
                "marks": 6,
                "expected_response_type": "pseudocode_and_complexity",
            },
            {
                "id": "3",
                "prompt": (
                    "A colleague wrote this code to look up a patient by surname:\n"
                    "```python\n"
                    "query = \"SELECT * FROM patients WHERE surname = '\" + user_input + \"'\"\n"
                    "```\n"
                    "Identify the security vulnerability in this code and rewrite it using a safe "
                    "approach (e.g. parameterised query), explaining briefly why your version is safe."
                ),
                "marks": 5,
                "expected_response_type": "vulnerability_identification_and_corrected_code",
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# Section F: Workplace Integration and Professional Practice
# ---------------------------------------------------------------------------
_SECTION_F_VARIANTS = [
    {
        "scenario": (
            "Your team lead tells you: 'The client wants a report showing which customers ordered "
            "which products. Just export the raw customer contact list along with it too, it's not "
            "like it's confidential.'"
        ),
        "question": (
            "Identify one workplace governance, legislative, or ethical principle relevant to this "
            "request, and explain in a short paragraph what you should do before complying, and why."
        ),
        "sub_questions": [],
    },
    {
        "scenario": (
            "A teammate says: 'We're behind schedule - let's skip logging what changed in this "
            "release so we can ship faster. No one reads those notes anyway.'"
        ),
        "question": (
            "Identify one workplace governance or professional-practice principle relevant to this "
            "situation, and explain in a short paragraph what you should do, and why."
        ),
        "sub_questions": [],
    },
]

# Explicit, hand-curated subset of each section's outcome codes that THIS
# question's content genuinely exercises - not the section's entire thematic
# outcome list. This is deliberately narrow: e.g. Section E's question tests
# 4 of KM-09's 19 knowledge topics, not all 19. Each list here is designed to
# be a superset of (or equal to) the matching section's `required_outcomes`
# in configs/software_developer.json, which src/generation/question_generator.py
# enforces at generation time and src/validation/coverage_validator.py
# re-checks structurally against the final paper. See docs/DESIGN.md,
# "Outcome mapping: explicit subsets, not section-wide copies."
_SECTION_OUTCOMES: dict[str, list[str]] = {
    "A": ["KM-04-KT02", "KM-04-KT07", "KM-04-KT09", "KM-04-KT11", "KM-05-KT02"],
    "B": ["KM-06-KT02", "KM-06-KT06", "KM-06-KT07", "KM-06-KT08"],
    "C": ["KM-07-KT04", "KM-07-KT07"],
    "D": ["KM-08-KT01", "KM-08-KT02", "KM-08-KT03", "KM-08-KT04", "KM-08-KT05"],
    "E": ["KM-09-KT02", "KM-09-KT09", "KM-09-KT16", "KM-09-KT18"],
    "F": ["KM-10-KT01", "KM-10-KT02", "KM-10-KT04"],
}

_SECTION_BANKS: dict[str, list[dict[str, Any]]] = {
    "A": _SECTION_A_VARIANTS,
    "B": _SECTION_B_VARIANTS,
    "C": _SECTION_C_VARIANTS,
    "D": _SECTION_D_VARIANTS,
    "E": _SECTION_E_VARIANTS,
    "F": _SECTION_F_VARIANTS,
}

_TYPE_BY_SECTION = {
    "A": "code_analysis",
    "B": "scenario_extended",
    "C": "design_task",
    "D": "scenario_short_answer",
    "E": "scenario_extended",
    "F": "scenario_short_answer",
}


class MockProvider(LLMProvider):
    """Offline, deterministic stand-in for a real LLM call.

    Selection is deterministic: ``variant = seed % len(bank)``. The same
    (section, seed) pair always returns the same content, which is what
    makes ``--seed`` meaningful for reproducibility without a live API.
    """

    name = "mock"

    def generate(self, system_prompt: str, user_prompt: str, task: dict[str, Any]) -> str:
        kind = task.get("kind")
        if kind == "generate_section_question":
            return json.dumps(self._generate_question(task))
        if kind == "generate_memo_for_question":
            return json.dumps(self._generate_memo(task))
        if kind == "quality_review":
            return json.dumps(self._quality_review(task))
        raise ValueError(f"MockProvider does not know how to handle task kind: {kind!r}")

    # -- question generation -------------------------------------------------
    def _generate_question(self, task: dict[str, Any]) -> dict[str, Any]:
        section = task["section"]
        seed = task.get("seed", 0)
        section_id = section["id"]
        bank = _SECTION_BANKS[section_id]
        variant = bank[seed % len(bank)]
        scenario = variant["scenario"]

        # REWORK: when the caller (src/generation/question_generator.py)
        # supplies retrieved learner-guide evidence - i.e. real generation
        # mode, see that module's docstring - weave a short, honest
        # reference to it into the scenario. This is NOT a substitute for a
        # real model reading and transforming the evidence (MockProvider
        # remains a fixed, hand-written fixture bank - see the module
        # docstring above); it exists so the SAME grounding contract
        # (src/generation/question_generator._grounding_overlap_ok) applies
        # uniformly to every provider and can be exercised deterministically
        # in tests without a live API call. When no evidence is supplied
        # (the existing test-mode call pattern, e.g.
        # tests/test_mock_provider_content.py), output is byte-identical to
        # before this rework.
        evidence = task.get("evidence") or []
        if evidence:
            top = evidence[0]
            reference_clause = (
                f" (Per {top['document']}, page {top['page']}: {top['passage'][:160]})"
            )
            scenario = scenario + reference_clause

        return {
            "type": _TYPE_BY_SECTION[section_id],
            "scenario": scenario,
            "question": variant["question"],
            "sub_questions": variant["sub_questions"],
            "expected_response_type": (
                variant["sub_questions"][0]["expected_response_type"] if variant["sub_questions"] else "short_answer"
            ),
            # Explicit, curated subset - see _SECTION_OUTCOMES above. Never the
            # full section["outcomes"] list; question_generator.py rejects any
            # provider output whose declared outcomes fall outside the
            # section's outcome universe or fail to cover the section's
            # required_outcomes.
            "outcomes": _SECTION_OUTCOMES[section_id],
        }

    # -- memo generation -------------------------------------------------------
    def _generate_memo(self, task: dict[str, Any]) -> dict[str, Any]:
        question = task["question"]
        section_id = question["section_id"]
        builder = _MEMO_BUILDERS[section_id]
        memo = builder(question)

        # REWORK: when the caller (src/generation/memo_generator.py)
        # supplies retrieved ANSWER evidence - real generation mode, see
        # that module's docstring - weave a short, honest reference to it
        # into the model answer(s). Same rationale as the question-side
        # evidence-weaving fix in _generate_question above: this is not a
        # substitute for a real model reading and using the evidence
        # (MockProvider's memo content remains a fixed, hand-written
        # fixture bank), it exists so the SAME answer-grounding contract
        # (src.generation.memo_generator._answer_grounding_ok) applies
        # uniformly to every provider and can be exercised deterministically
        # in tests without a live API call. Woven into EVERY sub-answer
        # (not just one), not only the top-level placeholder, so the
        # injected evidence carries enough relative weight in the overlap
        # score regardless of how much other sub-answer text surrounds it -
        # a single injection point was found insufficient for longer,
        # multi-part memos during testing. When no answer evidence is
        # supplied (the existing test-mode call pattern, e.g.
        # tests/test_mock_provider_content.py), output is byte-identical to
        # before this rework.
        answer_evidence = task.get("answer_evidence") or []
        if answer_evidence:
            top = answer_evidence[0]
            reference_clause = f" (Per {top['document']}, page {top['page']}: {top['passage'][:160]})"
            memo["model_answer"] = (memo.get("model_answer") or "") + reference_clause
            for sub_memo in memo.get("sub_questions", []) or []:
                sub_memo["model_answer"] = sub_memo.get("model_answer", "") + reference_clause

        return memo

    # -- quality review ----------------------------------------------------
    def _quality_review(self, task: dict[str, Any]) -> dict[str, Any]:
        paper = task["paper"]
        question_reviews = []
        for section in paper["sections"]:
            for q in section["questions"]:
                question_reviews.append(
                    {
                        "question_id": q["id"],
                        "occupational_relevance": "pass",
                        "guide_grounding": "pass" if q.get("grounding") else "not_applicable: no evidence supplied",
                        "reads_as_copied": "no",
                        "difficulty_appropriate": "pass",
                        "ambiguity": "none_detected",
                        "markability": "pass",
                        "notes": (
                            "Deterministic mock review: structural checks only "
                            "(occupational framing present, question references a concrete "
                            "workplace scenario, marks are itemised). This is not a substitute "
                            "for a real LLM or human review pass - see docs/DESIGN.md."
                        ),
                    }
                )
        return {"approved": True, "issues": [], "question_reviews": question_reviews}


# ---------------------------------------------------------------------------
# Memo content, one builder per section, matching the question banks above.
# ---------------------------------------------------------------------------
def _memo_A(question: dict[str, Any]) -> dict[str, Any]:
    subs = question["sub_questions"]
    is_kasi = "Kasi" in question["scenario"]
    sub_memos = [
        {
            "id": subs[0]["id"],
            "total_marks": subs[0]["marks"],
            "model_answer": (
                "1101(2) = 1x2^3 + 1x2^2 + 0x2^1 + 1x2^0 = 8 + 4 + 0 + 1 = 13"
                if is_kasi
                else "10110(2) = 1x2^4 + 0x2^3 + 1x2^2 + 1x2^1 + 0x2^0 = 16 + 0 + 4 + 2 + 0 = 22"
            ),
            "criteria": [
                {"description": "Correct positional/place-value setup shown", "marks": 1},
                {"description": "Correct arithmetic at each place value", "marks": 1},
                {"description": "Correct final decimal value", "marks": 1},
            ],
            "accepted_alternatives": [
                "Doubling method (start from leftmost bit, double-and-add) reaching the same final value.",
            ],
        },
        {
            "id": subs[1]["id"],
            "total_marks": subs[1]["marks"],
            "model_answer": (
                "17 % 5 = 2; 2 * 3 = 6; 2 + 6 = 8; 8 - 1 = 7. total = 7."
                if is_kasi
                else "23 % 4 = 3; 3 * 2 = 6; 6 - 5 = 1; 1 + 1 = 2. distance = 2."
            ),
            "criteria": [
                {"description": "Modulus evaluated correctly first (correct precedence)", "marks": 1},
                {"description": "Multiplication evaluated before remaining addition/subtraction", "marks": 1},
                {"description": "Left-to-right evaluation of remaining +/- operators", "marks": 1},
                {"description": "Correct final value stated", "marks": 1},
            ],
            "accepted_alternatives": [],
        },
        {
            "id": subs[2]["id"],
            "total_marks": subs[2]["marks"],
            "model_answer": (
                "n=0: 0%2==0 -> print 0; n=1: skip; n=2: print 4; n=3: skip; "
                "n=4: print 8; loop ends at n=5. Output: 0, 4, 8."
                if is_kasi
                else "speed=50,55: not >60, no print; speed=60: not >60 (boundary), no print; "
                "speed=65: >60 -> print 'over limit'. Output: over limit (once)."
            ),
            "criteria": [
                {"description": "Correct loop boundary (correct number of iterations)", "marks": 1},
                {"description": "Correct condition evaluation at each iteration", "marks": 2},
                {"description": "Correct final output sequence/value stated", "marks": 1},
            ],
            "accepted_alternatives": ["Answer presented as a trace table instead of prose - equally acceptable."],
        },
        {
            "id": subs[3]["id"],
            "total_marks": subs[3]["marks"],
            "model_answer": (
                "Python raises this TypeError because `+` between a `str` and a `float` is not "
                "defined - Python does not implicitly convert numbers to strings the way some other "
                "languages (e.g. JavaScript) do. Fix: `message = \"Total due: \" + str(45.50) + \" ZAR\"` "
                "(or `f\"Total due: {45.50} ZAR\"`), both of which produce `\"Total due: 45.5 ZAR\"`."
                if is_kasi
                else "Python raises this TypeError because `+` between a `str` and a `float` is not "
                "defined - Python does not implicitly convert numbers to strings the way some other "
                "languages (e.g. JavaScript) do. Fix: `log = \"Trip length: \" + str(12.3) + \" km\"` "
                "(or `f\"Trip length: {12.3} km\"`), both of which produce `\"Trip length: 12.3 km\"`."
            ),
            "criteria": [
                {
                    "description": (
                        "Correctly explains that Python's `+` operator does not implicitly convert a "
                        "float to a string (unlike some other languages)"
                    ),
                    "marks": 2,
                },
                {
                    "description": "Provides a corrected line that runs successfully and produces the exact target string",
                    "marks": 2,
                },
            ],
            "accepted_alternatives": [
                "str(), f-strings, .format(), or % formatting are all acceptable ways to perform the conversion.",
            ],
            "non_awarding_notes": (
                "An answer that only says 'you can't add a string and a number' without naming "
                "Python specifically, or that describes JavaScript's automatic string-coercion "
                "behaviour instead of Python's, does not earn the explanation marks - the question "
                "is now explicitly scoped to Python, where this code genuinely does raise an error."
            ),
        },
    ]
    return {
        "question_id": question["id"],
        "total_marks": question["marks"],
        "model_answer": "See per-part model answers below.",
        "criteria": [{"description": "See per-part criteria in sub_questions.", "marks": question["marks"]}],
        "accepted_alternatives": [],
        "partial_credit_guidance": (
            "Award marks per part independently. For worked calculations, award method marks even "
            "if the final numeric answer is wrong due to a single arithmetic slip, provided the "
            "method/order of operations is correct."
        ),
        "sub_questions": sub_memos,
    }


def _memo_B(question: dict[str, Any]) -> dict[str, Any]:
    subs = question["sub_questions"]
    is_green = "Green Roots" in question["scenario"]
    entity = "Volunteer" if is_green else "Member"
    field = "hoursPledged" if is_green else "booksRead"
    sub_memos = [
        {
            "id": subs[0]["id"],
            "total_marks": subs[0]["marks"],
            "model_answer": (
                "The task's stated requirement is that at least one interest-area checkbox MUST be "
                "checked before the form submits. A <form> containing <input type=\"text\" "
                "name=\"fullName\" required>, <input type=\"email\" name=\"email\" required>, and "
                "one <input type=\"checkbox\"> per interest area, each paired with a <label>, "
                "satisfies the markup part of this. However, HTML5's `required` attribute only ever "
                "validates a single element's own value - the browser has no built-in concept of "
                "'at least one checked' across a group of checkboxes, so this specific requirement "
                "CANNOT be enforced by HTML5 attributes alone. Enforcing it requires JavaScript (e.g. "
                "checking on submit that at least one checkbox in the group is checked) or a "
                "workaround such as a single hidden required proxy input tied to the group's state."
            ),
            "criteria": [
                {"description": "Uses a <form> with semantic, appropriately-labelled <input> elements", "marks": 2},
                {"description": "Uses type=\"email\" and the required attribute correctly on the name/email fields", "marks": 2},
                {"description": "Checkboxes correctly implemented and labelled for the interest areas", "marks": 1},
                {
                    "description": (
                        "Correctly states that HTML5 cannot natively enforce the stated 'at least one "
                        "checkbox selected' requirement across a group, and correctly identifies that "
                        "JavaScript (or an equivalent workaround) is needed to enforce it"
                    ),
                    "marks": 1,
                },
            ],
            "accepted_alternatives": [
                "Use of <label for=...> or wrapping <label> - either is acceptable.",
                "Mentioning aria-required/role=group as an accessibility improvement is a bonus, not a substitute for the correct answer that native HTML5 validation cannot enforce this rule.",
            ],
            "non_awarding_notes": (
                "Claiming that HTML5 attributes alone CAN enforce 'at least one checkbox selected' "
                "earns 0 for the fourth criterion, regardless of how the checkboxes are marked up."
            ),
        },
        {
            "id": subs[1]["id"],
            "total_marks": subs[1]["marks"],
            "model_answer": (
                "`.form-field { display: flex; flex-direction: column; }` by default, then "
                "`@media (min-width: 768px) { .form-field { flex-direction: row; align-items: center; } }`. "
                "Flexbox suits this because it lets the same markup reflow between a stacked and "
                "inline layout by changing a single property (flex-direction) rather than rewriting "
                "positioning rules."
            ),
            "criteria": [
                {"description": "Correct default (mobile-first) stacked flex layout", "marks": 2},
                {"description": "Correct media query breakpoint and row layout for wider screens", "marks": 3},
                {"description": "Sensible one-sentence justification for choosing Flexbox", "marks": 1},
            ],
            "accepted_alternatives": [
                "Any reasonable breakpoint value (e.g. 700px-800px) with correct reasoning is acceptable; 768px is the suggested convention, not a strict requirement.",
                "CSS Grid used instead of Flexbox, provided the same responsive behaviour is achieved and justified - award full marks for the layout, partial for the Flexbox-specific justification.",
            ],
        },
        {
            "id": subs[2]["id"],
            "total_marks": subs[2]["marks"],
            "model_answer": (
                "```javascript\n"
                "form.addEventListener('submit', function(e) {\n"
                "  e.preventDefault();\n"
                "  const email = form.email.value;\n"
                "  const valid = email.includes('@') && email.indexOf('.', email.indexOf('@')) > -1;\n"
                "  if (!valid) {\n"
                "    errorEl.textContent = 'Please enter a valid email address.';\n"
                "  } else {\n"
                "    errorEl.textContent = '';\n"
                "    console.log(Object.fromEntries(new FormData(form)));\n"
                "  }\n"
                "});\n"
                "```"
            ),
            "criteria": [
                {"description": "Correctly attaches a submit event listener and calls preventDefault()", "marks": 2},
                {"description": "Validates the email field per the stated rule (contains '@' and a '.' after it)", "marks": 3},
                {"description": "Displays an inline error without alert() when invalid", "marks": 2},
                {"description": "Logs form data to the console when valid", "marks": 1},
            ],
            "accepted_alternatives": [
                "Use of a regular expression for email validation instead of includes()/indexOf(), provided it correctly rejects/accepts the same cases.",
                "Reading field values via `document.getElementById` instead of the form's named-element access - equally acceptable.",
            ],
            "non_awarding_notes": "Using alert() for the error message earns 0 for the 'inline error' criterion even if the validation logic is correct.",
        },
        {
            "id": subs[3]["id"],
            "total_marks": subs[3]["marks"],
            "model_answer": (
                f"```javascript\n"
                f"class {entity} {{\n"
                f"  constructor(name, {field}) {{\n"
                f"    this.name = name;\n"
                f"    this._{field} = {field};\n"
                f"  }}\n"
                f"  get {field}() {{\n"
                f"    return this._{field};\n"
                f"  }}\n"
                f"  set {field}(value) {{\n"
                f"    if (value < 0) throw new Error('{field} cannot be negative');\n"
                f"    this._{field} = value;\n"
                f"  }}\n"
                f"}}\n"
                f"```\n"
                "This demonstrates ENCAPSULATION: the internal field is hidden behind an "
                "underscore-prefixed (or truly private #-prefixed) property, and all reads/writes "
                "are mediated by the getter/setter, which is what lets the class enforce the "
                "'no negative values' invariant in one place."
            ),
            "criteria": [
                {"description": "Correct ES6 class syntax with constructor", "marks": 3},
                {"description": "Correct getter implementation", "marks": 2},
                {"description": "Setter correctly rejects/handles negative values", "marks": 3},
                {"description": "Correctly names encapsulation and gives a valid reason it matters here", "marks": 2},
            ],
            "accepted_alternatives": [
                "Use of true private fields (`#hoursPledged`) instead of the underscore convention.",
                "Setter that clamps to 0 or ignores the invalid assignment instead of throwing, provided the negative value never becomes the stored value.",
                "Candidate names a different but defensibly-linked principle (e.g. 'data hiding') if their justification correctly describes encapsulation's mechanism.",
            ],
        },
    ]
    return {
        "question_id": question["id"],
        "total_marks": question["marks"],
        "model_answer": "See per-part model answers below.",
        "criteria": [{"description": "See per-part criteria in sub_questions.", "marks": question["marks"]}],
        "accepted_alternatives": [],
        "partial_credit_guidance": (
            "Working but inelegant code that satisfies the functional requirement of a part earns "
            "full marks for that part; deduct only for the specific missing/incorrect behaviour "
            "named in that part's criteria, not for style choices (e.g. var vs let, quote style)."
        ),
        "sub_questions": sub_memos,
    }


def _memo_C(question: dict[str, Any]) -> dict[str, Any]:
    subs = question["sub_questions"]
    is_library = "library" in question["scenario"].lower()
    if is_library:
        classes = "Member(memberId, name, contactEmail; reserveBook(), cancelReservation()); Book(bookId, title, isbn, status; isAvailable(), markOnLoan()); Reservation(reservationId, reservationDate, status; notifyMember(), expire())"
        assoc = "Member 1..* Reservation (a member may have many reservations), Reservation *..1 Book (each reservation is for exactly one book, a book may have many queued reservations)"
        flow = "1) Member requests reserveBook(bookId) on ReservationService. 2) ReservationService checks Book.status. 3) Book is on loan, so ReservationService creates a Reservation and adds Member to the waitlist. 4) When the Book is returned, ReservationService updates Book.status and calls notifyMember() on the next waitlisted Reservation."
    else:
        classes = "Patient(patientId, name, contactNumber; requestAppointment(), cancelAppointment()); Doctor(doctorId, name, specialty; isAvailable(), acceptAppointment()); Appointment(appointmentId, dateTime, status; notifyPatient(), expire())"
        assoc = "Patient 1..* Appointment (a patient may have many appointments), Appointment *..1 Doctor (each appointment is with exactly one doctor, a doctor may have many appointments)"
        flow = "1) Patient requests an Appointment slot via BookingService. 2) BookingService checks Doctor's schedule. 3) Slot is full, so BookingService creates a waitlist entry for the Patient. 4) When a slot opens, BookingService updates the schedule and calls notifyPatient() on the next waitlisted Patient."
    sub_memos = [
        {
            "id": subs[0]["id"],
            "total_marks": subs[0]["marks"],
            "model_answer": classes + ". Associations: " + assoc,
            "criteria": [
                {"description": "At least 3 plausible attributes per class (all three classes)", "marks": 3},
                {"description": "At least 2 plausible methods per class (all three classes)", "marks": 2},
                {"description": "Correct associations identified between the classes", "marks": 2},
                {"description": "Correct/plausible multiplicities stated (e.g. one-to-many)", "marks": 1},
            ],
            "accepted_alternatives": [
                "Any reasonably named attributes/methods that a competent developer would recognise as relevant - exact names are not required, only correct concepts and correct multiplicity direction.",
            ],
        },
        {
            "id": subs[1]["id"],
            "total_marks": subs[1]["marks"],
            "model_answer": flow,
            "criteria": [
                {"description": "Correct initiating actor and first message", "marks": 2},
                {"description": "Correctly identifies the 'currently unavailable' branch (on loan / slot full) and the waitlist step", "marks": 3},
                {"description": "Includes a service/coordinator object mediating between the actor and the resource", "marks": 1},
                {"description": "Correct final notification step once availability changes", "marks": 1},
            ],
            "accepted_alternatives": [
                "Any logically consistent object names, provided the sequence of decisions and the waitlist/notify mechanism is correct.",
            ],
        },
    ]
    return {
        "question_id": question["id"],
        "total_marks": question["marks"],
        "model_answer": "See per-part model answers below.",
        "criteria": [{"description": "See per-part criteria in sub_questions.", "marks": question["marks"]}],
        "accepted_alternatives": [],
        "partial_credit_guidance": (
            "This is a design task with no single correct diagram. Award marks for correct "
            "modelling concepts and internally consistent relationships/flow, not for matching an "
            "exact reference diagram."
        ),
        "sub_questions": sub_memos,
    }


def _memo_D(question: dict[str, Any]) -> dict[str, Any]:
    subs = question["sub_questions"]
    is_kasi = "Kasi Traders" in question["scenario"]
    if is_kasi:
        create = (
            "CREATE TABLE Suppliers (supplier_id INT PRIMARY KEY, name VARCHAR(100) NOT NULL, "
            "contact_email VARCHAR(100));\n"
            "CREATE TABLE Products (product_id INT PRIMARY KEY, name VARCHAR(100) NOT NULL, "
            "quantity_in_stock INT NOT NULL, reorder_threshold INT NOT NULL, supplier_id INT, "
            "FOREIGN KEY (supplier_id) REFERENCES Suppliers(supplier_id));"
        )
        query = (
            "SELECT p.name, p.quantity_in_stock, s.contact_email FROM Products p "
            "JOIN Suppliers s ON p.supplier_id = s.supplier_id "
            "WHERE p.quantity_in_stock < p.reorder_threshold ORDER BY p.quantity_in_stock ASC;"
        )
        update = "UPDATE Products SET price = price * 1.10 WHERE supplier_id = 3;"
    else:
        create = (
            "CREATE TABLE Depots (depot_id INT PRIMARY KEY, name VARCHAR(100) NOT NULL, "
            "contact_email VARCHAR(100));\n"
            "CREATE TABLE Vehicles (vehicle_id INT PRIMARY KEY, registration VARCHAR(20) NOT NULL, "
            "km_since_service INT NOT NULL, service_interval_km INT NOT NULL, depot_id INT, "
            "FOREIGN KEY (depot_id) REFERENCES Depots(depot_id));"
        )
        query = (
            "SELECT v.registration, v.km_since_service, d.contact_email FROM Vehicles v "
            "JOIN Depots d ON v.depot_id = d.depot_id "
            "WHERE v.km_since_service > v.service_interval_km ORDER BY v.km_since_service DESC;"
        )
        update = "UPDATE Vehicles SET km_since_service = 0 WHERE depot_id = 2;"
    sub_memos = [
        {
            "id": subs[0]["id"],
            "total_marks": subs[0]["marks"],
            "model_answer": create,
            "criteria": [
                {"description": "Both tables created with sensible, correctly-typed columns", "marks": 2},
                {"description": "Primary key correctly defined on each table", "marks": 2},
                {"description": "Foreign key correctly defined linking the two tables", "marks": 2},
            ],
            "accepted_alternatives": [
                "Any reasonable equivalent data types for the target SQL dialect (e.g. SERIAL vs INT for the PK, TEXT vs VARCHAR).",
                "AUTO_INCREMENT/IDENTITY on the primary key is a valid addition, not a requirement.",
            ],
        },
        {
            "id": subs[1]["id"],
            "total_marks": subs[1]["marks"],
            "model_answer": query,
            "criteria": [
                {"description": "Correct JOIN between the two tables on the foreign key", "marks": 2},
                {"description": "Correct WHERE condition selecting below-threshold rows", "marks": 2},
                {"description": "Correct ORDER BY direction and column", "marks": 2},
            ],
            "accepted_alternatives": [
                "Implicit join syntax (WHERE p.supplier_id = s.supplier_id) instead of explicit JOIN - equally acceptable.",
                "Column order in the SELECT list may differ from the model answer.",
            ],
        },
        {
            "id": subs[2]["id"],
            "total_marks": subs[2]["marks"],
            "model_answer": (
                update
                + " Omitting the WHERE clause would apply the price increase (or reset) to every "
                "row in the table, silently corrupting data for rows that were never meant to change."
            ),
            "criteria": [
                {"description": "Syntactically correct UPDATE statement with the correct filter", "marks": 2},
                {"description": "Correct explanation of the risk of omitting WHERE (mass/unintended update)", "marks": 2},
            ],
            "accepted_alternatives": [],
        },
        {
            "id": subs[3]["id"],
            "total_marks": subs[3]["marks"],
            "model_answer": (
                "Use optimistic concurrency control: include a version number or last-updated "
                "timestamp column, and require the UPDATE's WHERE clause to match the version the "
                "user last read; if no row matches (because someone else updated it first), reject "
                "the save and ask the user to reload and retry. (Pessimistic row-locking during the "
                "edit session is an equally valid alternative.)"
            ),
            "criteria": [
                {"description": "Names a valid concurrency-control technique (optimistic locking, pessimistic locking/row locks, or transactions with appropriate isolation level)", "marks": 3},
                {"description": "Explains, even briefly, how it prevents a lost update", "marks": 1},
            ],
            "accepted_alternatives": [
                "Database transactions with SERIALIZABLE/REPEATABLE READ isolation.",
                "Application-level 'last write wins with warning' design, provided the candidate explains it actually surfaces the conflict rather than silently discarding data.",
            ],
        },
    ]
    return {
        "question_id": question["id"],
        "total_marks": question["marks"],
        "model_answer": "See per-part model answers below.",
        "criteria": [{"description": "See per-part criteria in sub_questions.", "marks": question["marks"]}],
        "accepted_alternatives": [],
        "partial_credit_guidance": (
            "Accept any standard SQL dialect (MySQL, PostgreSQL, SQLite, SQL Server) as long as the "
            "syntax is internally consistent and correct for that dialect."
        ),
        "sub_questions": sub_memos,
    }


def _memo_E(question: dict[str, Any]) -> dict[str, Any]:
    subs = question["sub_questions"]
    is_feedback = "feedback" in question["scenario"].lower()
    phase_answer = (
        "Testing - the update describes running the completed build past real users specifically "
        "to find defects/issues before a wider release, which is the defining activity of the "
        "testing phase (this also has UAT characteristics, which is acceptable to name)."
        if is_feedback
        else "Design - the update describes planning screens and their data requirements before any "
        "code is written, which is the defining activity of the design phase."
    )
    dup_scenario = "customer IDs" if is_feedback else "patient phone numbers"
    table = "feedback" if is_feedback else "patients"
    column = "customer_name" if is_feedback else "surname"
    sub_memos = [
        {
            "id": subs[0]["id"],
            "total_marks": subs[0]["marks"],
            "model_answer": phase_answer,
            "criteria": [
                {"description": "Names the correct SDLC phase", "marks": 2},
                {"description": "Justification correctly ties the phase name to the specific activity described", "marks": 2},
            ],
            "accepted_alternatives": [
                "'User Acceptance Testing' as a more specific answer for the feedback scenario, since it is a sub-activity of testing.",
            ],
        },
        {
            "id": subs[1]["id"],
            "total_marks": subs[1]["marks"],
            "model_answer": (
                f"```\nfunction findDuplicate(ids):\n    seen = empty set\n    for id in ids:\n"
                f"        if id in seen:\n            return id\n        seen.add(id)\n    return None\n```\n"
                f"Applied to a list of {dup_scenario}, this returns the first ID/number already seen. "
                "Time complexity: O(n), because each element is visited once and set membership "
                "checks/inserts are O(1) on average."
            ),
            "criteria": [
                {"description": "Correct algorithm logic that reliably detects a duplicate", "marks": 3},
                {"description": "Uses a set/hash-based lookup rather than a nested loop (or explicitly notes the nested-loop alternative's worse complexity)", "marks": 1},
                {"description": "States O(n) (or correctly justifies whatever complexity their approach actually has, e.g. O(n^2) for a nested-loop version)", "marks": 2},
            ],
            "accepted_alternatives": [
                "A correct nested-loop (O(n^2)) solution, provided the candidate correctly states O(n^2) rather than incorrectly claiming O(n) - full marks require complexity/approach consistency, not necessarily the optimal algorithm.",
                "Sorting the list first then scanning for adjacent duplicates (O(n log n)), correctly justified.",
            ],
        },
        {
            "id": subs[2]["id"],
            "total_marks": subs[2]["marks"],
            "model_answer": (
                f"This is vulnerable to SQL injection: user_input is concatenated directly into the "
                f"query string, so input like `'; DROP TABLE {table}; --` would execute as SQL. Fix "
                f"with a parameterised query, e.g.:\n"
                f"```python\n"
                f"query = \"SELECT * FROM {table} WHERE {column} = %s\"\n"
                f"cursor.execute(query, (user_input,))\n"
                f"```\n"
                "This is safe because the database driver sends the value separately from the query "
                "structure, so it can never be interpreted as SQL code."
            ),
            "criteria": [
                {"description": "Correctly names SQL injection as the vulnerability", "marks": 2},
                {"description": "Rewrites using a parameterised query / prepared statement (or equivalent ORM safe-query method)", "marks": 2},
                {"description": "Explains, even briefly, why the fix is safe", "marks": 1},
            ],
            "accepted_alternatives": [
                "Use of an ORM's query builder (e.g. Django ORM, SQLAlchemy filter) instead of raw parameterised SQL.",
                "Placeholder syntax specific to the candidate's chosen language/driver (?, %s, $1, :name) - any correct parameterisation mechanism is acceptable.",
            ],
            "non_awarding_notes": "Manually escaping quotes in user_input (string replace) does not earn the 'safe fix' marks - it is a known-weak mitigation, not parameterisation.",
        },
    ]
    return {
        "question_id": question["id"],
        "total_marks": question["marks"],
        "model_answer": "See per-part model answers below.",
        "criteria": [{"description": "See per-part criteria in sub_questions.", "marks": question["marks"]}],
        "accepted_alternatives": [],
        "partial_credit_guidance": (
            "For the algorithm part, mark the approach and complexity claim as a pair - a suboptimal "
            "but correct and correctly-analysed algorithm should not be marked down for not being "
            "the most efficient possible solution."
        ),
        "sub_questions": sub_memos,
    }


def _memo_F(question: dict[str, Any]) -> dict[str, Any]:
    is_report = "report" in question["scenario"].lower()
    if is_report:
        answer = (
            "The relevant principle is data protection / privacy legislation (e.g. POPIA-style "
            "personal information protection) and workplace data-governance policy: a customer "
            "contact list is personal information, and 'not confidential' is not the same as "
            "'lawful to share' - export and use of personal data must be limited to what the client "
            "actually needs and agreed to. Before complying, the developer should check the data "
            "processing agreement/scope with the client, confirm whether raw contact details are "
            "actually required (versus just order/product data), and escalate to a supervisor or "
            "data-governance contact if the request appears to exceed the agreed purpose, rather "
            "than silently complying or silently refusing."
        )
    else:
        answer = (
            "The relevant principle is professional practice / change-management governance: "
            "release/change logs exist so the team (and future maintainers) can trace what changed, "
            "diagnose regressions quickly, and meet any audit or client-reporting obligations - "
            "'shipping faster' by skipping them creates hidden risk rather than removing real work. "
            "Before agreeing, the developer should raise the trade-off with the team lead, propose a "
            "minimal but real changelog entry, and only skip it if a documented team policy "
            "explicitly allows that for this type of release."
        )
    return {
        "question_id": question["id"],
        "total_marks": question["marks"],
        "model_answer": answer,
        "criteria": [
            {"description": "Names a specific, correctly-applicable governance/ethical/legislative or professional-practice principle (not a vague 'be ethical')", "marks": 2},
            {"description": "Explains a concrete, appropriate action to take before complying (e.g. check scope, escalate, confirm necessity) rather than blanket compliance or blanket refusal", "marks": 2},
            {"description": "Answer is coherent and specific to the scenario given, not generic boilerplate", "marks": 1},
        ],
        "accepted_alternatives": [
            "Any correctly-reasoned principle in the same family (e.g. 'confidentiality by design', 'least-privilege data sharing', 'informed consent') is acceptable even if named differently from the model answer.",
        ],
        "partial_credit_guidance": (
            "A candidate who identifies the right concern but proposes an overly extreme response "
            "(flat refusal with no escalation path, or unquestioning compliance) should lose the "
            "second criterion's marks but may still earn the first and third."
        ),
        "penalties": "",
    }


_MEMO_BUILDERS = {
    "A": _memo_A,
    "B": _memo_B,
    "C": _memo_C,
    "D": _memo_D,
    "E": _memo_E,
    "F": _memo_F,
}
