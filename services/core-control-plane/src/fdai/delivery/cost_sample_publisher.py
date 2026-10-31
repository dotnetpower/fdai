"""Broker-only Cost Governance sample ingress adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC

from fdai.shared.providers.cost_governance import COST_SAMPLE_EVENT_TYPE, CostObservation
from fdai.shared.providers.event_bus import EventBus


@dataclass(frozen=True, slots=True)
class EventBusCostSamplePublisher:
    """Publish raw cost samples for Huginn normalization; never call Njord."""

    bus: EventBus
    topic: str

    async def publish_cost_sample(
        self,
        observation: CostObservation,
        *,
        activation_revision: int,
    ) -> None:
        if not isinstance(self.topic, str) or not self.topic.strip():
            raise ValueError("cost sample publisher topic MUST be non-empty")
        if (
            isinstance(activation_revision, bool)
            or not isinstance(activation_revision, int)
            or activation_revision < 0
        ):
            raise ValueError("cost sample activation revision MUST be non-negative")
        if observation.currency != "USD":
            raise ValueError("cost sample publisher requires authoritative USD observations")
        if observation.observed_at.tzinfo is None or observation.observed_at.utcoffset() is None:
            raise ValueError("cost sample observed_at MUST be timezone-aware")
        observed_iso = observation.observed_at.astimezone(UTC).isoformat()
        payload = {
            "idempotency_key": observation.observation_id,
            "event_id": observation.observation_id,
            "event_type": COST_SAMPLE_EVENT_TYPE,
            "source": observation.source_authority,
            "resource_id": observation.source_uri,
            "correlation_id": observation.observation_id,
            "occurred_at": observed_iso,
            "detected_at": observed_iso,
            "attributes": {
                "scope": observation.scope_id,
                "resource_id": observation.source_uri,
                "amount_usd": float(observation.amount),
                "observed_at": observed_iso,
                "source_authority": observation.source_authority,
                "completeness": float(observation.completeness),
                "ontology_release_digest": observation.ontology_release_digest,
                "activation_revision": activation_revision,
            },
        }
        await self.bus.publish(
            self.topic,
            observation.scope_id,
            payload,
        )


__all__ = ["EventBusCostSamplePublisher"]
