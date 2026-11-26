"""Review-only semantic diffs for WAF and CAF assessment generations."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.rule_catalog.schema.framework_assessment import (
    FrameworkAssessmentCatalog,
    canonical_digest,
)


@dataclass(frozen=True, slots=True)
class FrameworkSemanticDiff:
    additions: tuple[str, ...]
    removals: tuple[str, ...]
    updates: tuple[str, ...]

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "additions": list(self.additions),
            "removals": list(self.removals),
            "updates": list(self.updates),
        }


@dataclass(frozen=True, slots=True)
class FrameworkReviewPackage:
    framework_id: str
    prior_version: str
    proposed_version: str
    prior_catalog_digest: str
    proposed_catalog_digest: str
    semantic_diff: FrameworkSemanticDiff
    requires_human_review: bool
    changes_active_authority: bool
    content_digest: str

    @classmethod
    def build(
        cls,
        prior: FrameworkAssessmentCatalog,
        proposed: FrameworkAssessmentCatalog,
    ) -> FrameworkReviewPackage:
        if prior.framework_id != proposed.framework_id:
            raise ValueError("framework review cannot compare different frameworks")
        prior_by_id = {item.control_id: item for item in prior.controls}
        proposed_by_id = {item.control_id: item for item in proposed.controls}
        diff = FrameworkSemanticDiff(
            additions=tuple(sorted(set(proposed_by_id) - set(prior_by_id))),
            removals=tuple(sorted(set(prior_by_id) - set(proposed_by_id))),
            updates=tuple(
                sorted(
                    control_id
                    for control_id in set(prior_by_id) & set(proposed_by_id)
                    if prior_by_id[control_id].specification_digest
                    != proposed_by_id[control_id].specification_digest
                )
            ),
        )
        material = {
            "framework_id": prior.framework_id,
            "prior_version": prior.framework_version,
            "proposed_version": proposed.framework_version,
            "prior_catalog_digest": prior.catalog_digest,
            "proposed_catalog_digest": proposed.catalog_digest,
            "semantic_diff": diff.to_dict(),
            "requires_human_review": True,
            "changes_active_authority": False,
        }
        return cls(
            framework_id=prior.framework_id,
            prior_version=prior.framework_version,
            proposed_version=proposed.framework_version,
            prior_catalog_digest=prior.catalog_digest,
            proposed_catalog_digest=proposed.catalog_digest,
            semantic_diff=diff,
            requires_human_review=True,
            changes_active_authority=False,
            content_digest=canonical_digest(material),
        )


@dataclass(frozen=True, slots=True)
class FrameworkGenerationState:
    active: FrameworkAssessmentCatalog
    pending_review: FrameworkAssessmentCatalog | None = None
    pending_review_digest: str | None = None
    failed_version: str | None = None
    failure_reason: str | None = None


def retain_last_valid_framework_generation(
    current: FrameworkGenerationState,
    *,
    proposed: FrameworkAssessmentCatalog | None,
    review_package_digest: str | None = None,
    failed_version: str | None = None,
    failure_reason: str | None,
) -> FrameworkGenerationState:
    """Keep the active generation until one exact valid proposal is reviewed."""

    if proposed is None:
        if not failed_version or not failure_reason:
            raise ValueError("failed framework generation requires version and reason")
        return FrameworkGenerationState(
            active=current.active,
            pending_review=current.pending_review,
            pending_review_digest=current.pending_review_digest,
            failed_version=failed_version,
            failure_reason=failure_reason,
        )
    if (
        proposed.framework_id != current.active.framework_id
        or failed_version is not None
        or failure_reason is not None
        or not review_package_digest
    ):
        raise ValueError("valid framework proposal requires matching identity and review digest")
    return FrameworkGenerationState(
        active=current.active,
        pending_review=proposed,
        pending_review_digest=review_package_digest,
    )


def promote_reviewed_framework_generation(
    current: FrameworkGenerationState,
    *,
    approved_package_digest: str,
) -> FrameworkGenerationState:
    """Activate only the proposal bound to the independently approved package."""

    if current.pending_review is None or current.pending_review_digest != approved_package_digest:
        raise ValueError("approved framework package does not match the pending generation")
    return FrameworkGenerationState(active=current.pending_review)


__all__ = [
    "FrameworkGenerationState",
    "FrameworkReviewPackage",
    "FrameworkSemanticDiff",
    "promote_reviewed_framework_generation",
    "retain_last_valid_framework_generation",
]
