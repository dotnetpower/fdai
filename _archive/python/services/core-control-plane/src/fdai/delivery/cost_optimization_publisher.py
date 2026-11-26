"""Broker-only Cost Governance optimization ingress adapter."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from fdai.agents import validate_cross_vertical_candidate
from fdai.shared.providers.cost_governance import COST_OPTIMIZATION_EVENT_TYPE
from fdai.shared.providers.event_bus import EventBus


@dataclass(frozen=True, slots=True)
class EventBusCostOptimizationCandidatePublisher:
    bus: EventBus
    topic: str

    async def publish_cost_optimization_candidate(
        self,
        candidate: dict[str, Any],
        *,
        activation_revision: int,
    ) -> None:
        if not isinstance(self.topic, str) or not self.topic.strip():
            raise ValueError("optimization ingress topic MUST be non-empty")
        if (
            isinstance(activation_revision, bool)
            or not isinstance(activation_revision, int)
            or activation_revision < 0
        ):
            raise ValueError("optimization ingress activation revision MUST be non-negative")
        if "producer_principal" in candidate:
            raise ValueError("optimization ingress MUST NOT supply an agent principal")
        validate_cross_vertical_candidate(
            "object.cost-anomaly",
            {**candidate, "producer_principal": "Njord"},
        )
        resource_id = str(candidate.get("resource_id") or "").strip()
        correlation_id = str(candidate.get("correlation_id") or "").strip()
        idempotency_key = str(candidate.get("idempotency_key") or "").strip()
        observed_at = str(candidate.get("observed_at") or "").strip()
        if not resource_id or not correlation_id or not idempotency_key or not observed_at:
            raise ValueError("optimization candidate envelope fields MUST be non-empty")
        event_digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
        await self.bus.publish(
            self.topic,
            resource_id,
            {
                "idempotency_key": idempotency_key,
                "event_id": f"optimization:{event_digest}",
                "event_type": COST_OPTIMIZATION_EVENT_TYPE,
                "source": "fdai-cost-governance",
                "resource_id": resource_id,
                "correlation_id": correlation_id,
                "occurred_at": observed_at,
                "attributes": {
                    "activation_revision": activation_revision,
                    "candidate": dict(candidate),
                },
            },
        )


__all__ = ["EventBusCostOptimizationCandidatePublisher"]
