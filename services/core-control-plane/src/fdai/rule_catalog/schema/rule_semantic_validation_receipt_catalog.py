"""Strict content-addressed catalog for passing semantic-surface validation evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from fdai.rule_catalog.schema.rule_semantic_retrieval import (
    CohortMetric,
    SurfaceValidationReceipt,
    ValidationDecision,
)

_SCHEMA_FILE = "rule_semantic_validation_receipt.schema.json"


@dataclass(frozen=True, slots=True)
class SemanticValidationReceiptCatalogIssue:
    key: str
    message: str


class SemanticValidationReceiptCatalogError(ValueError):
    """Aggregate validation-receipt artifact load failure."""

    def __init__(self, issues: list[SemanticValidationReceiptCatalogIssue]) -> None:
        self.issues = tuple(issues)
        preview = "; ".join(f"{item.key}: {item.message}" for item in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"semantic validation receipt catalog load failed: {preview}{suffix}")


def load_semantic_validation_receipts(
    root: Path,
) -> Mapping[str, SurfaceValidationReceipt]:
    """Load passing receipts whose filenames and bodies match their canonical digests."""

    if not root.is_dir():
        return {}
    validator = Draft202012Validator(_schema())
    issues: list[SemanticValidationReceiptCatalogIssue] = []
    loaded: dict[str, SurfaceValidationReceipt] = {}
    for path in sorted(root.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            issues.append(
                SemanticValidationReceiptCatalogIssue(
                    path.name,
                    "receipt artifact must be a regular file",
                )
            )
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            issues.append(SemanticValidationReceiptCatalogIssue(path.name, f"invalid JSON: {exc}"))
            continue
        if not isinstance(raw, Mapping):
            issues.append(SemanticValidationReceiptCatalogIssue(path.name, "not a JSON object"))
            continue
        schema_issues = sorted(validator.iter_errors(dict(raw)), key=lambda item: list(item.path))
        if schema_issues:
            issues.extend(
                SemanticValidationReceiptCatalogIssue(
                    f"{path.name}:{'/'.join(str(value) for value in item.path) or '<root>'}",
                    item.message,
                )
                for item in schema_issues
            )
            continue
        try:
            receipt = _receipt_from_mapping(raw)
        except (TypeError, ValueError) as exc:
            issues.append(SemanticValidationReceiptCatalogIssue(path.name, str(exc)))
            continue
        expected_name = f"{receipt.digest.removeprefix('sha256:')}.json"
        if path.name != expected_name:
            issues.append(
                SemanticValidationReceiptCatalogIssue(
                    path.name,
                    f"filename does not match receipt digest {receipt.digest!r}",
                )
            )
            continue
        loaded[receipt.digest] = receipt
    if issues:
        raise SemanticValidationReceiptCatalogError(issues)
    return loaded


def _receipt_from_mapping(raw: Mapping[str, Any]) -> SurfaceValidationReceipt:
    metrics = tuple(
        CohortMetric(
            cohort=str(item["cohort"]),
            metric=str(item["metric"]),
            value=float(item["value"]),
            sample_count=int(item["sample_count"]),
        )
        for item in raw["cohort_metrics"]
    )
    return SurfaceValidationReceipt(
        schema_version=str(raw["schema_version"]),
        surface_digest=str(raw["surface_digest"]),
        generation_digest=str(raw["generation_digest"]),
        catalog_digest=str(raw["catalog_digest"]),
        dataset_digest=str(raw["dataset_digest"]),
        evaluator_ref=str(raw["evaluator_ref"]),
        evaluation_policy_digest=str(raw["evaluation_policy_digest"]),
        training_query_digests=tuple(str(item) for item in raw["training_query_digests"]),
        evaluation_query_digests=tuple(str(item) for item in raw["evaluation_query_digests"]),
        cohort_metrics=metrics,
        failure_codes=tuple(str(item) for item in raw["failure_codes"]),
        decision=ValidationDecision(str(raw["decision"])),
        validation_authority=str(raw["validation_authority"]),
    )


def _schema() -> dict[str, Any]:
    raw = (
        resources.files("fdai.rule_catalog.schema")
        .joinpath(_SCHEMA_FILE)
        .read_text(encoding="utf-8")
    )
    return json.loads(raw)  # type: ignore[no-any-return]


__all__ = [
    "SemanticValidationReceiptCatalogError",
    "SemanticValidationReceiptCatalogIssue",
    "load_semantic_validation_receipts",
]
