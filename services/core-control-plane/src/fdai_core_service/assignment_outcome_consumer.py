"""Deliver review-only ownership artifacts after an audit-sealed canonical case result."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.core.human_assignment.ownership_coordination import AssignmentOwnershipCoordinator
from fdai.core.stewardship import StewardshipMap
from fdai.shared.providers.event_bus import EventBus, subscription
from fdai.shared.providers.state_store import StateStore
from fdai_service_contracts.assignment_transport import (
    ASSIGNMENT_PROJECTION_TOPIC,
    AssignmentAgentDecision,
)


@dataclass(frozen=True, slots=True)
class AssignmentOutcomeConsumer:
    """An artifact delivery adapter, not an approver, map applier, or IAM executor.

    Re-read the Core-only command result before delivery. A transport identity or claimed Saga
    producer cannot create a case or substitute a different proposal. Existing publisher
    idempotency repairs uncertain delivery; only a separately verified merge changes ownership.
    """

    store: StateStore
    ownership: AssignmentOwnershipCoordinator | None = None
    base: StewardshipMap | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def run(self, *, bus: EventBus, stop: asyncio.Event) -> None:
        """Consume the Saga-owned result stream; I/O failure preserves the broker offset."""
        async with subscription(
            bus, "object.audit-entry", "assignment-artifact-delivery-v1"
        ) as stream:
            async for envelope in stream:
                if stop.is_set():
                    return
                if envelope.payload.get("kind") != "human_assignment":
                    continue
                try:
                    await self.deliver(envelope.payload, bus=bus)
                except ValueError:
                    await bus.dead_letter(
                        "object.audit-entry",
                        "invalid-assignment-artifact",
                        {"reason": "invalid_assignment_artifact", "execution_authority": False},
                        "invalid_assignment_artifact",
                    )

    async def deliver(self, payload: Mapping[str, Any], *, bus: EventBus) -> None:
        """Resolve a sealed result to a review-only PR or explicit unavailable disposition."""
        if payload.get("producer_principal") != "Saga":
            raise ValueError("assignment artifact delivery requires a Saga-owned seal")
        decision = AssignmentAgentDecision.model_validate(payload.get("assignment"))
        if payload.get("correlation_id") != decision.notice.case_id:
            raise ValueError("assignment artifact correlation is invalid")
        result = decision.result
        if result is None or payload.get("audited_topic") != "object.state-snapshot":
            return
        stored = await self.store.read_state(
            f"human_assignment:command-result:{decision.notice.proposal_id}"
        )
        if stored != result.model_dump(mode="json", exclude_none=True):
            raise ValueError("assignment artifact result does not match canonical state")
        status, pr_ref = "not_required", None
        if result.state == "approved":
            if self.ownership is None or self.base is None:
                status = "unavailable"
            else:
                case = await self.ownership.cases.get_case(result.case_id)
                if case.state.value in {"approved", "ownership_pr_open"}:
                    try:
                        _case, proposal = await self.ownership.open_proposal(
                            case_id=case.case_id,
                            expected_revision=case.revision,
                            actor_ref="assignment-artifact-delivery",
                            base=self.base,
                            now=self.clock(),
                        )
                    except ValueError:
                        status = "held"
                    else:
                        status, pr_ref = "pr_open", proposal.pr_ref
                else:
                    status = "superseded_or_converged"
        receipt = {
            "proposal_id": decision.notice.proposal_id,
            "request_digest": decision.notice.proposal_digest,
            "case_id": result.case_id,
            "status": status,
            "pr_ref": pr_ref,
            "execution_authority": False,
        }
        await self.store.write_state_with_audit_if_absent(
            f"human_assignment:artifact-receipt:{decision.notice.proposal_id}:{status}",
            receipt,
            {"actor": "Saga", "action_kind": "human.assignment.artifact_observed", **receipt},
        )
        await bus.publish(
            ASSIGNMENT_PROJECTION_TOPIC,
            decision.notice.case_id,
            {"kind": "assignment_artifact", "schema_version": "1.0.0", **receipt},
        )


__all__ = ["AssignmentOutcomeConsumer"]
