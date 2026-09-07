"""Shared result types for every validator, so the CLI/report can render a
single uniform structure regardless of which check produced it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CheckResult:
    name: str
    passed: bool
    details: str = ""


@dataclass
class ValidationReport:
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.checks.append(result)
        if not result.passed:
            self.passed = False

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def empty(cls) -> ValidationReport:
        return cls(passed=True, checks=[])
