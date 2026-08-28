"""Review-gated direction mapping promotion proposal tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fdai.core.ontology_platform.direction_shadow import (
    ComparisonDisposition,
    DirectionGraphGeneration,
    DirectionPromotionDecision,
    DirectionShadowReceipt,
    RebuildPointer,
    assess_direction_mapping_promotion,
    compare_graph_generations,
)

_PRIOR_RELEASE = "sha256:" + ("a" * 64)
_ALIGNED_RELEASE = "sha256:" + ("b" * 64)
_REGRESSION = "sha256:" + ("c" * 64)
_PROVIDER_SCHEMA = "sha256:" + ("d" * 64)
_MAPPING_REVISION = "mapping-rev-1"
_NOW = datetime(2026, 8, 27, tzinfo=UTC)


def _receipt(*, complete: bool = True, exact_release_mode: bool = True) -> DirectionShadowReceipt:
    provider_schema_digest = _PROVIDER_SCHEMA if exact_release_mode else None
    mapping_revision = _MAPPING_REVISION if exact_release_mode else None
    legacy = DirectionGraphGeneration.create(
        generation_ref="legacy",
        ontology_release_digest=_PRIOR_RELEASE,
        object_ids=("resource-a",),
        links=(),
        complete=complete,
        provider_schema_digest=provider_schema_digest,
        mapping_revision=mapping_revision,
    )
    aligned = DirectionGraphGeneration.create(
        generation_ref="aligned",
        ontology_release_digest=_ALIGNED_RELEASE,
        object_ids=("resource-a",),
        links=(),
        complete=True,
        provider_schema_digest=provider_schema_digest,
        mapping_revision=mapping_revision,
    )
    return compare_graph_generations(
        legacy,
        aligned,
        migration_revision="migration-1",
        rebuild_pointer=RebuildPointer(
            authoritative_generation_ref="inventory-generation:aligned",
            rebuild_procedure_ref="runbook:ontology-current-state-rebuild:v1",
        ),
        require_exact_releases=exact_release_mode,
    )


def test_complete_comparison_and_regression_receipt_create_only_a_pr_proposal() -> None:
    result = assess_direction_mapping_promotion(
        _receipt(),
        regression_receipt_digests=(_REGRESSION,),
        requested_by="requester",
        reviewed_by="reviewer",
        reviewed_at=_NOW,
        decision=DirectionPromotionDecision.APPROVE_PROPOSAL,
    )

    assert result.proposal_ready is True
    assert result.reason_codes == ()
    assert result.catalog_pr_required is True
    assert result.graph_mutation_authority is False
    assert result.migration_execution_authority is False
    assert result.assessment_digest.startswith("sha256:")


def test_incomplete_comparison_cannot_be_approved() -> None:
    receipt = _receipt(complete=False)
    assert receipt.disposition is ComparisonDisposition.REVIEW_REQUIRED

    result = assess_direction_mapping_promotion(
        receipt,
        regression_receipt_digests=(_REGRESSION,),
        requested_by="requester",
        reviewed_by="reviewer",
        reviewed_at=_NOW,
        decision=DirectionPromotionDecision.APPROVE_PROPOSAL,
    )

    assert result.proposal_ready is False
    assert result.reason_codes == ("comparison_requires_review",)


def test_non_exact_comparison_cannot_become_proposal_ready() -> None:
    receipt = _receipt(exact_release_mode=False)
    assert receipt.disposition is ComparisonDisposition.COMPLETE

    result = assess_direction_mapping_promotion(
        receipt,
        regression_receipt_digests=(_REGRESSION,),
        requested_by="requester",
        reviewed_by="reviewer",
        reviewed_at=_NOW,
        decision=DirectionPromotionDecision.APPROVE_PROPOSAL,
    )

    assert result.proposal_ready is False
    assert result.reason_codes == ("exact_release_mode_required",)


def test_reviewer_rejection_preserves_the_rollback_pointer() -> None:
    result = assess_direction_mapping_promotion(
        _receipt(),
        regression_receipt_digests=(_REGRESSION,),
        requested_by="requester",
        reviewed_by="reviewer",
        reviewed_at=_NOW,
        decision=DirectionPromotionDecision.REJECT,
    )

    assert result.proposal_ready is False
    assert result.reason_codes == ("reviewer_rejected",)
    assert result.rebuild_pointer.authoritative_generation_ref == ("inventory-generation:aligned")


def test_self_review_is_rejected() -> None:
    with pytest.raises(ValueError, match="differ"):
        assess_direction_mapping_promotion(
            _receipt(),
            regression_receipt_digests=(_REGRESSION,),
            requested_by="same",
            reviewed_by="same",
            reviewed_at=_NOW,
            decision=DirectionPromotionDecision.APPROVE_PROPOSAL,
        )


def test_regression_evidence_is_required_and_canonical() -> None:
    with pytest.raises(ValueError, match="regression receipts"):
        assess_direction_mapping_promotion(
            _receipt(),
            regression_receipt_digests=(),
            requested_by="requester",
            reviewed_by="reviewer",
            reviewed_at=_NOW,
            decision=DirectionPromotionDecision.APPROVE_PROPOSAL,
        )


def test_duplicate_regression_receipts_are_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        assess_direction_mapping_promotion(
            _receipt(),
            regression_receipt_digests=(_REGRESSION, _REGRESSION),
            requested_by="requester",
            reviewed_by="reviewer",
            reviewed_at=_NOW,
            decision=DirectionPromotionDecision.APPROVE_PROPOSAL,
        )


def test_equivalent_review_times_have_one_replay_identity() -> None:
    first = assess_direction_mapping_promotion(
        _receipt(),
        regression_receipt_digests=(_REGRESSION,),
        requested_by="requester",
        reviewed_by="reviewer",
        reviewed_at=_NOW,
        decision=DirectionPromotionDecision.APPROVE_PROPOSAL,
    )
    second = assess_direction_mapping_promotion(
        _receipt(),
        regression_receipt_digests=(_REGRESSION,),
        requested_by="requester",
        reviewed_by="reviewer",
        reviewed_at=_NOW.astimezone(timezone(timedelta(hours=9))),
        decision=DirectionPromotionDecision.APPROVE_PROPOSAL,
    )

    assert first.assessment_digest == second.assessment_digest


def test_authority_literal_fields_fail_closed_at_runtime() -> None:
    pointer = RebuildPointer(
        authoritative_generation_ref="inventory-generation:aligned",
        rebuild_procedure_ref="runbook:ontology-current-state-rebuild:v1",
    )
    with pytest.raises(ValueError, match="mutation authority"):
        replace(pointer, mutation_authority=True)

    with pytest.raises(ValueError, match="mutation authority"):
        replace(_receipt(), graph_mutation_authority=True)

    assessment = assess_direction_mapping_promotion(
        _receipt(),
        regression_receipt_digests=(_REGRESSION,),
        requested_by="requester",
        reviewed_by="reviewer",
        reviewed_at=_NOW,
        decision=DirectionPromotionDecision.APPROVE_PROPOSAL,
    )
    with pytest.raises(ValueError, match="mutation authority"):
        replace(assessment, migration_execution_authority=True)
