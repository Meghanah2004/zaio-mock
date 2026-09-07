"""JSON syntax + JSON Schema validation for papers and memos.

This is the first deterministic gate every generated (or hand-edited)
paper/memo must pass before any other validator runs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

from src.config import SCHEMAS_DIR
from src.validation.types import CheckResult


def _load_schema(name: str) -> dict[str, Any]:
    path = SCHEMAS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing schema: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def validate_against_schema(instance: dict[str, Any], schema_name: str) -> CheckResult:
    schema = _load_schema(schema_name)
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        details = "; ".join(f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors[:10])
        return CheckResult(name=f"schema:{schema_name}", passed=False, details=details)
    return CheckResult(name=f"schema:{schema_name}", passed=True, details="valid")


def validate_paper_schema(paper: dict[str, Any]) -> CheckResult:
    return validate_against_schema(paper, "paper.schema.json")


def validate_memo_schema(memo: dict[str, Any]) -> CheckResult:
    return validate_against_schema(memo, "memo.schema.json")


def load_json_file(path: Path) -> dict[str, Any]:
    """Load and parse a JSON file, raising a clear error on syntax failure."""
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
