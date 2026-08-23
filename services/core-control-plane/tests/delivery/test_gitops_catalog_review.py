"""Draft-only GitOps catalog review publication tests."""

from __future__ import annotations

import json

from fdai.core.operational_learning import (
    CatalogReviewPackage,
    DraftCatalogArtifact,
    OperationalPatternRuleCandidate,
    PolicyCheckReceipt,
    ReplayCheckReceipt,
    SchemaCheckReceipt,
    ShadowCheckReceipt,
)
from fdai.delivery.gitops_pr.catalog_review import GitOpsCatalogReviewPublisher
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.remediation_pr import PublishReceipt, RemediationPr


def _review_package() -> CatalogReviewPackage:
    candidate = OperationalPatternRuleCandidate(
        pattern_id="1" * 64,
        failure_fingerprint="2" * 64,
        resource_type="kubernetes.service",
        action_type="ops.scale-out",
        sample_size=2,
        reusable_count=1,
        negative_count=1,
        outcome_counts=(("rollback", 1), ("success", 1)),
        immutable_case_refs=(
            f"case-history:case-a:1:{'3' * 64}",
            f"case-history:case-b:1:{'4' * 64}",
        ),
        digest_evidence=("5" * 64,),
        digest="6" * 64,
    )
    common = {"candidate_digest": candidate.digest, "artifact_digest": "7" * 64}
    return CatalogReviewPackage(
        candidate=candidate,
        draft_rule=DraftCatalogArtifact.from_mapping(
            kind="rule",
            mapping={"id": "learned.operational.example", "remediates": "ops.scale-out"},
        ),
        draft_action_type=None,
        immutable_case_refs=candidate.immutable_case_refs,
        catalog_version="catalog-v1",
        schema_version="2.0.0",
        schema=SchemaCheckReceipt(
            **common,
            schema_version="2.0.0",
            passed=True,
        ),
        replay=ReplayCheckReceipt(
            **common,
            replay_version="replay-v1",
            first_result_digest="8" * 64,
            second_result_digest="8" * 64,
            passed=True,
        ),
        shadow=ShadowCheckReceipt(
            **common,
            scenario_set_id="operational-learning-v1",
            baseline_result_digest="9" * 64,
            challenger_result_digest="a" * 64,
            regression_passed=True,
            policy_escapes=0,
            passed=True,
        ),
        policy=PolicyCheckReceipt(
            **common,
            policy_version="policy-v1",
            policy_escapes=0,
            passed=True,
        ),
        review_required=True,
        content_digest="b" * 64,
    )


class _RecordingPublisher:
    def __init__(self, *, already_existed: bool = False) -> None:
        self.requests: list[RemediationPr] = []
        self._already_existed = already_existed

    async def publish(self, request: RemediationPr) -> PublishReceipt:
        self.requests.append(request)
        return PublishReceipt(
            pr_ref="example/fdai-catalog#42",
            already_existed=self._already_existed,
        )


async def test_catalog_review_is_content_addressed_and_inert() -> None:
    package = _review_package()
    downstream = _RecordingPublisher()
    publisher = GitOpsCatalogReviewPublisher(publisher=downstream)

    receipt = await publisher.publish(package)

    assert receipt.package_digest == package.content_digest
    assert receipt.review_ref == "example/fdai-catalog#42"
    assert receipt.already_existed is False
    request = downstream.requests[0]
    assert request.mode is Mode.SHADOW
    assert request.idempotency_key == f"catalog-review-{package.content_digest}"
    assert request.patch_path.endswith(f"operational-{package.content_digest}.json")
    assert "shadow" in request.labels
    document = json.loads(request.patch)
    assert document["package_digest"] == package.content_digest
    assert document["review_required"] is True
    assert document["grants_authority"] is False
    assert document["draft_rule"] == package.draft_rule.mapping


async def test_existing_review_receipt_preserves_remote_idempotency() -> None:
    package = _review_package()
    downstream = _RecordingPublisher(already_existed=True)

    receipt = await GitOpsCatalogReviewPublisher(publisher=downstream).publish(package)

    assert receipt.already_existed is True
    assert len(downstream.requests) == 1
