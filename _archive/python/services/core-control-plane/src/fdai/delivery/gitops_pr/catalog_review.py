"""Draft-only GitOps publication for immutable operational catalog reviews."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from fdai.core.operational_learning import (
    CatalogReviewPackage,
    CatalogReviewPublicationReceipt,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.remediation_pr import RemediationPr, RemediationPrPublisher


@dataclass(frozen=True, slots=True)
class CatalogReviewPrObservation:
    """Sanitized independent readback of one exact draft pull request."""

    observation_digest: str
    open: bool
    draft: bool
    head_matches: bool
    head_commit_matches: bool
    base_matches: bool
    labels_match: bool
    content_matches: bool
    files_match: bool
    observed_labels: tuple[str, ...]
    merged: bool
    auto_merge_enabled: bool


@runtime_checkable
class CatalogReviewPrPublisher(RemediationPrPublisher, Protocol):
    async def observe_catalog_review(
        self,
        *,
        pr_ref: str,
        idempotency_key: str,
        required_labels: tuple[str, ...],
        expected_head_sha: str,
        expected_path: str,
        expected_document_digest: str,
    ) -> CatalogReviewPrObservation: ...


class GitOpsCatalogReviewPublisher:
    """Publish one O3 package as an inert, shadow-labeled draft pull request.

    The pull request contains a content-addressed review package. It does not
    write active catalog paths, merge the pull request, or promote its Rule or
    ActionType. Human review must produce the ordinary catalog-as-code change.
    """

    def __init__(
        self,
        *,
        publisher: RemediationPrPublisher,
        binding_digest: str | None = None,
    ) -> None:
        self._publisher = publisher
        self._binding_digest = binding_digest

    async def publish(
        self,
        package: CatalogReviewPackage,
    ) -> CatalogReviewPublicationReceipt:
        rule_id = str(package.draft_rule.mapping["id"])
        action_type = package.candidate.action_type
        required_labels = tuple(
            sorted(
                (
                    "draft",
                    "shadow",
                    "governance",
                    "catalog-review",
                    f"rule:{rule_id}",
                    f"action:{action_type}",
                )
            )
        )
        if any(len(label) > 50 for label in required_labels):
            raise ValueError("catalog review exact labels exceed the GitHub label limit")
        review_document = _review_document(package)
        review_document_digest = hashlib.sha256(review_document.encode("utf-8")).hexdigest()
        review = RemediationPr(
            action_id=UUID(hex=package.content_digest[:32]),
            idempotency_key=f"catalog-review-{package.content_digest}",
            rule_ids=(rule_id,),
            title=f"Review operational rule candidate {rule_id}",
            body=_review_body(package, rule_id=rule_id),
            patch=review_document,
            patch_path=(f"rule-catalog/review-packages/operational-{package.content_digest}.json"),
            labels=required_labels,
            mode=Mode.SHADOW,
            metadata={
                "package_digest": package.content_digest,
                "review_document_digest": review_document_digest,
            },
        )
        receipt = await self._publisher.publish(review)
        if receipt.state != "open":
            raise ValueError("catalog review publication MUST remain an open draft")
        if receipt.head_sha is None:
            raise ValueError("catalog review publication returned no exact head commit")
        if not isinstance(self._publisher, CatalogReviewPrPublisher):
            raise RuntimeError("catalog review publisher lacks independent readback")
        observation = await self._publisher.observe_catalog_review(
            pr_ref=receipt.pr_ref,
            idempotency_key=review.idempotency_key,
            required_labels=review.labels,
            expected_head_sha=receipt.head_sha,
            expected_path=review.patch_path,
            expected_document_digest=review_document_digest,
        )
        if not (
            observation.open
            and observation.draft
            and observation.head_matches
            and observation.head_commit_matches
            and observation.base_matches
            and observation.labels_match
            and observation.content_matches
            and observation.files_match
            and not observation.merged
            and not observation.auto_merge_enabled
        ):
            raise ValueError("catalog review pull request readback is unsafe")
        return CatalogReviewPublicationReceipt(
            package_digest=package.content_digest,
            review_ref=receipt.pr_ref,
            already_existed=receipt.already_existed,
            candidate_digest=package.candidate.digest,
            binding_digest=self._binding_digest,
            observation_digest=observation.observation_digest,
            required_labels=required_labels,
            observed_labels=observation.observed_labels,
            head_sha=receipt.head_sha,
            review_document_digest=review_document_digest,
        )


def _review_document(package: CatalogReviewPackage) -> str:
    material = {
        "schema_version": "1.0.0",
        "kind": "operational-catalog-review",
        "package_digest": package.content_digest,
        "review_required": True,
        "catalog_version": package.catalog_version,
        "catalog_schema_version": package.schema_version,
        "candidate": package.candidate.to_mapping(),
        "draft_rule": package.draft_rule.mapping,
        "draft_action_type": (
            None if package.draft_action_type is None else package.draft_action_type.mapping
        ),
        "immutable_case_refs": list(package.immutable_case_refs),
        "checks": {
            "schema": asdict(package.schema),
            "replay": asdict(package.replay),
            "shadow": asdict(package.shadow),
            "policy": asdict(package.policy),
        },
        "grants_authority": False,
    }
    return json.dumps(material, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"


def _review_body(package: CatalogReviewPackage, *, rule_id: str) -> str:
    return "\n".join(
        (
            "This draft contains an inert operational catalog review package.",
            "",
            f"Rule candidate: `{rule_id}`",
            f"Package digest: `{package.content_digest}`",
            f"Immutable cases: `{len(package.immutable_case_refs)}`",
            "",
            "Merging this review package does not activate a Rule or ActionType. ",
            "Activation requires a separate reviewed catalog-as-code change.",
        )
    )


__all__ = [
    "CatalogReviewPrObservation",
    "CatalogReviewPrPublisher",
    "GitOpsCatalogReviewPublisher",
]
