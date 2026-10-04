"""Publish revalidated observer recommendations without direct Operator database access."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Protocol

from fdai_service_contracts.cluster_connector import connector_time
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.observer_deployment import (
    OBSERVER_PROPOSAL_TOPIC,
    ObserverDeploymentProposal,
    ObserverProposalProjection,
)
from pydantic import TypeAdapter

from fdai.delivery.kubernetes_connector_proposals import (
    OBSERVER_PROPOSAL_PREFIX,
    ObserverDeploymentProposalService,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.notifications.base import (
    Link,
    NotificationMessage,
    Severity,
    TrustTier,
)
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

_OBSERVER_PROPOSAL_NOTIFICATION_CATEGORY = "operational_alert"
_OBSERVER_PROPOSAL_CONSOLE_URL = "/environment-deployment"


class ObserverProposalNotificationDispatcher(Protocol):
    """Existing notification-router boundary used for informational proposal alerts."""

    async def dispatch(self, message: NotificationMessage) -> object: ...


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


def observer_proposal_notification_audit_id(
    proposal: ObserverDeploymentProposal,
    *,
    principal_ref: str,
) -> str:
    """Return the stable durable outbox identity for one principal/proposal pair."""

    principal = _bounded_principal_ref(principal_ref)
    principal_digest = canonical_digest({"principal_ref": principal})
    return f"observer-deployment-proposal:{proposal.proposal_digest}:{principal_digest}"


def observer_proposal_notification_message(
    proposal: ObserverDeploymentProposal,
    *,
    principal_ref: str,
    console_url: str = _OBSERVER_PROPOSAL_CONSOLE_URL,
) -> NotificationMessage:
    """Render an informational ChatOps notification without approval or execution controls."""

    principal = _bounded_principal_ref(principal_ref)
    if not console_url or len(console_url) > 512:
        raise ValueError("observer proposal notification console_url MUST be bounded")
    target_digest = canonical_digest({"target_ref": proposal.target_ref})
    recommended = proposal.recommended
    candidate_line = (
        f"Recommended inspection candidate: `{recommended.method}` with "
        f"`{recommended.egress}` egress."
        if recommended is not None
        else "No deployment method has complete evidence yet."
    )
    title = f"Observer deployment proposal: {proposal.status}"
    body = "\n".join(
        (
            f"Observer deployment proposal `{proposal.proposal_digest}` is `{proposal.status}`.",
            candidate_line,
            (
                "This notification is informational only: it does not approve, install, "
                "execute, or grant deployment authority."
            ),
            f"Evidence expires at `{proposal.expires_at.isoformat()}`.",
        )
    )
    return NotificationMessage(
        category=_OBSERVER_PROPOSAL_NOTIFICATION_CATEGORY,
        trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
        correlation_id=proposal.proposal_digest,
        audit_id=observer_proposal_notification_audit_id(
            proposal,
            principal_ref=principal,
        ),
        title=title,
        body_markdown=body,
        severity=Severity.INFO,
        links=(Link(label="View observer proposals", url=console_url),),
        metadata={
            "proposal_digest": proposal.proposal_digest,
            "proposal_status": proposal.status,
            "target_digest": target_digest,
            "principal_digest": canonical_digest({"principal_ref": principal}),
            "approval_required": str(proposal.approval_required).lower(),
            "execution_authority": str(proposal.execution_authority).lower(),
            "notification_kind": "observer_deployment_proposal",
        },
    )


async def publish_observer_proposal_notification(
    *,
    proposal: ObserverDeploymentProposal,
    dispatcher: ObserverProposalNotificationDispatcher,
    principal_ref: str,
    console_url: str = _OBSERVER_PROPOSAL_CONSOLE_URL,
) -> object:
    """Publish one proposal through the configured notification outbox/router boundary."""

    return await dispatcher.dispatch(
        observer_proposal_notification_message(
            proposal,
            principal_ref=principal_ref,
            console_url=console_url,
        )
    )


async def publish_discovered_proposals(
    *,
    targets: tuple[str, ...],
    service: ObserverDeploymentProposalService,
    store: StateStore,
    identity: WorkloadIdentity,
    notification_dispatcher: ObserverProposalNotificationDispatcher | None = None,
    notification_http_client: Any = None,
    notification_principal_ref: str = "inventory-subscription-discovery",
    notification_store_dsn: str | None = None,
) -> None:
    """Use the existing deployment transport and its physical-topic mapping; never create topics."""
    import asyncio
    import os
    from datetime import UTC

    from fdai.delivery.event_bus_multiplex import MultiplexedEventBus
    from fdai.delivery.inventory_change_acceleration import build_job_event_bus

    if notification_dispatcher is None and notification_store_dsn:
        from fdai.delivery.persistence import (
            PostgresNotificationDeliveryStore,
            PostgresStateStoreConfig,
        )
        from fdai.runtime.delivery import _build_notification_router

        notification_dispatcher = _build_notification_router(
            store,
            http_client=notification_http_client,
            notification_delivery_store=PostgresNotificationDeliveryStore(
                config=PostgresStateStoreConfig(dsn=notification_store_dsn)
            ),
        )

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
                if notification_dispatcher is not None:
                    proposal = await service.current(target)
                    if proposal is not None:
                        await publish_observer_proposal_notification(
                            proposal=proposal,
                            dispatcher=notification_dispatcher,
                            principal_ref=notification_principal_ref,
                        )
    finally:
        async with asyncio.timeout(5):
            await raw.close()


def _bounded_principal_ref(value: str) -> str:
    principal = value.strip()
    if not 1 <= len(principal) <= 256:
        raise ValueError("observer proposal notification principal_ref MUST be bounded")
    return principal
