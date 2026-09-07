"""Builds the machine-readable assessment blueprint.

blueprint = compact reference analysis (artifacts/reference-analysis.json)
            + qualification config (configs/<qualification>.json)

The blueprint is the ONLY thing question/memo generation reads for
assessment structure - neither stage re-reads the raw reference PDFs or the
full reference-analysis document. This is the token-efficiency boundary
described in docs/DESIGN.md.

Every number in the blueprint originates from `configs/<qualification>.json`
and is explicitly flagged there as an implementation assumption; every
outcome/competency string originates from the reference analysis's KT data,
which *is* grounded in the supplied source material.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BlueprintSection:
    id: str
    title: str
    marks: int
    outcomes: list[str]
    """Full thematic outcome list for the section's km_refs - documents scope,
    is NOT itself a per-question coverage requirement (see required_outcomes)."""
    competencies: list[str]
    """Titles parallel to `outcomes`, same order - one title per outcome code."""
    required_outcomes: list[str]
    """Hand-curated subset of `outcomes` that a generated question MUST
    demonstrably cover. This is what src/validation/coverage_validator.py
    checks paper questions against - never the full `outcomes` list."""
    difficulty: str
    question_types: list[str]
    occupational_context: str
    questions_planned: int


@dataclass
class Blueprint:
    paper_id: str
    qualification: str
    qualification_title: str
    nqf_level: list[int]
    duration_minutes: int
    total_marks: int
    pass_mark_percent: int
    status_disclaimer: str
    instructions: list[str]
    sections: list[BlueprintSection] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    novelty_thresholds: dict[str, float] = field(default_factory=lambda: {"warn": 0.35, "flag": 0.55})

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


STATUS_DISCLAIMER = (
    "MOCK / PRACTICE ASSESSMENT ONLY. This paper is generated for formative "
    "self-assessment and exam-preparation purposes. It is NOT an official "
    "QCTO External Integrated Summative Assessment (EISA), is not moderated "
    "by MICT SETA, and confers no qualification status or credit."
)

_OCCUPATIONAL_CONTEXT_BY_KM = {
    "KM-04": "Junior developer performing estimation and calculation tasks before coding a feature.",
    "KM-05": "Junior developer writing and reasoning about small procedural programs.",
    "KM-06": "Front-end developer building and styling an interactive web feature for a client site.",
    "KM-07": "Developer documenting a system design for a team using UML before implementation.",
    "KM-08": "Developer designing, querying and maintaining a relational database for an application.",
    "KM-09": "Developer working through the SDLC and applying secure-coding practice on a real feature.",
    "KM-10": "Developer operating within workplace governance, legislative and ethical constraints.",
    "KM-11": "Developer collaborating and communicating within a modern, 4IR-influenced workplace.",
    "KM-12": "Developer applying design-thinking to scope a user-centred solution.",
}


def _outcomes_and_competencies_for(km_refs: list[str], modules_by_km: dict[str, Any]) -> tuple[list[str], list[str]]:
    outcomes: list[str] = []
    competencies: list[str] = []
    for km in km_refs:
        mod = modules_by_km.get(km)
        if not mod:
            continue
        for topic in mod["knowledge_topics"]:
            outcomes.append(topic["code"])
            competencies.append(topic["title"])
    return outcomes, competencies


def build_blueprint(reference_analysis: dict[str, Any], qual_config: dict[str, Any], paper_number: int) -> Blueprint:
    modules_by_km = {f"KM-{m['km']}": m for m in reference_analysis["modules"]}

    sections: list[BlueprintSection] = []
    for sec_cfg in qual_config["sections"]:
        outcomes, competencies = _outcomes_and_competencies_for(sec_cfg["km_refs"], modules_by_km)

        required_outcomes = sec_cfg.get("required_outcomes", list(outcomes))
        unknown_required = set(required_outcomes) - set(outcomes)
        if unknown_required:
            raise ValueError(
                f"configs/{qual_config['qualification_key']}.json section '{sec_cfg['id']}' declares "
                f"required_outcomes not present among its km_refs' knowledge topics: "
                f"{sorted(unknown_required)}. Fix the config before generating."
            )

        primary_km = sec_cfg["km_refs"][0]
        occupational_context = sec_cfg.get("occupational_context") or _OCCUPATIONAL_CONTEXT_BY_KM.get(
            primary_km, "General software development workplace context."
        )

        sections.append(
            BlueprintSection(
                id=sec_cfg["id"],
                title=sec_cfg["title"],
                marks=sec_cfg["marks"],
                outcomes=outcomes,
                competencies=competencies,
                required_outcomes=required_outcomes,
                difficulty=sec_cfg["difficulty"],
                question_types=sec_cfg["question_types"],
                occupational_context=occupational_context,
                questions_planned=qual_config.get("questions_per_section", 1),
            )
        )

    total_marks_check = sum(s.marks for s in sections)
    if total_marks_check != qual_config["total_marks"]:
        raise ValueError(
            f"configs/{qual_config['qualification_key']}.json is inconsistent: "
            f"section marks sum to {total_marks_check} but total_marks is "
            f"{qual_config['total_marks']}. Fix the config before generating."
        )
    assumptions = [
        qual_config.get("_assumption_notice", ""),
        (
            "Section mark allocation is informed by (not strictly proportional to) each module's "
            "QCTO credit weighting; low-credit but conceptually essential modules (KM-05 "
            "Programming Basics, KM-09 SDLC/Security) retain a mark floor rather than being "
            "scaled down to their small credit share."
        ),
        (
            f"Computed section marks sum to {total_marks_check}; configured total_marks is "
            f"{qual_config['total_marks']}."
        ),
        (
            "Each section's `required_outcomes` is a hand-curated subset of its full thematic "
            "`outcomes` list, chosen to match what a single blueprint-compliant question can "
            "genuinely and specifically assess. The broader `outcomes` list documents thematic "
            "scope only and is not itself a per-question coverage requirement - "
            "src/validation/coverage_validator.py checks generated questions against "
            "`required_outcomes`, not `outcomes`."
        ),
    ]

    novelty_cfg = qual_config.get("novelty", {})
    novelty_thresholds = {
        "warn": novelty_cfg.get("similarity_warn_threshold", 0.35),
        "flag": novelty_cfg.get("similarity_flag_threshold", 0.55),
    }

    return Blueprint(
        paper_id=f"mock-eisa-{qual_config['qualification_key']}-paper-{paper_number:02d}",
        qualification=qual_config["qualification_key"],
        qualification_title=reference_analysis["qualification_title"],
        nqf_level=reference_analysis["nqf_levels_present"],
        duration_minutes=qual_config["duration_minutes"],
        total_marks=qual_config["total_marks"],
        pass_mark_percent=qual_config["pass_mark_percent"],
        status_disclaimer=STATUS_DISCLAIMER,
        instructions=qual_config["candidate_instructions"],
        sections=sections,
        assumptions=[a for a in assumptions if a],
        novelty_thresholds=novelty_thresholds,
    )


def write_blueprint(blueprint: Blueprint, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blueprint.to_json_dict(), indent=2), encoding="utf-8")
