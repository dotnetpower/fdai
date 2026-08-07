"""Focused contract for the reversible SD-08 authority probe Action."""

from datetime import UTC, datetime

from fdai.runtime.executor_authority_probe_cli import build_probe_action
from fdai.shared.contracts.models import Mode, Operation


def test_probe_actions_are_enforce_single_target_and_mutual_rollbacks() -> None:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    common = {
        "resource_group": "example",
        "nsg_name": "nsg-example",
        "rule_name": "fdai-sd08-probe",
        "now": now,
    }

    upsert = build_probe_action(operation="upsert", idempotency_key="probe-upsert", **common)
    delete = build_probe_action(operation="delete", idempotency_key="probe-delete", **common)

    assert upsert.mode is delete.mode is Mode.ENFORCE
    assert upsert.operation is Operation.UPDATE
    assert delete.operation is Operation.DELETE
    assert upsert.blast_radius.count == delete.blast_radius.count == 1
    assert upsert.params["rule"]["source_address_prefix"] == "192.0.2.1/32"
    assert "ops.delete-network-rule" in (upsert.rollback_ref.reference or "")
    assert "ops.upsert-network-rule" in (delete.rollback_ref.reference or "")
