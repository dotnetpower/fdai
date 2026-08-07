"""Isolated Executor command and shadow-receipt contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from fdai.shared.contracts import (
    ExecutorCommand,
    ExecutorShadowReceipt,
    ExecutorShadowReceiptStatus,
    executor_action_payload_digest,
)
from fdai.shared.contracts.models import ExecutionPath, Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import JsonSchemaContractValidator

COMMAND_ID = UUID("00000000-0000-0000-0000-000000000071")
ACTION_ID = UUID("00000000-0000-0000-0000-000000000072")
EVENT_ID = UUID("00000000-0000-0000-0000-000000000073")
RECEIPT_ID = UUID("00000000-0000-0000-0000-000000000074")
NOW = datetime(2026, 8, 7, 4, 0, tzinfo=UTC)


def _payload(*, mode: str = "shadow") -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "action_id": str(ACTION_ID),
        "event_id": str(EVENT_ID),
        "idempotency_key": "executor-action-1",
        "target_resource_ref": "resource:one",
        "mode": mode,
        "params": {"replicas": 2},
    }


def _command(**changes: object) -> ExecutorCommand:
    payload = changes.pop("action_payload", _payload())
    assert isinstance(payload, dict)
    values: dict[str, object] = {
        "command_id": COMMAND_ID,
        "action_schema_version": "1.0.0",
        "action_id": ACTION_ID,
        "event_id": EVENT_ID,
        "idempotency_key": "executor-action-1",
        "target_resource_ref": "resource:one",
        "partition_key": "resource:one",
        "execution_path": ExecutionPath.DIRECT_API,
        "requested_mode": Mode.SHADOW,
        "attempt": 1,
        "issued_at": NOW,
        "deadline_at": NOW + timedelta(minutes=1),
        "action_payload_digest": executor_action_payload_digest(payload),
        "action_payload": payload,
    }
    values.update(changes)
    return ExecutorCommand.model_validate(values)


def _receipt(**changes: object) -> ExecutorShadowReceipt:
    values: dict[str, object] = {
        "receipt_id": RECEIPT_ID,
        "command_id": COMMAND_ID,
        "action_id": ACTION_ID,
        "idempotency_key": "executor-action-1",
        "attempt": 1,
        "action_payload_digest": executor_action_payload_digest(_payload()),
        "requested_mode": Mode.SHADOW,
        "status": ExecutorShadowReceiptStatus.SHADOWED,
        "reason": "shadow command recorded without dispatch",
        "executor_instance_id": "executor-instance-1",
        "received_at": NOW,
        "completed_at": NOW,
        "effect_applied": False,
    }
    values.update(changes)
    return ExecutorShadowReceipt.model_validate(values)


def test_command_and_shadow_receipt_round_trip_without_effect_authority() -> None:
    command = _command()
    receipt = _receipt()
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())

    assert ExecutorCommand.model_validate_json(command.model_dump_json()) == command
    assert ExecutorShadowReceipt.model_validate_json(receipt.model_dump_json()) == receipt
    validator.validate("executor-command", command.model_dump(mode="json"))
    validator.validate(
        "executor-receipt",
        receipt.model_dump(mode="json"),
        version=receipt.schema_version,
    )
    assert receipt.effect_applied is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("action_schema_version", "2.0.0"),
        ("action_id", UUID("00000000-0000-0000-0000-000000000099")),
        ("partition_key", "resource:other"),
        ("requested_mode", Mode.ENFORCE),
    ],
)
def test_command_rejects_envelope_or_partition_mismatch(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match="does not match|partition key"):
        _command(**{field: value})


def test_command_rejects_payload_digest_tampering() -> None:
    with pytest.raises(ValidationError, match="payload digest mismatch"):
        _command(action_payload_digest="sha256:" + "0" * 64)


def test_command_rejects_naive_or_non_future_deadline() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        _command(issued_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError, match="deadline MUST follow"):
        _command(deadline_at=NOW)


def test_payload_digest_rejects_non_json_and_oversized_values() -> None:
    with pytest.raises(ValueError, match="canonical JSON"):
        executor_action_payload_digest({"bad": object()})
    with pytest.raises(ValueError, match="byte limit"):
        executor_action_payload_digest({"text": "x" * 262_145})


def test_shadow_receipt_rejects_enforce_success_or_effect_claim() -> None:
    with pytest.raises(ValidationError, match="reject enforce"):
        _receipt(requested_mode=Mode.ENFORCE)
    with pytest.raises(ValidationError, match="Input should be False"):
        _receipt(effect_applied=True)


def test_enforce_request_can_only_produce_rejected_shadow_receipt() -> None:
    enforce_payload = _payload(mode="enforce")
    command = _command(
        requested_mode=Mode.ENFORCE,
        action_payload=enforce_payload,
        action_payload_digest=executor_action_payload_digest(enforce_payload),
    )
    receipt = _receipt(
        requested_mode=Mode.ENFORCE,
        status=ExecutorShadowReceiptStatus.REJECTED,
        reason="effect authority is not available before SD-08",
    )

    assert command.requested_mode is Mode.ENFORCE
    assert receipt.status is ExecutorShadowReceiptStatus.REJECTED
    assert receipt.effect_applied is False
