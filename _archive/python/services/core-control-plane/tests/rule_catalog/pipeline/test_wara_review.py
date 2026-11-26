from __future__ import annotations

from pathlib import Path

import pytest
from fdai.rule_catalog.pipeline.wara_review import (
    WaraGenerationState,
    WaraReviewPackage,
    promote_reviewed_generation,
    retain_last_valid_generation,
)
from fdai.rule_catalog.schema.wara_assessment import load_wara_assessment_catalog

ROOT = Path(__file__).resolve().parents[5]
CATALOG_ROOT = ROOT / "rule-catalog/collected/wara-aprl/assessment"


def _catalog():
    return load_wara_assessment_catalog(
        CATALOG_ROOT / "crosswalk.json",
        CATALOG_ROOT / "queries.json",
    )[0]


def test_review_package_is_deterministic_and_never_changes_authority() -> None:
    catalog = _catalog()

    first = WaraReviewPackage.build(catalog, catalog)
    second = WaraReviewPackage.build(catalog, catalog)

    assert first == second
    assert first.requires_human_review is True
    assert first.changes_active_authority is False
    assert first.semantic_diff.additions == ()
    assert first.semantic_diff.updates == ()


def test_review_package_classifies_updates_disables_and_reactivations() -> None:
    catalog = _catalog()
    first = catalog.recommendations[0]
    changed = first.model_copy(update={"implementation_digest": "sha256:" + "f" * 64})
    proposed = catalog.model_copy(
        update={
            "source_revision": "2" * 40,
            "crosswalk_digest": "sha256:" + "c" * 64,
            "recommendations": (changed, *catalog.recommendations[1:]),
        }
    )

    package = WaraReviewPackage.build(
        catalog,
        proposed,
        disabled_guids=("00000000-0000-0000-0000-000000000001",),
        reactivated_guids=("00000000-0000-0000-0000-000000000002",),
    )

    assert package.semantic_diff.updates == (first.aprl_guid,)
    assert package.semantic_diff.disables == ("00000000-0000-0000-0000-000000000001",)
    assert package.semantic_diff.reactivations == ("00000000-0000-0000-0000-000000000002",)
    assert package.changes_active_authority is False


def test_failed_generation_preserves_last_valid_snapshot() -> None:
    catalog = _catalog()
    current = WaraGenerationState(active=catalog)

    failed = retain_last_valid_generation(
        current,
        proposed=None,
        failed_revision="2" * 40,
        failure_reason="active_set_mismatch",
    )

    assert failed.active is catalog
    assert failed.failed_revision == "2" * 40
    assert failed.failure_reason == "active_set_mismatch"


def test_valid_generation_stays_pending_until_exact_review_is_approved() -> None:
    catalog = _catalog()
    proposed = catalog.model_copy(
        update={
            "source_revision": "2" * 40,
            "crosswalk_digest": "sha256:" + "c" * 64,
        }
    )
    package = WaraReviewPackage.build(catalog, proposed)
    staged = retain_last_valid_generation(
        WaraGenerationState(active=catalog),
        proposed=proposed,
        review_package_digest=package.content_digest,
        failure_reason=None,
    )

    assert staged.active is catalog
    assert staged.pending_review is proposed
    with pytest.raises(ValueError, match="does not match"):
        promote_reviewed_generation(
            staged,
            approved_package_digest="sha256:" + "d" * 64,
        )
    promoted = promote_reviewed_generation(
        staged,
        approved_package_digest=package.content_digest,
    )
    assert promoted.active is proposed
    assert promoted.pending_review is None
