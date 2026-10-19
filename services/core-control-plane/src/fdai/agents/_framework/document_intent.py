"""Owned document-intent transitions on existing typed topics; no direct cross-agent calls."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Protocol

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import Handler, PantheonBus
from fdai.agents._framework.var_decisions import PendingHilTicket
from fdai.agents._framework.var_pending_durability import checkpoint_pending_ticket
from fdai.agents.var import Var
from fdai.core.ontology_platform.document_intent import (
    INTENT_KIND,
    DocumentIntentDiff,
    DocumentIntentEvent,
)


class DocumentIntentOperations(Protocol):
    async def authorize_review(self, reviewer: str, digest: str) -> bool: ...
    async def active_revision(self, digest: str) -> int | None: ...
    async def review(self, digest: str) -> DocumentIntentDiff: ...
    async def transition(self, digest: str, phase: str, receipt: Mapping[str, Any]) -> None: ...
    async def apply(self, digest: str, correlation: str) -> DocumentIntentEvent: ...
    async def observe(self, event: DocumentIntentEvent) -> DocumentIntentEvent: ...
    async def rollback(self, event: DocumentIntentEvent) -> DocumentIntentEvent: ...
    async def pending(self, owner: str) -> tuple[DocumentIntentEvent, ...]: ...
    async def published(self, event: DocumentIntentEvent) -> None: ...


def owned_document_intent_handler(
    agent: Agent, operations: DocumentIntentOperations | None, fallback: Handler
) -> Handler:
    """Each owner publishes its own object; sealed approval requires real durable Saga audit."""
    if operations is not None and isinstance(agent, Var):
        agent.bind_document_intent_review_authorizer(
            lambda reviewer, digest: operations.authorize_review(reviewer, digest)
        )

    async def publish(event: DocumentIntentEvent) -> None:
        if agent.bus is None or operations is None:
            raise RuntimeError("document intent dependencies are unavailable")
        await operations.transition(event.intent_digest, event.phase, event.model_dump(mode="json"))
        await agent.bus.publish(agent.spec.name, event.topic, event.model_dump(mode="json"))
        await operations.published(event)

    async def handle(topic: str, payload: dict[str, Any]) -> None:
        if payload.get("kind") != INTENT_KIND:
            await fallback(topic, payload)
            return
        name = agent.spec.name
        if name == "Thor":
            return
        if operations is None or agent.bus is None:
            raise RuntimeError("document intent owner is unavailable")
        async with asyncio.timeout(60):
            if name == "Saga":
                if not getattr(agent, "durable_audit", False):
                    raise RuntimeError("document intent requires durable Saga audit")
                await fallback(topic, payload)
                if topic == "object.approval":
                    if payload.get("producer_principal") != "Var":
                        raise PermissionError("intent approval requires Var")
                    if payload.get("state") != "approved":
                        return
                    params = payload.get("params")
                    if not isinstance(params, dict) or set(params) != {"intent_digest"}:
                        raise ValueError("intent approval is not an exact diff reference")
                    event = DocumentIntentEvent.create(
                        "approved_sealed", params["intent_digest"], payload["correlation_id"]
                    )
                    await publish(event)
                    return
            elif topic == "object.approval":
                return
            event = DocumentIntentEvent.model_validate(payload)
            if topic != event.topic:
                raise PermissionError("intent event arrived on a different owned topic")
            if name == "Saga":
                phase = {
                    "verdict": "verdict_sealed",
                    "verified": "verified_sealed",
                }.get(event.phase)
                if phase is not None:
                    await publish(
                        DocumentIntentEvent.create(
                            phase,
                            event.intent_digest,
                            event.correlation_id,
                            outcome=event.outcome,
                            applied_revision=event.applied_revision,
                        )
                    )
                return
            next_phase = {
                ("Muninn", "source"): "ready",
                ("Norns", "ready"): "candidate",
                ("Mimir", "candidate"): "reviewed",
                ("Forseti", "reviewed"): "verdict",
            }.get((name, event.phase))
            if next_phase is not None:
                if event.outcome != "pending":
                    return
                if name == "Muninn" and event.phase == "source":
                    revision = await operations.active_revision(event.intent_digest)
                    if revision is not None:
                        await publish(
                            DocumentIntentEvent.create(
                                "applied",
                                event.intent_digest,
                                event.correlation_id,
                                applied_revision=revision,
                            )
                        )
                        return
                await operations.review(event.intent_digest)
                await publish(
                    DocumentIntentEvent.create(
                        next_phase, event.intent_digest, event.correlation_id
                    )
                )
            elif name == "Var" and event.phase == "verdict_sealed":
                if event.outcome != "pending" or not isinstance(agent, Var):
                    return
                diff = await operations.review(event.intent_digest)
                ticket = PendingHilTicket(
                    correlation_id=event.correlation_id,
                    action_type="document.review-intent-diff",
                    resource_id="document-intent:" + event.intent_digest[7:],
                    quorum_required=1,
                    initiator_principal=diff.requester_ref,
                    kind=INTENT_KIND,
                    params={"intent_digest": event.intent_digest},
                    idempotency_key=event.idempotency_key,
                )
                if agent._state_store is None:
                    raise RuntimeError("intent approval requires durable Var state")
                await checkpoint_pending_ticket(agent._state_store, ticket)
                agent._pending[event.correlation_id] = ticket
            elif name == "Muninn" and event.phase == "approved_sealed":
                try:
                    result = await operations.apply(event.intent_digest, event.correlation_id)
                except (PermissionError, ValueError):
                    result = DocumentIntentEvent.create(
                        "held", event.intent_digest, event.correlation_id, outcome="mismatched"
                    )
                await publish(result)
            elif name == "Heimdall" and event.phase == "applied":
                await publish(await operations.observe(event))
            elif (
                name == "Vidar"
                and event.phase == "verified_sealed"
                and event.outcome == "mismatched"
            ):
                try:
                    result = await operations.rollback(event)
                except (PermissionError, ValueError):
                    result = DocumentIntentEvent.create(
                        "recovery_held",
                        event.intent_digest,
                        event.correlation_id,
                        outcome="mismatched",
                        applied_revision=event.applied_revision,
                    )
                await publish(result)
            elif name == "Forseti" and event.phase in {"held", "recovery_held"}:
                await publish(
                    DocumentIntentEvent.create(
                        "arbitration_requested",
                        event.intent_digest,
                        event.correlation_id,
                        outcome="mismatched",
                        applied_revision=event.applied_revision,
                    )
                )
            elif name == "Odin" and event.phase == "arbitration_requested":
                await publish(
                    DocumentIntentEvent.create(
                        "arbitrated",
                        event.intent_digest,
                        event.correlation_id,
                        outcome="mismatched",
                        applied_revision=event.applied_revision,
                    )
                )

    return handle


async def recover_document_intent_publications(
    agents: Mapping[str, Agent], operations: DocumentIntentOperations
) -> int:
    count = 0
    for owner, agent in agents.items():
        if agent.bus is None:
            continue
        for event in await operations.pending(owner):
            await agent.bus.publish(owner, event.topic, event.model_dump(mode="json"))
            await operations.published(event)
            count += 1
    return count


async def publish_document_intent_source(
    bus: PantheonBus, *, intent_digest: str, correlation_id: str
) -> None:
    """Source-adapter ingress for an already authenticated, retained governed envelope."""
    event = DocumentIntentEvent.create("source", intent_digest, correlation_id)
    await bus.publish(
        "Huginn",
        event.topic,
        {**event.model_dump(mode="json"), "event_type": "document.intent.projection.v1"},
    )
