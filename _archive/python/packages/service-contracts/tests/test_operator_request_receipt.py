"""Operator request receipt contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai_service_contracts.operator_request_receipt import (
    OperatorRequestReceipt,
    OperatorRequestReceiptBody,
    canonical_params_digest,
    canonical_workflow_action_digest,
    operator_request_receipt_digest,
    operator_request_receipt_body_from_event,
)
from pydantic import ValidationError
from pydantic import BaseModel, ConfigDict


def test_operator_request_receipt_binds_exact_request_and_signature() -> None:
    now = datetime(2026, 10, 1, tzinfo=UTC)
    body = operator_request_receipt_body_from_event(
        {
            "idempotency_key": "request-one",
            "correlation_id": "conversation-one",
            "initiator_principal": "operator-one",
            "action_type": "ops.scale-out",
            "resource_id": "resource-one",
            "params": {"replicas": 3},
        },
        producer_service_identity="operator-service",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )

    receipt = OperatorRequestReceipt.create(body=body, signature=b"signature")

    assert receipt.initiator_principal == "operator-one"
    assert receipt.producer_service_identity == "operator-service"
    assert receipt.schema_version == "1.1.0"
    assert receipt.canonical_workflow_action_digest == canonical_workflow_action_digest(None)
    assert receipt.signature_bytes() == b"signature"


def test_operator_request_receipt_binds_workflow_action_lineage() -> None:
    now = datetime(2026, 10, 1, tzinfo=UTC)
    workflow_action = {
        "process_id": "process-one",
        "step_id": "restart",
        "proposal_ref": "process-one:step:restart:attempt:1",
        "attempt": 1,
    }

    body = operator_request_receipt_body_from_event(
        {
            "idempotency_key": "request-one",
            "correlation_id": "conversation-one",
            "initiator_principal": "operator-one",
            "action_type": "ops.restart",
            "resource_id": "resource-one",
            "params": {"target": "resource-one"},
            "workflow_action": workflow_action,
        },
        producer_service_identity="operator-service",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )

    assert body.schema_version == "1.1.0"
    assert body.canonical_workflow_action_digest == canonical_workflow_action_digest(
        workflow_action
    )


def test_operator_request_receipt_distinguishes_absent_and_empty_workflow_lineage() -> None:
    assert canonical_workflow_action_digest(None) != canonical_workflow_action_digest({})


def test_operator_request_receipt_v1_0_remains_compatible_without_workflow_lineage() -> None:
    now = datetime(2026, 10, 1, tzinfo=UTC)

    body = operator_request_receipt_body_from_event(
        {
            "idempotency_key": "request-one",
            "correlation_id": "conversation-one",
            "initiator_principal": "operator-one",
            "action_type": "ops.scale-out",
            "resource_id": "resource-one",
            "params": {},
        },
        producer_service_identity="operator-service",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
        schema_version="1.0.0",
    )

    assert body.schema_version == "1.0.0"
    assert body.canonical_workflow_action_digest is None


def test_operator_request_receipt_v1_0_and_v1_1_golden_digests_remain_stable() -> None:
    issued = datetime(2026, 1, 1, tzinfo=UTC)
    expires = issued + timedelta(minutes=5)
    common = {
        "idempotency_key": "idem-1",
        "correlation_id": "corr-1",
        "initiator_principal": "operator-1",
        "action_type": "incident.create",
        "canonical_params_digest": canonical_params_digest({"a": 1}),
        "resource_id": "resource-1",
        "producer_service_identity": "operator-service",
        "issued_at": issued,
        "expires_at": expires,
    }

    assert (
        operator_request_receipt_digest(
            OperatorRequestReceiptBody(schema_version="1.0.0", **common)
        )
        == "sha256:7680f89f5917806214b1b5af3ffcf2a1a1746ff4f5027373f60e82bd1f70f346"
    )
    assert (
        operator_request_receipt_digest(
            OperatorRequestReceiptBody(
                schema_version="1.1.0",
                canonical_workflow_action_digest=canonical_workflow_action_digest(None),
                **common,
            )
        )
        == "sha256:c0408e047074c98da5b248824a6baac7ccd8207ffc454aa49cbab9c9757af93d"
    )


def test_operator_request_receipt_v1_2_binds_fresh_auth_context() -> None:
    now = datetime(2026, 10, 1, tzinfo=UTC)

    body = operator_request_receipt_body_from_event(
        {
            "operator_request_receipt_schema_version": "1.2.0",
            "idempotency_key": "request-one",
            "correlation_id": "conversation-one",
            "initiator_principal": "operator-one",
            "action_type": "policy.revision-request",
            "resource_id": "policy:admission",
            "params": {"content_digest": "sha256:" + "a" * 64},
            "authenticated_at": now.isoformat(),
            "max_auth_age_seconds": 600,
            "principal_roles": ("Owner", "policy-admin"),
        },
        producer_service_identity="operator-service",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )

    assert body.schema_version == "1.2.0"
    assert body.authenticated_at == now
    assert body.principal_roles == ("Owner", "policy-admin")
    assert body.max_auth_age_seconds == 600


def test_operator_request_receipt_v1_1_serializes_for_head_schema_compatibility() -> None:
    now = datetime(2026, 10, 1, tzinfo=UTC)
    body = operator_request_receipt_body_from_event(
        {
            "idempotency_key": "request-one",
            "correlation_id": "conversation-one",
            "initiator_principal": "operator-one",
            "action_type": "ops.scale-out",
            "resource_id": "resource-one",
            "params": {"replicas": 3},
        },
        producer_service_identity="operator-service",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    receipt = OperatorRequestReceipt.create(body=body, signature=b"signature")
    serialized = receipt.model_dump(mode="json")

    assert "authenticated_at" not in serialized
    assert "principal_roles" not in serialized
    assert "max_auth_age_seconds" not in serialized
    _HeadReceiptV11.model_validate(serialized)


class _HeadReceiptV11(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    idempotency_key: str
    correlation_id: str
    initiator_principal: str
    action_type: str
    canonical_params_digest: str
    resource_id: str
    canonical_workflow_action_digest: str
    producer_service_identity: str
    issued_at: datetime
    expires_at: datetime
    receipt_digest: str
    signature_alg: str
    signature: str


def test_operator_request_receipt_rejects_unbounded_validity() -> None:
    now = datetime(2026, 10, 1, tzinfo=UTC)

    with pytest.raises(ValidationError, match="validity MUST be positive and bounded"):
        operator_request_receipt_body_from_event(
            {
                "idempotency_key": "request-one",
                "correlation_id": "conversation-one",
                "initiator_principal": "operator-one",
                "action_type": "ops.scale-out",
                "resource_id": "resource-one",
                "params": {},
            },
            producer_service_identity="operator-service",
            issued_at=now,
            expires_at=now + timedelta(hours=1),
        )
