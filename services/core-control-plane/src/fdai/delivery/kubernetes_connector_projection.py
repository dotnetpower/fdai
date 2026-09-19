"""Publish revalidated observer recommendations without direct Operator database access."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from fdai_service_contracts.cluster_connector import connector_time
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.observer_deployment import (
    OBSERVER_PROPOSAL_TOPIC,
    ObserverProposalProjection,
)
from pydantic import TypeAdapter

from fdai.delivery.kubernetes_connector_proposals import (
    OBSERVER_PROPOSAL_PREFIX,
    ObserverDeploymentProposalService,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity


async def publish_observer_proposal(
    *,
    target_ref: str,
    service: ObserverDeploymentProposalService,
    store: StateStore,
    bus: EventBus,
    now: Callable[[], datetime],
) -> bool:
    """Publish from the durable checkpoint on every refresh, preserving at-least-once semantics."""
    record = await store.read_state(
        OBSERVER_PROPOSAL_PREFIX + canonical_digest({"target_ref": target_ref})
    )
    if record is None:
        return False
    revision = record.get("revision")
    if type(revision) is not int or not 1 <= revision <= 2**63 - 1:
        raise ValueError("observer proposal publication checkpoint is invalid")
    try:
        proposal = await service.current(target_ref)
    except ValueError:
        proposal = None
    published_at = connector_time(now())
    confirmed = await store.read_state(
        OBSERVER_PROPOSAL_PREFIX + canonical_digest({"target_ref": target_ref})
    )
    if confirmed != record:
        raise ValueError("observer proposal changed during publication")
    if proposal is not None and record.get("proposal") != proposal.model_dump(mode="json"):
        raise ValueError("observer proposal source revision changed")
    if proposal is not None and published_at >= proposal.expires_at:
        proposal = None
    clock = TypeAdapter(datetime)
    value = {
        "schema_version": "1.0.0",
        "target_ref": target_ref,
        "source_revision": revision,
        "published_at": clock.dump_python(published_at, mode="json"),
        "expires_at": clock.dump_python(
            min(published_at + timedelta(minutes=1), proposal.expires_at)
            if proposal
            else published_at + timedelta(minutes=1),
            mode="json",
        ),
        "proposal": proposal.model_dump(mode="json") if proposal else None,
        "state": "current" if proposal else "unavailable",
        "reason": "current_evidence" if proposal else "evidence_unavailable",
        "execution_authority": False,
    }
    projection = ObserverProposalProjection.model_validate(
        {**value, "projection_digest": canonical_digest(value)}
    )
    await bus.publish(
        OBSERVER_PROPOSAL_TOPIC,
        canonical_digest({"target_ref": target_ref}),
        projection.model_dump(mode="json"),
    )
    return True


async def publish_discovered_proposals(
    *,
    targets: tuple[str, ...],
    service: ObserverDeploymentProposalService,
    store: StateStore,
    identity: WorkloadIdentity,
) -> None:
    """Use the existing deployment transport and its physical-topic mapping; never create topics."""
    import asyncio
    import os
    from datetime import UTC

    from fdai.delivery.event_bus_multiplex import MultiplexedEventBus
    from fdai.delivery.inventory_change_acceleration import build_job_event_bus

    raw, _ = build_job_event_bus(identity)
    physical = os.environ.get("FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC", "").strip()
    bus: EventBus = (
        MultiplexedEventBus(raw, frozenset({OBSERVER_PROPOSAL_TOPIC}), physical)
        if physical
        else raw
    )
    try:
        async with asyncio.timeout(10):
            for target in targets:
                await publish_observer_proposal(
                    target_ref=target,
                    service=service,
                    store=store,
                    bus=bus,
                    now=lambda: datetime.now(UTC),
                )
    finally:
        async with asyncio.timeout(5):
            await raw.close()
