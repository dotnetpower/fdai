"""Draft-only GitOps publication for verified rule-catalog collection runs.

Mirrors :mod:`fdai.delivery.gitops_pr.catalog_review`
(``GitOpsCatalogReviewPublisher``) for a different producer: a verified,
due source-watcher collection instead of an O3 operational-pattern
candidate. Both delegate to the same neutral
:class:`~fdai.shared.providers.remediation_pr.RemediationPrPublisher`
transport (concretely :class:`~fdai.delivery.gitops_pr.adapter.GitOpsPrAdapter`
against GitHub), so this module adds no new HTTP client code - it only
shapes the rule-catalog-collection review payload.
"""

from __future__ import annotations

import json
from uuid import UUID

from fdai.rule_catalog.pipeline.review import (
    CollectionReviewPackage,
    CollectionReviewPublicationReceipt,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.remediation_pr import RemediationPr, RemediationPrPublisher


class GitOpsCollectionReviewPublisher:
    """Publish one verified collection run as an inert, shadow-labeled draft PR.

    The pull request contains a content-addressed review package pointing at
    the durably mirrored snapshot; it never writes ``rule-catalog/catalog/``
    or ``rule-catalog/baselines/``, never merges, and never proposes a
    normalized Rule. A human still runs the existing parser and a separate
    reviewed catalog-as-code change to actually land new content.
    """

    def __init__(self, *, publisher: RemediationPrPublisher) -> None:
        self._publisher = publisher

    async def publish(self, package: CollectionReviewPackage) -> CollectionReviewPublicationReceipt:
        review = RemediationPr(
            action_id=UUID(hex=package.content_digest[:32]),
            idempotency_key=f"collection-review-{package.content_digest}",
            rule_ids=(),
            title=(f"Review collected source {package.source_id}@{package.resolved_revision[:12]}"),
            body=_review_body(package),
            patch=_review_document(package),
            patch_path=(f"rule-catalog/review-packages/collection-{package.content_digest}.json"),
            labels=("shadow", "governance", "collection-review"),
            mode=Mode.SHADOW,
            metadata={
                "package_digest": package.content_digest,
                "source_id": package.source_id,
            },
        )
        receipt = await self._publisher.publish(review)
        return CollectionReviewPublicationReceipt(
            package_digest=package.content_digest,
            review_ref=receipt.pr_ref,
            already_existed=receipt.already_existed,
        )


def _review_document(package: CollectionReviewPackage) -> str:
    material = {
        "schema_version": "1.0.0",
        "kind": "rule-catalog-collection-review",
        "package_digest": package.content_digest,
        "review_required": True,
        "source_id": package.source_id,
        "resolved_revision": package.resolved_revision,
        "content_sha256": package.content_sha256,
        "license": package.license,
        "redistribution": package.redistribution,
        "verified_rules": package.verified_rules,
        "verified_at": package.verified_at,
        "snapshot_files": [
            {
                "relative_path": file.relative_path,
                "storage_ref": file.storage_ref,
                "digest": file.digest,
            }
            for file in package.snapshot_files
        ],
        "grants_authority": False,
    }
    return json.dumps(material, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"


def _review_body(package: CollectionReviewPackage) -> str:
    return "\n".join(
        (
            "This draft contains an inert rule-catalog collection review package.",
            "",
            f"Source: `{package.source_id}` @ `{package.resolved_revision}`",
            f"Package digest: `{package.content_digest}`",
            f"Durably mirrored snapshot files: `{len(package.snapshot_files)}`",
            "",
            "Merging this review package does not land any Rule, ActionType, or ",
            "ConfigurationBaseline. Landing new catalog content still requires a ",
            "separate reviewed catalog-as-code change.",
        )
    )


__all__ = ["GitOpsCollectionReviewPublisher"]
