"""Bind handover chat proposals to server-verified goal state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fdai_operator_service.families.conversation.contracts import (
    ConversationProposal,
    ConversationProposalOutbox,
    OutboxReceipt,
)
from fdai_operator_service.families.conversation.factory import ConversationFamilyDependencies


class HandoverConversationBinder(Protocol):
    """Resolve an optional handover goal into a server-owned conversation target."""

    async def bind_conversation(self, proposal: ConversationProposal) -> ConversationProposal: ...


@dataclass(frozen=True, slots=True)
class HandoverBoundProposalOutbox:
    """Apply handover binding before the ordinary durable proposal boundary."""

    fallback: ConversationProposalOutbox
    binder: HandoverConversationBinder

    async def append(self, proposal: ConversationProposal) -> OutboxReceipt:
        return await self.fallback.append(await self.binder.bind_conversation(proposal))


def bind_handover_conversations(
    dependencies: ConversationFamilyDependencies,
    binder: HandoverConversationBinder | None,
) -> ConversationFamilyDependencies:
    """Decorate only the proposal outbox when both required ports are available."""
    if binder is None or dependencies.outbox is None:
        return dependencies
    return ConversationFamilyDependencies(
        authorizer=dependencies.authorizer,
        projections=dependencies.projections,
        outbox=HandoverBoundProposalOutbox(dependencies.outbox, binder),
        streams=dependencies.streams,
    )


__all__ = [
    "HandoverBoundProposalOutbox",
    "HandoverConversationBinder",
    "bind_handover_conversations",
]
