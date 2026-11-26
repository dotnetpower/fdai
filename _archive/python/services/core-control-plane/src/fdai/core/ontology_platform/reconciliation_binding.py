"""Production-ready event and provider binding for effect reconciliation.

Runtime composition supplies an artifact resolver, an observation-context verifier, the durable
ledger, and an EventBus. The binder is a mechanical relay: it grants no authority, mutates no
provider state, and publishes only the ledger's proposal-only outbox event.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from fdai.shared.contracts.models import OntologyActionType, OntologyRelease
from fdai.shared.providers.event_bus import EventBus

from .kinetics import MutationPlan
from .reconciliation import EffectReconciliationCoordinator, ReconciliationLedger
from .reconciliation_contracts import (
    AuthenticatedObservationContext,
    EffectObservationEnvelope,
    ReconciliationOutcome,
)
from .reconciliation_events import (
    EffectReconciliationRequestEvent,
    ReconciliationOutboxEvent,
)

RECONCILIATION_REQUEST_TOPIC = "ontology.effect-reconciliation.requests"
RECONCILIATION_OUTBOX_TOPIC = "ontology.effect-reconciliation.outcomes"


@dataclass(frozen=True, slots=True)
class ResolvedReconciliationArtifacts:
    """Resolver-owned immutable bodies restored from compact exact event references."""

    plan: MutationPlan
    action_type: OntologyActionType
    active_release: OntologyRelease


class ReconciliationArtifactResolver(Protocol):
    """Resolve exact local artifacts without accepting substituted wire bodies."""

    async def resolve(
        self,
        event: EffectReconciliationRequestEvent,
    ) -> ResolvedReconciliationArtifacts: ...


class ObservationContextVerifier(Protocol):
    """Authenticate observation identity, credential lineage, and signed receipt claims."""

    async def verify(
        self,
        *,
        evidence: EffectObservationEnvelope,
        claimed_context: AuthenticatedObservationContext,
    ) -> AuthenticatedObservationContext: ...


class EffectReconciliationBinder:
    """Bind typed observation requests to durable reconciliation and outbox publication.

    ``handle_event`` is safe for at-least-once and reordered delivery because the coordinator and
    ledger own canonical identities. ``publish_pending`` is restart-safe: it leases one durable
    event, publishes its stable idempotency key, and records broker acknowledgement afterward.
    """

    def __init__(
        self,
        *,
        coordinator: EffectReconciliationCoordinator,
        ledger: ReconciliationLedger,
        event_bus: EventBus,
        artifact_resolver: ReconciliationArtifactResolver,
        observation_verifier: ObservationContextVerifier,
        claimant_id: str,
        outbox_topic: str = RECONCILIATION_OUTBOX_TOPIC,
        lease_duration: timedelta = timedelta(seconds=30),
        retry_delay: timedelta = timedelta(seconds=5),
    ) -> None:
        if not claimant_id:
            raise ValueError("reconciliation binder claimant id MUST be non-empty")
        if not outbox_topic:
            raise ValueError("reconciliation outbox topic MUST be non-empty")
        if lease_duration <= timedelta(0) or retry_delay < timedelta(0):
            raise ValueError("reconciliation outbox timing MUST be non-negative")
        self._coordinator = coordinator
        self._ledger = ledger
        self._event_bus = event_bus
        self._artifact_resolver = artifact_resolver
        self._observation_verifier = observation_verifier
        self._claimant_id = claimant_id
        self._outbox_topic = outbox_topic
        self._lease_duration = lease_duration
        self._retry_delay = retry_delay

    async def handle_event(self, payload: Mapping[str, Any]) -> ReconciliationOutcome:
        """Validate one untrusted bus payload and durably record its canonical outcome."""

        event = EffectReconciliationRequestEvent.model_validate(payload)
        authenticated = await self._observation_verifier.verify(
            evidence=event.evidence,
            claimed_context=event.observation_context,
        )
        if authenticated != event.observation_context:
            raise ValueError("verified observation context does not match the request event")
        artifacts = await self._artifact_resolver.resolve(event)
        request = event.bind(
            plan=artifacts.plan,
            action_type=artifacts.action_type,
            active_release=artifacts.active_release,
        )
        return await self._coordinator.coordinate(
            request,
            observation_context=authenticated,
            active_release=artifacts.active_release,
        )

    async def publish_pending(self, *, now: datetime) -> ReconciliationOutboxEvent | None:
        """Publish one due durable event and acknowledge it only after broker success."""

        event = await self._ledger.claim_outbox(
            claimant_id=self._claimant_id,
            now=now,
            lease_until=now + self._lease_duration,
        )
        if event is None:
            return None
        try:
            await self._event_bus.publish(
                self._outbox_topic,
                event.result.reconciliation_id,
                event.model_dump(mode="json"),
            )
        except Exception:
            await self._ledger.release_outbox(
                event.result.reconciliation_id,
                event.idempotency_key,
                claimant_id=self._claimant_id,
                available_at=now + self._retry_delay,
            )
            raise
        await self._ledger.complete_outbox(
            event.result.reconciliation_id,
            event.idempotency_key,
            claimant_id=self._claimant_id,
            published_at=now,
        )
        return event

    async def drain_pending(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[ReconciliationOutboxEvent, ...]:
        """Bound restart replay so one busy aggregate set cannot monopolize the runtime."""

        if limit < 1 or limit > 1000:
            raise ValueError("reconciliation outbox drain limit MUST be between 1 and 1000")
        published: list[ReconciliationOutboxEvent] = []
        for _ in range(limit):
            event = await self.publish_pending(now=now)
            if event is None:
                break
            published.append(event)
        return tuple(published)


__all__ = [
    "EffectReconciliationBinder",
    "ObservationContextVerifier",
    "RECONCILIATION_OUTBOX_TOPIC",
    "RECONCILIATION_REQUEST_TOPIC",
    "ReconciliationArtifactResolver",
    "ResolvedReconciliationArtifacts",
]
