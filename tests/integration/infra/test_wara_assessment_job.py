"""Deployment contract for the scheduled logical-topic WARA assessment."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MAIN = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
JOB = (ROOT / "infra/modules/compute/container-apps/wara_assessment_job.tf").read_text(
    encoding="utf-8"
)


def test_wara_job_uses_existing_physical_topic_and_narrow_sender_role() -> None:
    assert "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC" in JOB
    assert 'resource "azurerm_role_assignment" "inventory_wara_sender"' in MAIN
    assert "module.event_bus.topic_ids[local.semantic_turn_physical_topic]" in MAIN
    assert 'role_definition_name = "Azure Event Hubs Data Sender"' in MAIN


def test_wara_logical_topic_is_not_provisioned_as_an_extra_event_hub() -> None:
    event_topics = MAIN[MAIN.index("event_topics = [") : MAIN.index("event_auxiliary_topics =")]
    assert "assessment.wara" not in event_topics
