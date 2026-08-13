"""Schema-validated loader for governed semantic retrieval thresholds."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from fdai.rule_catalog.schema.rule_semantic_evaluation import RetrievalEvaluationPolicy

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_SCHEMA_FILE = "rule_semantic_evaluation_policy.schema.json"


@dataclass(frozen=True, slots=True)
class EvaluationPolicyLoadIssue:
    key: str
    message: str


class EvaluationPolicyLoadError(ValueError):
    """Aggregate error surfaced at the governed evaluation-policy boundary."""

    def __init__(self, issues: list[EvaluationPolicyLoadIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{item.key}: {item.message}" for item in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        message = f"semantic retrieval evaluation policy validation failed: {preview}{suffix}"
        super().__init__(message)


def _load_schema() -> dict[str, Any]:
    raw = resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
    return json.loads(raw)  # type: ignore[no-any-return]


_VALIDATOR = Draft202012Validator(_load_schema())


def load_retrieval_evaluation_policy_from_mapping(
    raw: Mapping[str, Any],
) -> RetrievalEvaluationPolicy:
    """Validate one mapping and return its content-addressed policy contract."""

    issues = [
        EvaluationPolicyLoadIssue(
            key="/".join(str(part) for part in error.path) or "<root>",
            message=error.message,
        )
        for error in sorted(_VALIDATOR.iter_errors(raw), key=lambda item: list(item.path))
    ]
    if issues:
        raise EvaluationPolicyLoadError(issues)
    try:
        return RetrievalEvaluationPolicy(
            schema_version=raw["schema_version"],
            top_k=raw["top_k"],
            min_recall_at_k=raw["min_recall_at_k"],
            min_mean_reciprocal_rank=raw["min_mean_reciprocal_rank"],
            min_no_match_precision=raw["min_no_match_precision"],
            required_cohorts=tuple(raw["required_cohorts"]),
        )
    except (TypeError, ValueError) as exc:
        raise EvaluationPolicyLoadError(
            [EvaluationPolicyLoadIssue(key="<domain>", message=str(exc))]
        ) from exc


def load_retrieval_evaluation_policy_from_json(raw: str) -> RetrievalEvaluationPolicy:
    """Parse JSON and fail closed on malformed or non-object configuration."""

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EvaluationPolicyLoadError(
            [EvaluationPolicyLoadIssue(key="<json>", message=exc.msg)]
        ) from exc
    if not isinstance(decoded, dict):
        raise EvaluationPolicyLoadError(
            [EvaluationPolicyLoadIssue(key="<root>", message="configuration MUST be an object")]
        )
    return load_retrieval_evaluation_policy_from_mapping(decoded)


__all__ = [
    "EvaluationPolicyLoadError",
    "EvaluationPolicyLoadIssue",
    "load_retrieval_evaluation_policy_from_json",
    "load_retrieval_evaluation_policy_from_mapping",
]
