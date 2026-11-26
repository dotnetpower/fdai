"""The analyzer's broker readback has only the exact ingest-topic read identity."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def test_analyzer_readback_role_uses_the_job_identity_and_exact_ingest_topic() -> None:
    source = (_ROOT / "infra/main.tf").read_text(encoding="utf-8")
    start = source.index(
        'resource "azurerm_role_assignment" "inventory_analyzer_eventhubs_receiver" {'
    )
    role = source[start : source.index("\n}", start) + 2]
    assert "scope                = module.event_bus.topic_ids[local.event_topics[0]]" in role
    assert 'role_definition_name = "Azure Event Hubs Data Receiver"' in role
    assert "principal_id         = module.inventory_identity.principal_id" in role
    assert "azurerm_role_assignment.inventory_analyzer_eventhubs_receiver," in source
    sender_start = source.index('resource "azurerm_role_assignment" "inventory_eventhubs_sender" {')
    sender = source[sender_start : source.index("\n}", sender_start) + 2]
    assert "depends_on = [azurerm_role_assignment.inventory_analyzer_eventhubs_receiver]" in sender

    job = (_ROOT / "infra/modules/compute/container-apps/analyzer_tick_job.tf").read_text(
        encoding="utf-8"
    )
    assert "identity_ids = [var.inventory_identity_id]" in job
    targets = (
        _ROOT / "packages/deployment-cli/src/fdai_deployment_cli/standalone_stage_targets.py"
    ).read_text(encoding="utf-8")
    assert '"azurerm_role_assignment.inventory_eventhubs_sender"' in targets
