"""Assurance Twin - bounded posture/review activity tip contract tests."""

from __future__ import annotations

import json

import pytest
from fdai.core.assurance_twin import build_posture_assessment_report
from fdai.core.assurance_twin.posture_activity import (
    AssuranceTwinReviewActivity,
    build_change_review_activity,
    build_posture_report_activity,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.iac_review import IacReview
from fdai.shared.providers.projection import Finding, ResourceRef
from fdai_service_contracts import (
    JsonSchemaContractValidator,
    OperationalActivityStatus,
    OperationalFreshness,
    PackageResourceSchemaRegistry,
)


def _finding(rule: str = "r-1", ref: str = "vm-a", severity: str = "high") -> Finding:
    return Finding(
        rule_id=rule,
        resource=ResourceRef(resource_type="compute.vm", ref=ref),
        severity=severity,  # type: ignore[arg-type]
        reason="reason",
    )


def _report(
    *findings: Finding,
    scope: str = "sub/00000000-0000-0000-0000-000000000001",
    generated_at: str = "2026-07-07T00:00:00Z",
) -> object:
    return build_posture_assessment_report(
        scope=scope,
        generated_at=generated_at,
        mode=Mode.SHADOW,
        findings=findings,
    )


def _review(
    *findings: Finding,
    pr_ref: str = "owner/repo#1",
    review_key: str = "k-1",
) -> IacReview:
    return IacReview(
        pr_ref=pr_ref,
        review_key=review_key,
        findings=findings,
        verdict="needs_review",
        mode=Mode.SHADOW,
        generated_at="2026-07-07T00:00:00Z",
    )


def test_posture_report_activity_is_authority_free_and_schema_valid() -> None:
    scope = "sub/customer-sensitive-scope"
    correlation_id = "sub/customer-sensitive-correlation"
    activity = build_posture_report_activity(
        _report(_finding(), scope=scope),
        correlation_id=correlation_id,
        freshness=OperationalFreshness.FRESH,
    )
    payload = activity.model_dump(mode="json")

    assert payload["execution_authority"] is False
    assert payload["owner_agent"] == "Heimdall"
    assert payload["producer"] == "assurance-twin"
    assert payload["observation_domain"] is None
    assert payload["evidence_count"] == 1
    assert payload["source"] == "assurance-twin:posture"
    assert scope not in json.dumps(payload)
    assert correlation_id not in json.dumps(payload)
    assert activity.status is OperationalActivityStatus.COMPLETED
    JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate(
        "agent-operational-activity",
        payload,
        version="1.2.0",
    )


def test_change_review_activity_is_authority_free_and_schema_valid() -> None:
    pr_ref = "customer/repository#1"
    review_key = "customer/repository#1:change-a"
    correlation_id = "customer/repository#1:correlation"
    activity = build_change_review_activity(
        _review(
            _finding(),
            _finding(rule="r-2"),
            pr_ref=pr_ref,
            review_key=review_key,
        ),
        correlation_id=correlation_id,
        freshness=OperationalFreshness.FRESH,
    )
    payload = activity.model_dump(mode="json")

    assert payload["execution_authority"] is False
    assert payload["owner_agent"] == "Forseti"
    assert payload["evidence_count"] == 2
    assert payload["source"] == "assurance-twin:review"
    serialized = json.dumps(payload)
    assert pr_ref not in serialized
    assert review_key not in serialized
    assert correlation_id not in serialized
    assert AssuranceTwinReviewActivity.model_validate(payload) == activity


def test_posture_activity_identity_binds_privacy_safe_report_evidence() -> None:
    correlation_id = "shared-correlation"
    first = build_posture_report_activity(
        _report(scope="scope-a"),
        correlation_id=correlation_id,
        freshness=OperationalFreshness.FRESH,
    )
    second = build_posture_report_activity(
        _report(scope="scope-b"),
        correlation_id=correlation_id,
        freshness=OperationalFreshness.FRESH,
    )
    replay = build_posture_report_activity(
        _report(scope="scope-a"),
        correlation_id=correlation_id,
        freshness=OperationalFreshness.FRESH,
    )

    assert first.activity_id != second.activity_id
    assert first.idempotency_key != second.idempotency_key
    assert replay.activity_id == first.activity_id
    assert "scope-a" not in first.activity_id
    assert correlation_id not in first.activity_id


def test_unavailable_freshness_requires_reason_code() -> None:
    with pytest.raises(ValueError, match="MUST include a reason code"):
        build_posture_report_activity(
            _report(),
            correlation_id="posture-2",
            freshness=OperationalFreshness.UNAVAILABLE,
        )


def test_stale_freshness_requires_reason_code() -> None:
    with pytest.raises(ValueError, match="MUST include a reason code"):
        build_change_review_activity(
            _review(),
            correlation_id="review-2",
            freshness=OperationalFreshness.STALE,
        )


def test_unavailable_freshness_with_reason_yields_failed_status() -> None:
    activity = build_posture_report_activity(
        _report(),
        correlation_id="posture-3",
        freshness=OperationalFreshness.UNAVAILABLE,
        reason_codes=("inventory_freshness_ttl_exceeded",),
    )
    assert activity.status is OperationalActivityStatus.FAILED
    assert activity.freshness is OperationalFreshness.UNAVAILABLE


def test_empty_correlation_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="correlation_id MUST be non-empty"):
        build_posture_report_activity(
            _report(),
            correlation_id="  ",
            freshness=OperationalFreshness.FRESH,
        )
