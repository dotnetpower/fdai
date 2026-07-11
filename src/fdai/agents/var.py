"""Var - Approver (Wave 3 + Wave 6 behavior).

Var carries the HIL approval principal (Wave 3) and delivers admin
security notifications through the ChatOps admin channel (Wave 6).
Every card is deduped by (initiator, action_type) within a rolling
window and the last-seen counter is incremented on repeat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fdai.agents._framework.adapters import AdminCard, InMemoryAdminChannel
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    capped_list,
    mentioned,
)
from fdai.agents._framework.pantheon import _VAR


@dataclass
class PendingHilTicket:
    correlation_id: str
    action_type: str
    resource_id: str | None
    quorum_required: int
    initiator_principal: str | None = None
    approvers: list[str] = field(default_factory=list)
    rejected: bool = False


def _evict_oldest_ticket(mapping: dict[Any, Any], cap: int, *, keep: Any = None) -> None:
    """Bound ``mapping`` to ``cap`` entries, dropping oldest-first (insertion
    order), never evicting ``keep`` (the entry just written)."""
    while len(mapping) > cap:
        for key in mapping:
            if key != keep:
                del mapping[key]
                break
        else:  # only `keep` remains
            break


class Var(Agent):
    """Wave-3 HIL approval + Wave-6 admin channel delivery."""

    #: Bound the in-memory maps so a long-lived approver cannot leak one entry
    #: per never-decided HIL item / admin card forever (oldest-first eviction).
    _MAX_PENDING = 5_000
    _MAX_CARDS = 5_000

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        admin_channel: InMemoryAdminChannel | None = None,
    ) -> None:
        super().__init__(spec=_VAR)
        self.bus = bus
        self.admin_channel = admin_channel or InMemoryAdminChannel()
        self._pending: dict[str, PendingHilTicket] = {}
        # (initiator, action_type) -> AdminCard for dedup counter update
        self._last_cards: dict[tuple[str, str], AdminCard] = {}

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    # ---- typed port ----------------------------------------------------

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic != "object.action-run":
            return
        if payload.get("state") != "hil_pending":
            return
        correlation = str(payload.get("correlation_id", ""))
        if not correlation or correlation in self._pending:
            return
        # Clamp quorum to a floor of 1: a forged / malformed action-run must
        # never yield a zero-or-negative quorum that would approve with no
        # approver (the two-approver requirement for irreversible actions is
        # set by Forseti; this only prevents a downgrade below one).
        quorum = max(1, int(payload.get("quorum_required", 1)))
        self._pending[correlation] = PendingHilTicket(
            correlation_id=correlation,
            action_type=str(payload.get("action_type", "")),
            resource_id=payload.get("resource_id"),
            quorum_required=quorum,
            initiator_principal=payload.get("initiator_principal"),
        )
        self.record_behavior("ticket_pending")
        _evict_oldest_ticket(self._pending, self._MAX_PENDING, keep=correlation)

    # ---- HIL decision --------------------------------------------------

    async def decide(
        self,
        correlation_id: str,
        *,
        approver: str,
        decision: str,
    ) -> dict[str, Any] | None:
        ticket = self._pending.get(correlation_id)
        if ticket is None:
            return None
        if decision == "reject":
            ticket.rejected = True
        elif decision == "approve":
            # No self-approval: the operator who initiated the action can never
            # approve it (approval and initiation are distinct principals - a
            # pantheon safety invariant, agent-pantheon.md). Enforced here even
            # if the entry RBAC gate was bypassed upstream. Compare trimmed so
            # a whitespace-padded principal cannot slip past, and reject a blank
            # approver outright.
            approver_norm = approver.strip()
            if not approver_norm:
                raise ValueError(f"approver MUST be a non-empty principal on {correlation_id!r}")
            initiator_norm = (ticket.initiator_principal or "").strip()
            if initiator_norm and approver_norm == initiator_norm:
                self.record_behavior("self_approval_blocked")
                raise ValueError(
                    f"principal {approver_norm!r} cannot approve an action it initiated "
                    f"({correlation_id!r}): no self-approval"
                )
            if approver_norm in ticket.approvers:
                self.record_behavior("double_approval_blocked")
                raise ValueError(
                    f"principal {approver_norm!r} cannot self-approve twice on {correlation_id!r}"
                )
            ticket.approvers.append(approver_norm)
        else:
            raise ValueError(f"unknown decision {decision!r}")

        if ticket.rejected or len(ticket.approvers) >= ticket.quorum_required:
            final = "rejected" if ticket.rejected else "approved"
            self.record_behavior(final)
            approval = {
                "producer_principal": "Var",
                "correlation_id": correlation_id,
                "action_type": ticket.action_type,
                "state": final,
                "approvers": list(ticket.approvers),
            }
            if self.bus is not None:
                await self.bus.publish("Var", "object.approval", approval)
            del self._pending[correlation_id]
            return approval
        return None

    def pending_tickets(self) -> tuple[PendingHilTicket, ...]:
        return tuple(self._pending.values())

    # ---- admin notification (Wave 6) ----------------------------------

    async def deliver_admin_card(self, payload: dict[str, Any]) -> AdminCard:
        """Deliver an admin ChatOps card. Dedups by (initiator, action)."""
        initiator = str(payload.get("initiator_principal", ""))
        action = str(payload.get("attempted_action", ""))
        severity = str(payload.get("severity", "high"))
        counter = int(payload.get("counter", 1))
        key = (initiator, action)
        existing = self._last_cards.get(key)
        if existing is not None:
            # Repeat: update counter in place rather than post a new card.
            new_card = AdminCard(
                severity=severity,
                initiator_principal=initiator,
                attempted_action=action,
                counter=counter,
            )
            self._last_cards[key] = new_card
            # Update the last delivered card's counter too
            self.admin_channel.cards[-1] = new_card
            return new_card
        card = AdminCard(
            severity=severity,
            initiator_principal=initiator,
            attempted_action=action,
            counter=counter,
        )
        self.admin_channel.send(card)
        self._last_cards[key] = card
        _evict_oldest_ticket(self._last_cards, self._MAX_CARDS, keep=key)
        return card

    # ---- conversational port -------------------------------------------

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        pending = self._pending
        facts = {
            **capability_facts(self.spec),
            "pending_hil": len(pending),
            "correlations": capped_list(sorted(pending)),
        }
        corr = mentioned(question, pending)
        if corr:
            ticket = pending[corr[0]]
            facts.update(
                {
                    "correlation_id": ticket.correlation_id,
                    "action_type": ticket.action_type,
                    "quorum_required": ticket.quorum_required,
                    "approvals": len(ticket.approvers),
                    "rejected": ticket.rejected,
                }
            )
            answer = (
                f"HIL {ticket.correlation_id!r} ({ticket.action_type}): "
                f"{len(ticket.approvers)}/{ticket.quorum_required} approval(s)"
                + (", rejected" if ticket.rejected else "")
                + "."
            )
            return IntrospectionResult(answer=answer, facts=facts)
        if not pending:
            answer = (
                "No HIL approvals pending; I hold the human approval queue "
                "(distinct principal from the executor)."
            )
        else:
            answer = f"{len(pending)} HIL approval(s) pending: {', '.join(sorted(pending))}."
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Var", "PendingHilTicket"]
