"""Draft-only GitOps catalog review publication tests."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.operational_learning import (
    CatalogReviewPackage,
    DraftCatalogArtifact,
    OperationalPatternRuleCandidate,
    PolicyCheckReceipt,
    ReplayCheckReceipt,
    SchemaCheckReceipt,
    ShadowCheckReceipt,
)
from fdai.core.operational_learning.case_review import OperationalCaseReview
from fdai.delivery.gitops_pr.catalog_review import (
    CatalogReviewPrObservation,
    GitOpsCatalogReviewPublisher,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.remediation_pr import PublishReceipt, RemediationPr

_REQUIRED_LABELS = (
    "action:ops.scale-out",
    "catalog-review",
    "draft",
    "governance",
    "rule:learned.operational.example",
    "shadow",
)
_HEAD_SHA = "f" * 40


def _review_package() -> CatalogReviewPackage:
    case_refs = (
        f"case-history:case-a:1:{'3' * 64}",
        f"case-history:case-b:1:{'4' * 64}",
    )
    case_reviews = tuple(
        OperationalCaseReview(
            case_ref=ref,
            event_time_cutoff=datetime(2026, 1, 1, tzinfo=UTC),
            source_kind="operational_case",
            source_identity_digest="c" * 64,
            source_synthetic=False,
            evidence_complete=True,
            conflict_digests=(),
        )
        for ref in case_refs
    )
    candidate = OperationalPatternRuleCandidate(
        pattern_id="1" * 64,
        failure_fingerprint="2" * 64,
        resource_type="kubernetes.service",
        action_type="ops.scale-out",
        sample_size=2,
        reusable_count=1,
        negative_count=1,
        outcome_counts=(("rollback", 1), ("success", 1)),
        immutable_case_refs=case_refs,
        digest_evidence=("5" * 64,),
        fdai_revision="d" * 40,
        scenario_set_version="operational-learning-v1",
        case_reviews=case_reviews,
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
    def __init__(
        self,
        *,
        already_existed: bool = False,
        observation_updates: dict[str, bool] | None = None,
    ) -> None:
        self.requests: list[RemediationPr] = []
        self._already_existed = already_existed
        self._observation_updates = observation_updates or {}

    async def publish(self, request: RemediationPr) -> PublishReceipt:
        self.requests.append(request)
        return PublishReceipt(
            pr_ref="example/fdai-catalog#42",
            already_existed=self._already_existed,
            head_sha=_HEAD_SHA,
        )

    async def observe_catalog_review(
        self,
        *,
        pr_ref: str,
        idempotency_key: str,
        required_labels: tuple[str, ...],
        expected_head_sha: str,
        expected_path: str,
        expected_document_digest: str,
    ) -> CatalogReviewPrObservation:
        assert pr_ref == "example/fdai-catalog#42"
        assert idempotency_key.startswith("catalog-review-")
        assert required_labels == _REQUIRED_LABELS
        assert expected_head_sha == _HEAD_SHA
        assert expected_path.startswith("rule-catalog/review-packages/operational-")
        assert len(expected_document_digest) == 64
        values = {
            "open": True,
            "draft": True,
            "head_matches": True,
            "head_commit_matches": True,
            "base_matches": True,
            "labels_match": True,
            "content_matches": True,
            "files_match": True,
            "observed_labels": required_labels,
            "merged": False,
            "auto_merge_enabled": False,
            **self._observation_updates,
        }
        return CatalogReviewPrObservation(
            observation_digest="e" * 64,
            **values,
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
    assert "draft" in request.labels
    assert "shadow" in request.labels
    assert "rule:learned.operational.example" in request.labels
    assert "action:ops.scale-out" in request.labels
    assert receipt.required_labels == _REQUIRED_LABELS
    assert receipt.observed_labels == _REQUIRED_LABELS
    assert receipt.head_sha == _HEAD_SHA
    assert receipt.review_document_digest is not None
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


async def test_catalog_review_rejects_exact_label_over_provider_limit() -> None:
    package = _review_package()
    oversized = replace(
        package,
        draft_rule=DraftCatalogArtifact.from_mapping(
            kind="rule",
            mapping={
                "id": "learned.operational." + "f" * 40,
                "remediates": "ops.scale-out",
            },
        ),
    )

    with pytest.raises(ValueError, match="label limit"):
        await GitOpsCatalogReviewPublisher(publisher=_RecordingPublisher()).publish(oversized)


@pytest.mark.parametrize(
    "observation_updates",
    [
        {"draft": False},
        {"head_matches": False},
        {"head_commit_matches": False},
        {"base_matches": False},
        {"labels_match": False},
        {"content_matches": False},
        {"files_match": False},
        {"merged": True},
        {"auto_merge_enabled": True},
    ],
)
async def test_catalog_review_rejects_substituted_or_mergeable_pr(
    observation_updates: dict[str, bool],
) -> None:
    publisher = GitOpsCatalogReviewPublisher(
        publisher=_RecordingPublisher(observation_updates=observation_updates)
    )

    with pytest.raises(ValueError, match="readback is unsafe"):
        await publisher.publish(_review_package())
