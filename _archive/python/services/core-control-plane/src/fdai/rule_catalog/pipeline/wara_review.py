"""Deterministic review-only semantic diffs for pinned WARA generations."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.rule_catalog.schema.wara_assessment import WaraAssessmentCatalog, canonical_digest


@dataclass(frozen=True, slots=True)
class WaraSemanticDiff:
    additions: tuple[str, ...]
    updates: tuple[str, ...]
    disables: tuple[str, ...]
    reactivations: tuple[str, ...]

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "additions": list(self.additions),
            "updates": list(self.updates),
            "disables": list(self.disables),
            "reactivations": list(self.reactivations),
        }


@dataclass(frozen=True, slots=True)
class WaraReviewPackage:
    prior_revision: str
    proposed_revision: str
    prior_crosswalk_digest: str
    proposed_crosswalk_digest: str
    semantic_diff: WaraSemanticDiff
    requires_human_review: bool
    changes_active_authority: bool
    content_digest: str

    @classmethod
    def build(
        cls,
        prior: WaraAssessmentCatalog,
        proposed: WaraAssessmentCatalog,
        *,
        disabled_guids: tuple[str, ...] = (),
        reactivated_guids: tuple[str, ...] = (),
    ) -> WaraReviewPackage:
        prior_by_id = {item.aprl_guid: item for item in prior.recommendations}
        proposed_by_id = {item.aprl_guid: item for item in proposed.recommendations}
        additions = tuple(sorted(set(proposed_by_id) - set(prior_by_id)))
        inferred_disables = set(prior_by_id) - set(proposed_by_id)
        updates = tuple(
            sorted(
                guid
                for guid in set(prior_by_id) & set(proposed_by_id)
                if prior_by_id[guid].implementation_digest
                != proposed_by_id[guid].implementation_digest
            )
        )
        diff = WaraSemanticDiff(
            additions=additions,
            updates=updates,
            disables=tuple(sorted(inferred_disables | set(disabled_guids))),
            reactivations=tuple(sorted(set(reactivated_guids))),
        )
        digest_material = {
            "prior_revision": prior.source_revision,
            "proposed_revision": proposed.source_revision,
            "prior_crosswalk_digest": prior.crosswalk_digest,
            "proposed_crosswalk_digest": proposed.crosswalk_digest,
            "semantic_diff": diff.to_dict(),
            "requires_human_review": True,
            "changes_active_authority": False,
        }
        return cls(
            prior_revision=prior.source_revision,
            proposed_revision=proposed.source_revision,
            prior_crosswalk_digest=prior.crosswalk_digest,
            proposed_crosswalk_digest=proposed.crosswalk_digest,
            semantic_diff=diff,
            requires_human_review=True,
            changes_active_authority=False,
            content_digest=canonical_digest(digest_material),
        )


@dataclass(frozen=True, slots=True)
class WaraGenerationState:
    active: WaraAssessmentCatalog
    pending_review: WaraAssessmentCatalog | None = None
    pending_review_digest: str | None = None
    failed_revision: str | None = None
    failure_reason: str | None = None


def retain_last_valid_generation(
    current: WaraGenerationState,
    *,
    proposed: WaraAssessmentCatalog | None,
    review_package_digest: str | None = None,
    failed_revision: str | None = None,
    failure_reason: str | None,
) -> WaraGenerationState:
    """Select a fully validated proposal or preserve the current generation."""

    if proposed is None:
        if not failure_reason or not failed_revision:
            raise ValueError("failed WARA generation requires a revision and failure reason")
        return WaraGenerationState(
            active=current.active,
            pending_review=current.pending_review,
            pending_review_digest=current.pending_review_digest,
            failed_revision=failed_revision,
            failure_reason=failure_reason,
        )
    if failure_reason is not None or failed_revision is not None:
        raise ValueError("valid WARA proposal cannot carry failure details")
    if not review_package_digest:
        raise ValueError("valid WARA proposal requires a review package digest")
    return WaraGenerationState(
        active=current.active,
        pending_review=proposed,
        pending_review_digest=review_package_digest,
    )


def promote_reviewed_generation(
    current: WaraGenerationState,
    *,
    approved_package_digest: str,
) -> WaraGenerationState:
    """Activate only the exact proposal whose review package was approved."""

    if current.pending_review is None or current.pending_review_digest != approved_package_digest:
        raise ValueError("approved WARA review package does not match pending generation")
    return WaraGenerationState(active=current.pending_review)


__all__ = [
    "WaraGenerationState",
    "WaraReviewPackage",
    "WaraSemanticDiff",
    "promote_reviewed_generation",
    "retain_last_valid_generation",
]
