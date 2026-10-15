"""Publish operational-readiness remediation proposals to governed ingress."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fdai.shared.contracts import Event
from fdai.shared.providers import EventBus


class EventBusRemediationProposalPublisher:
    """Route shadow remediation proposals through ordinary risk-gated ingress."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        topic: str,
    ) -> None:
        if not topic.strip():
            raise ValueError("remediation proposal topic MUST be non-empty")
        self._event_bus = event_bus
        self._topic = topic.strip()

    async def publish_remediation_proposal(
        self,
        proposal: Mapping[str, Any],
    ) -> None:
        resource_ref = _required_string(proposal, "resource_ref")
        action_type = _required_string(proposal, "action_type")
        idempotency_key = _required_string(proposal, "idempotency_key")
        if proposal.get("kind") != "operational_readiness.remediation_proposal":
            raise ValueError("remediation proposal kind is invalid")
        if proposal.get("mode") != "shadow":
            raise ValueError("remediation proposals MUST remain in shadow mode")
        if proposal.get("execution_authority") not in (None, False):
            raise ValueError("remediation proposals MUST NOT grant execution authority")

        payload = dict(proposal)
        payload["execution_authority"] = False
        payload["approval_required"] = True
        now = datetime.now(UTC)
        event = Event.model_validate(
            {
                "schema_version": "1.0.0",
                "event_id": str(
                    uuid5(
                        NAMESPACE_URL,
                        f"fdai:operational-readiness-remediation:{idempotency_key}",
                    )
                ),
                "idempotency_key": idempotency_key,
                "event_type": "operator_request",
                "correlation_id": f"operational-readiness:{idempotency_key}",
                "source": "operational-readiness",
                "resource_ref": resource_ref,
                "detected_at": now,
                "ingested_at": now,
                "mode": "shadow",
                "payload": {
                    "operator_request": {
                        "initiator_principal": _required_string(proposal, "submitter"),
                        "action_type": action_type,
                        "params": {},
                    },
                    "operational_readiness": {
                        "kind": "operational_readiness.remediation_proposal",
                        "request_id": idempotency_key,
                        "route": "risk_gate",
                        "grants_authority": False,
                        "approval_required": True,
                        "proposal": payload,
                    },
                },
            }
        ).model_dump(mode="json")
        await self._event_bus.publish(self._topic, resource_ref, event)


def _required_string(proposal: Mapping[str, Any], field: str) -> str:
    value = proposal.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"remediation proposal {field} must be a non-empty string")
    return value.strip()


__all__ = ["EventBusRemediationProposalPublisher"]
