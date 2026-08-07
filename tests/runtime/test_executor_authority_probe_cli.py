"""Focused contract for the reversible SD-08 authority probe Action."""

from datetime import UTC, datetime

from fdai.runtime.executor_authority_probe_cli import build_probe_action
from fdai.runtime.isolated_executor_client import executor_command_id
from fdai.shared.contracts.models import Mode, Operation


def test_probe_actions_are_enforce_single_target_and_mutual_rollbacks() -> None:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    upsert = build_probe_action(
        operation="upsert",
        resource_group="example",
        nsg_name="nsg-example",
        rule_name="fdai-sd08-probe",
        idempotency_key="probe-upsert",
        now=now,
    )
    delete = build_probe_action(
        operation="delete",
        resource_group="example",
        nsg_name="nsg-example",
        rule_name="fdai-sd08-probe",
        idempotency_key="probe-delete",
        now=now,
    )

    assert upsert.mode is delete.mode is Mode.ENFORCE
    assert upsert.operation is Operation.UPDATE
    assert delete.operation is Operation.DELETE
    assert upsert.blast_radius.count == delete.blast_radius.count == 1
    assert upsert.params["rule"]["source_address_prefix"] == "192.0.2.1/32"
    assert "ops.delete-network-rule" in (upsert.rollback_ref.reference or "")
    assert "ops.upsert-network-rule" in (delete.rollback_ref.reference or "")


def test_probe_retry_preserves_action_payload_and_command_identity() -> None:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    first = build_probe_action(
        operation="upsert",
        resource_group="example",
        nsg_name="nsg-example",
        rule_name="fdai-sd08-probe",
        idempotency_key="probe-upsert",
        now=now,
    )
    retry = build_probe_action(
        operation="upsert",
        resource_group="example",
        nsg_name="nsg-example",
        rule_name="fdai-sd08-probe",
        idempotency_key="probe-upsert",
        now=now,
    )

    assert first.model_dump(mode="json") == retry.model_dump(mode="json")
    assert executor_command_id(first) == executor_command_id(retry)
