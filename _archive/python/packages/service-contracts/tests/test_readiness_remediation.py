from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai_service_contracts.readiness_remediation import ReadinessRemediationRequest
from pydantic import ValidationError


def _request() -> ReadinessRemediationRequest:
    now = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    return ReadinessRemediationRequest.create(
        idempotency_key="orr-remediation:" + "a" * 32,
        action_type="remediate.tag-add",
        target_resource_ref="resource:storage/account/example",
        target_revision="inventory-revision-7",
        params={},
        citing_rule_ids=("readiness.owner-tag.required",),
        evidence_refs=("evidence:orr:owner-tag",),
        submitter="handoff-owner",
        approver="operations-approver",
        approved_at=now,
        requested_at=now,
        severity="high",
    )


def test_request_binds_shadow_authority_identity_and_digest() -> None:
    request = _request()

    assert request.request_id.startswith("orr-remediation-")
    assert request.request_digest.startswith("sha256:")
    assert request.source_mode == "shadow"
    assert request.approval_authority is False
    assert request.execution_authority is False


def test_request_rejects_target_revision_tampering() -> None:
    payload = _request().model_dump(mode="json")
    payload["target_revision"] = "inventory-revision-8"

    with pytest.raises(ValidationError, match="request digest mismatched"):
        ReadinessRemediationRequest.model_validate(payload)


def test_request_rejects_self_approval() -> None:
    for approver in ("handoff-owner", "ｈａｎｄｏｆｆ-owner"):
        payload = _request().model_dump(mode="json")
        payload["approver"] = approver

        with pytest.raises(ValidationError, match="MUST NOT approve"):
            ReadinessRemediationRequest.model_validate(payload)


def test_request_rejects_authority_escalation() -> None:
    payload = _request().model_dump(mode="json")
    payload["execution_authority"] = True

    with pytest.raises(ValidationError, match="Input should be False"):
        ReadinessRemediationRequest.model_validate(payload)


def test_request_factory_rejects_naive_time() -> None:
    now = datetime(2026, 10, 15, 9, 0)

    with pytest.raises(ValueError, match="timezone"):
        ReadinessRemediationRequest.create(
            idempotency_key="orr-remediation:" + "a" * 32,
            action_type="remediate.tag-add",
            target_resource_ref="resource:storage/account/example",
            target_revision="inventory-revision-7",
            params={},
            citing_rule_ids=("readiness.owner-tag.required",),
            evidence_refs=("evidence:orr:owner-tag",),
            submitter="handoff-owner",
            approver="operations-approver",
            approved_at=now,
            requested_at=now,
            severity="high",
        )
