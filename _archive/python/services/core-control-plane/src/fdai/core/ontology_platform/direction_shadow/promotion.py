"""Review-gated direction-mapping promotion proposals without migration authority."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from .identity import content_digest
from .models import ComparisonDisposition, DirectionShadowReceipt, RebuildPointer


class DirectionPromotionDecision(StrEnum):
    """Human review result for one complete direction comparison."""

    APPROVE_PROPOSAL = "approve_proposal"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class DirectionPromotionAssessment:
    """Content-addressed catalog-PR proposal with no graph or migration authority."""

    comparison_receipt_digest: str
    prior_generation_digest: str
    aligned_generation_digest: str
    regression_receipt_digests: tuple[str, ...]
    requested_by: str
    reviewed_by: str
    reviewed_at: datetime
    decision: DirectionPromotionDecision
    proposal_ready: bool
    reason_codes: tuple[str, ...]
    rebuild_pointer: RebuildPointer
    catalog_pr_required: Literal[True] = True
    graph_mutation_authority: Literal[False] = False
    migration_execution_authority: Literal[False] = False
    assessment_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            self.catalog_pr_required is not True
            or self.graph_mutation_authority is not False
            or self.migration_execution_authority is not False
        ):
            raise ValueError("direction promotion assessment cannot grant mutation authority")
        for name, value in (
            ("comparison_receipt_digest", self.comparison_receipt_digest),
            ("prior_generation_digest", self.prior_generation_digest),
            ("aligned_generation_digest", self.aligned_generation_digest),
            *(("regression_receipt_digest", digest) for digest in self.regression_receipt_digests),
        ):
            _require_digest(name, value)
        if not self.regression_receipt_digests or self.regression_receipt_digests != tuple(
            sorted(set(self.regression_receipt_digests))
        ):
            raise ValueError("regression receipts MUST be a non-empty unique sorted set")
        for name, value in (("requested_by", self.requested_by), ("reviewed_by", self.reviewed_by)):
            if not value.strip() or value != value.strip() or len(value) > 256:
                raise ValueError(f"{name} MUST be a bounded non-empty principal")
        if self.requested_by == self.reviewed_by:
            raise ValueError("direction promotion reviewer MUST differ from requester")
        if self.reviewed_at.tzinfo is None:
            raise ValueError("direction promotion review time MUST be timezone-aware")
        object.__setattr__(self, "reviewed_at", self.reviewed_at.astimezone(UTC))
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ValueError("direction promotion reason codes MUST be unique and sorted")
        if self.proposal_ready != (
            self.decision is DirectionPromotionDecision.APPROVE_PROPOSAL and not self.reason_codes
        ):
            raise ValueError("direction promotion readiness does not match its review")
        object.__setattr__(
            self,
            "assessment_digest",
            content_digest(self.to_mapping(include_digest=False)),
        )

    def to_mapping(self, *, include_digest: bool = True) -> dict[str, object]:
        """Return the replay-stable review record."""

        value: dict[str, object] = {
            "aligned_generation_digest": self.aligned_generation_digest,
            "catalog_pr_required": self.catalog_pr_required,
            "comparison_receipt_digest": self.comparison_receipt_digest,
            "decision": self.decision.value,
            "graph_mutation_authority": self.graph_mutation_authority,
            "migration_execution_authority": self.migration_execution_authority,
            "prior_generation_digest": self.prior_generation_digest,
            "proposal_ready": self.proposal_ready,
            "reason_codes": list(self.reason_codes),
            "rebuild_pointer": {
                "authoritative_generation_ref": (self.rebuild_pointer.authoritative_generation_ref),
                "mutation_authority": self.rebuild_pointer.mutation_authority,
                "rebuild_procedure_ref": self.rebuild_pointer.rebuild_procedure_ref,
                "restores_deleted_rows": self.rebuild_pointer.restores_deleted_rows,
                "strategy": self.rebuild_pointer.strategy,
            },
            "regression_receipt_digests": list(self.regression_receipt_digests),
            "requested_by": self.requested_by,
            "reviewed_at": self.reviewed_at.isoformat(),
            "reviewed_by": self.reviewed_by,
        }
        if include_digest:
            value["assessment_digest"] = self.assessment_digest
        return value


def assess_direction_mapping_promotion(
    receipt: DirectionShadowReceipt,
    *,
    regression_receipt_digests: tuple[str, ...],
    requested_by: str,
    reviewed_by: str,
    reviewed_at: datetime,
    decision: DirectionPromotionDecision,
) -> DirectionPromotionAssessment:
    """Create a review-bound PR proposal while withholding every migration authority.

    A comparison that did not pin provider-schema release identity on both
    sides (``receipt.exact_release_mode`` is ``False``) can never become
    ``proposal_ready``, even when its disposition is otherwise complete and
    the reviewer approves: a non-exact comparison cannot prove the aligned
    generation matches the same release the legacy generation was pinned to.
    """

    reasons: set[str] = set()
    if receipt.disposition is not ComparisonDisposition.COMPLETE:
        reasons.add("comparison_requires_review")
    if not receipt.exact_release_mode:
        reasons.add("exact_release_mode_required")
    if decision is DirectionPromotionDecision.REJECT:
        reasons.add("reviewer_rejected")
    if len(regression_receipt_digests) != len(set(regression_receipt_digests)):
        raise ValueError("regression receipts MUST be unique")
    canonical_regressions = tuple(sorted(regression_receipt_digests))
    return DirectionPromotionAssessment(
        comparison_receipt_digest=receipt.receipt_digest,
        prior_generation_digest=receipt.legacy_generation_digest,
        aligned_generation_digest=receipt.aligned_generation_digest,
        regression_receipt_digests=canonical_regressions,
        requested_by=requested_by,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        decision=decision,
        proposal_ready=not reasons,
        reason_codes=tuple(sorted(reasons)),
        rebuild_pointer=receipt.rebuild_pointer,
    )


def _require_digest(name: str, value: str) -> None:
    if (
        len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{name} MUST be a canonical SHA-256 digest")


__all__ = [
    "DirectionPromotionAssessment",
    "DirectionPromotionDecision",
    "assess_direction_mapping_promotion",
]
