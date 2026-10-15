from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from fdai.delivery.operational_readiness_remediation import (
    EventBusRemediationProposalPublisher,
)
from fdai.shared.contracts import Event
from fdai.shared.providers import PublishReceipt


class RecordingEventBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, object], str]] = []

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        self.published.append((topic, dict(payload), key))
        return PublishReceipt(topic=topic, partition=0, offset=len(self.published) - 1)


def _proposal(**overrides: object) -> dict[str, object]:
    proposal: dict[str, object] = {
        "kind": "operational_readiness.remediation_proposal",
        "action_type": "remediate.tag-add",
        "resource_ref": "resource:vm-1",
        "scope": "subscription:test",
        "target_environment": "development",
        "submitter": "operator-a",
        "approver": "operator-b",
        "approved_at": "2026-10-15T00:00:00Z",
        "evidence": ["evidence:orr-1"],
        "severity": "high",
        "blocking": True,
        "idempotency_key": "orr-remediation-1",
        "dimension": "rollback",
        "control_id": "orr.rollback",
        "mode": "shadow",
    }
    proposal.update(overrides)
    return proposal


@pytest.mark.asyncio
async def test_publishes_shadow_proposal_to_governed_operator_request_ingress() -> None:
    event_bus = RecordingEventBus()
    publisher = EventBusRemediationProposalPublisher(
        event_bus=event_bus,
        topic="fdai.events",
    )

    await publisher.publish_remediation_proposal(_proposal())

    topic, raw_event, key = event_bus.published[0]
    event = Event.model_validate(raw_event)
    assert topic == "fdai.events"
    assert key == "resource:vm-1"
    assert event.event_type == "operator_request"
    assert event.source == "operational-readiness"
    assert event.resource_ref == "resource:vm-1"
    operator_request = event.payload["operator_request"]
    assert operator_request == {
        "initiator_principal": "operator-a",
        "action_type": "remediate.tag-add",
        "params": {},
    }
    readiness = event.payload["operational_readiness"]
    assert readiness["route"] == "risk_gate"
    assert readiness["request_id"] == "orr-remediation-1"
    assert readiness["grants_authority"] is False
    proposal = readiness["proposal"]
    assert isinstance(proposal, dict)
    assert proposal["mode"] == "shadow"
    assert proposal["approval_required"] is True
    assert proposal["execution_authority"] is False
    assert "executor" not in event.payload

    await publisher.publish_remediation_proposal(_proposal())
    repeated = Event.model_validate(event_bus.published[1][1])
    assert repeated.event_id == event.event_id
    assert repeated.idempotency_key == event.idempotency_key


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"mode": "execute"}, "shadow mode"),
        ({"execution_authority": True}, "execution authority"),
        ({"resource_ref": ""}, "resource_ref"),
    ],
)
async def test_rejects_authority_or_ungrounded_target(
    overrides: dict[str, object],
    message: str,
) -> None:
    publisher = EventBusRemediationProposalPublisher(
        event_bus=RecordingEventBus(),
        topic="fdai.events",
    )

    with pytest.raises(ValueError, match=message):
        await publisher.publish_remediation_proposal(_proposal(**overrides))


def test_rejects_empty_topic() -> None:
    with pytest.raises(ValueError, match="topic"):
        EventBusRemediationProposalPublisher(
            event_bus=RecordingEventBus(),
            topic=" ",
        )
