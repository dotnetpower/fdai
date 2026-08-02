"""Durable ticket-effect coordination for confirmed Console incidents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fdai.core.incident.intent import IncidentCreationProposal
from fdai.core.incident.registry import incident_id_for
from fdai.shared.providers.state_store import StateStore

from .console_action_dispatch import (
    ConsoleActionDispatch,
    ConsoleActionDispatcher,
    ConsoleActionDispatchState,
    console_action_intent_digest,
)


@dataclass(frozen=True, slots=True)
class ConsoleIncidentTicketCoordinator:
    dispatcher: ConsoleActionDispatcher
    state_store: StateStore
    event_topic: str
    batch_size: int
    blocked_retention_seconds: int = 86_400

    def __post_init__(self) -> None:
        if self.batch_size < 1 or self.blocked_retention_seconds < 1:
            raise ValueError("incident ticket recovery bounds MUST be positive")

    async def prepare(
        self,
        proposal: IncidentCreationProposal,
        actor_oid: str,
        session_id: str,
    ) -> None:
        incident_id = str(incident_id_for(proposal.correlation_keys))
        payload = _ticket_payload(
            incident_id=incident_id,
            actor_oid=actor_oid,
            session_id=session_id,
        )
        resource_id = str(payload["resource_id"])
        await self.dispatcher.prepare_blocked(
            idempotency_key=str(payload["idempotency_key"]),
            intent_digest=console_action_intent_digest(
                topic=self.event_topic,
                partition_key=resource_id,
                payload=payload,
            ),
            topic=self.event_topic,
            partition_key=resource_id,
            payload=payload,
            correlation_id=str(payload["correlation_id"]),
            actor_oid=actor_oid,
        )

    async def publish(
        self,
        *,
        incident_id: str,
        actor_oid: str,
        session_id: str | None,
    ) -> ConsoleActionDispatch:
        payload = _ticket_payload(
            incident_id=incident_id,
            actor_oid=actor_oid,
            session_id=session_id,
        )
        return await self.dispatcher.activate_and_deliver_key(str(payload["idempotency_key"]))

    async def reconcile(self) -> int:
        transitions = await self.state_store.read_incident_transitions()
        opened_ids = {
            str(row.get("incident_id"))
            for row in transitions
            if row.get("kind") == "incident.open" and row.get("incident_id")
        }
        activated = 0
        matched = 0
        abandoned = 0
        now = self.dispatcher.clock()
        for record in await self.dispatcher.store.blocked(limit=self.dispatcher.store.scan_limit):
            incident_id = _ticket_incident_id(record.payload)
            if incident_id is not None and incident_id in opened_ids:
                if matched >= self.batch_size:
                    continue
                matched += 1
                result = await self.dispatcher.activate_and_deliver(record.dispatch_id)
                activated += int(result.state is ConsoleActionDispatchState.PUBLISHED)
                continue
            if (
                abandoned < self.batch_size
                and record.accepted_at + timedelta(seconds=self.blocked_retention_seconds) <= now
            ):
                abandon_result = await self.dispatcher.store.abandon(
                    record.dispatch_id,
                    now=now,
                    reason="incident_not_opened_before_retention_expiry",
                )
                abandoned += int(
                    abandon_result is not None
                    and abandon_result.state is ConsoleActionDispatchState.ABANDONED
                )
        return activated


def _ticket_incident_id(payload: Mapping[str, object]) -> str | None:
    params = payload.get("params")
    if payload.get("action_type") != "tool.open-incident-ticket" or not isinstance(params, Mapping):
        return None
    incident_id = params.get("incident_id")
    return incident_id if isinstance(incident_id, str) else None


def _ticket_payload(
    *,
    incident_id: str,
    actor_oid: str,
    session_id: str | None,
) -> dict[str, Any]:
    resource_id = f"incident:{incident_id}"
    correlation_id = f"incident-ticket:{incident_id}"
    return {
        "idempotency_key": correlation_id,
        "correlation_id": correlation_id,
        "initiator_principal": actor_oid,
        "operator_initiated": True,
        "action_type": "tool.open-incident-ticket",
        "resource_id": resource_id,
        "event_type": "operator_request",
        "params": {
            "incident_id": incident_id,
            "ticket_provider": "github",
            "summary": f"FDAI incident {incident_id}",
            "description": "Created from a confirmed operator conversation.",
            "labels": ["fdai-incident"],
        },
        "session_id": session_id,
    }


__all__ = ["ConsoleIncidentTicketCoordinator"]
