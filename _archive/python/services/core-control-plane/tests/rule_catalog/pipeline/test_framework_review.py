"""Review-only update tests for WAF and CAF assessment generations."""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai.rule_catalog.pipeline.framework_review import (
    FrameworkGenerationState,
    FrameworkReviewPackage,
    promote_reviewed_framework_generation,
    retain_last_valid_framework_generation,
)
from fdai.rule_catalog.schema.framework_assessment import (
    load_framework_assessment_catalog,
)

ROOT = Path(__file__).resolve().parents[5]
GENERATED = ROOT / "rule-catalog/framework-assessments/generated"


def _catalog(name: str):
    return load_framework_assessment_catalog(GENERATED / f"{name}.json")


def test_framework_review_package_is_deterministic_and_no_authority() -> None:
    catalog = _catalog("azure-waf")

    first = FrameworkReviewPackage.build(catalog, catalog)
    second = FrameworkReviewPackage.build(catalog, catalog)

    assert first == second
    assert first.semantic_diff.additions == ()
    assert first.semantic_diff.removals == ()
    assert first.semantic_diff.updates == ()
    assert first.requires_human_review is True
    assert first.changes_active_authority is False


def test_failed_framework_generation_preserves_active_catalog() -> None:
    catalog = _catalog("azure-caf")
    current = FrameworkGenerationState(active=catalog)

    failed = retain_last_valid_framework_generation(
        current,
        proposed=None,
        failed_version="2026-09-11",
        failure_reason="evidence_specification_incomplete",
    )

    assert failed.active is catalog
    assert failed.failed_version == "2026-09-11"


def test_framework_generation_requires_exact_review_digest() -> None:
    catalog = _catalog("azure-caf")
    package = FrameworkReviewPackage.build(catalog, catalog)
    staged = retain_last_valid_framework_generation(
        FrameworkGenerationState(active=catalog),
        proposed=catalog,
        review_package_digest=package.content_digest,
        failure_reason=None,
    )

    with pytest.raises(ValueError, match="does not match"):
        promote_reviewed_framework_generation(
            staged,
            approved_package_digest="sha256:" + "f" * 64,
        )
    promoted = promote_reviewed_framework_generation(
        staged,
        approved_package_digest=package.content_digest,
    )

    assert promoted.active is catalog
    assert promoted.pending_review is None


def test_framework_review_rejects_cross_framework_comparison() -> None:
    with pytest.raises(ValueError, match="different frameworks"):
        FrameworkReviewPackage.build(_catalog("azure-waf"), _catalog("azure-caf"))
