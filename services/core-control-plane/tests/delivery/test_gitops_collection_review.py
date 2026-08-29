"""Draft-only GitOps collection-review publication tests."""

from __future__ import annotations

import json

from fdai.delivery.gitops_pr.collection_review import GitOpsCollectionReviewPublisher
from fdai.rule_catalog.pipeline.review import CollectionReviewPackage, MirroredSnapshotFile
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.remediation_pr import PublishReceipt, RemediationPr


def _package() -> CollectionReviewPackage:
    return CollectionReviewPackage.build(
        source_id="example-source",
        resolved_revision="0" * 40,
        content_sha256="1" * 64,
        license="Apache-2.0",
        redistribution="embeddable",
        verified_rules=3,
        verified_at="2026-07-06T00:00:00+00:00",
        snapshot_files=(
            MirroredSnapshotFile(
                relative_path="a.yaml",
                storage_ref=f"rule-catalog-snapshots/example-source/{'0' * 40}/a.yaml",
                digest="2" * 64,
            ),
        ),
    )


class _RecordingPublisher:
    def __init__(self, *, already_existed: bool = False) -> None:
        self.requests: list[RemediationPr] = []
        self._already_existed = already_existed

    async def publish(self, request: RemediationPr) -> PublishReceipt:
        self.requests.append(request)
        return PublishReceipt(
            pr_ref="example/fdai#7",
            already_existed=self._already_existed,
        )


async def test_collection_review_is_content_addressed_and_inert() -> None:
    package = _package()
    downstream = _RecordingPublisher()
    publisher = GitOpsCollectionReviewPublisher(publisher=downstream)

    receipt = await publisher.publish(package)

    assert receipt.package_digest == package.content_digest
    assert receipt.review_ref == "example/fdai#7"
    assert receipt.already_existed is False
    request = downstream.requests[0]
    assert request.mode is Mode.SHADOW
    assert request.idempotency_key == f"collection-review-{package.content_digest}"
    expected_path = f"rule-catalog/review-packages/collection-{package.content_digest}.json"
    assert request.patch_path == expected_path
    assert not request.patch_path.startswith("rule-catalog/catalog/")
    assert not request.patch_path.startswith("rule-catalog/baselines/")
    assert "shadow" in request.labels
    assert "collection-review" in request.labels
    document = json.loads(request.patch)
    assert document["package_digest"] == package.content_digest
    assert document["source_id"] == package.source_id
    assert document["grants_authority"] is False
    assert document["snapshot_files"][0]["storage_ref"] == package.snapshot_files[0].storage_ref


async def test_existing_review_receipt_preserves_remote_idempotency() -> None:
    package = _package()
    downstream = _RecordingPublisher(already_existed=True)

    receipt = await GitOpsCollectionReviewPublisher(publisher=downstream).publish(package)

    assert receipt.already_existed is True
    assert len(downstream.requests) == 1
