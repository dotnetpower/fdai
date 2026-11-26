"""Strict mapping loader for best-practice checklist artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from fdai.shared.contracts.models import (
    BestPractice,
    BestPracticeRequirement,
    Category,
    Provenance,
    RequirementKind,
    RequirementMode,
    Severity,
)

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_SCHEMA_FILE = "best_practice.schema.json"


@dataclass(frozen=True, slots=True)
class BestPracticeLoadIssue:
    key: str
    message: str


class BestPracticeLoadError(ValueError):
    """Aggregate validation error at the best-practice load boundary."""

    def __init__(self, issues: list[BestPracticeLoadIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{issue.key}: {issue.message}" for issue in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"best-practice validation failed: {preview}{suffix}")


def _validator() -> Draft202012Validator:
    schema = json.loads(
        resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
    )
    return Draft202012Validator(schema, format_checker=FormatChecker())


_VALIDATOR = _validator()


def load_best_practice_from_mapping(raw: Mapping[str, Any]) -> BestPractice:
    """Validate and materialize one best-practice checklist artifact."""

    issues = [
        BestPracticeLoadIssue(
            key="/".join(str(part) for part in error.path) or "<root>",
            message=error.message,
        )
        for error in sorted(_VALIDATOR.iter_errors(raw), key=lambda item: list(item.path))
    ]
    if issues:
        raise BestPracticeLoadError(issues)
    try:
        provenance = Provenance.model_validate(raw["provenance"])
        return BestPractice(
            id=str(raw["id"]),
            version=str(raw["version"]),
            framework=str(raw["framework"]),
            control_id=str(raw["control_id"]),
            title=str(raw["title"]),
            rationale=str(raw["rationale"]),
            severity=Severity(str(raw["severity"])),
            category=Category(str(raw["category"])),
            requirement_mode=RequirementMode(str(raw.get("requirement_mode", "all"))),
            requirements=tuple(
                BestPracticeRequirement(
                    kind=RequirementKind(str(requirement["kind"])),
                    ref=str(requirement["ref"]),
                    freshness_days=requirement.get("freshness_days"),
                )
                for requirement in raw["requirements"]
            ),
            provenance=provenance,
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise BestPracticeLoadError(
            [BestPracticeLoadIssue(key="<domain>", message=str(exc))]
        ) from exc


__all__ = [
    "BestPracticeLoadError",
    "BestPracticeLoadIssue",
    "load_best_practice_from_mapping",
]
