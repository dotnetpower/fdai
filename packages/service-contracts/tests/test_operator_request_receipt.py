"""Operator request receipt contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai_service_contracts.operator_request_receipt import (
    OperatorRequestReceipt,
    canonical_workflow_action_digest,
    operator_request_receipt_body_from_event,
)
from pydantic import ValidationError


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
