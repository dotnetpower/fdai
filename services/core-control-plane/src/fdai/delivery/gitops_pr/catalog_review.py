"""Draft-only GitOps publication for immutable operational catalog reviews."""

from __future__ import annotations

import json
from dataclasses import asdict
from uuid import UUID

from fdai.core.operational_learning import (
    CatalogReviewPackage,
    CatalogReviewPublicationReceipt,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.remediation_pr import RemediationPr, RemediationPrPublisher


class GitOpsCatalogReviewPublisher:
    """Publish one O3 package as an inert, shadow-labeled draft pull request.

    The pull request contains a content-addressed review package. It does not
    write active catalog paths, merge the pull request, or promote its Rule or
    ActionType. Human review must produce the ordinary catalog-as-code change.
    """

    def __init__(self, *, publisher: RemediationPrPublisher) -> None:
        self._publisher = publisher

    async def publish(
        self,
        package: CatalogReviewPackage,
    ) -> CatalogReviewPublicationReceipt:
        rule_id = str(package.draft_rule.mapping["id"])
        review = RemediationPr(
            action_id=UUID(hex=package.content_digest[:32]),
            idempotency_key=f"catalog-review-{package.content_digest}",
            rule_ids=(rule_id,),
            title=f"Review operational rule candidate {rule_id}",
            body=_review_body(package, rule_id=rule_id),
            patch=_review_document(package),
            patch_path=(f"rule-catalog/review-packages/operational-{package.content_digest}.json"),
            labels=("shadow", "governance", "catalog-review"),
            mode=Mode.SHADOW,
            metadata={"package_digest": package.content_digest},
        )
        receipt = await self._publisher.publish(review)
        return CatalogReviewPublicationReceipt(
            package_digest=package.content_digest,
            review_ref=receipt.pr_ref,
            already_existed=receipt.already_existed,
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


__all__ = ["GitOpsCatalogReviewPublisher"]
