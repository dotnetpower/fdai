"""Explicit cross-channel links between independently approved senders."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.core.conversation.channel_access import (
    ChannelPairingStore,
    ChannelSenderKey,
    PairingApprovalAuthorizer,
)


@dataclass(frozen=True, slots=True)
class CrossChannelIdentityLink:
    link_id: str
    principal_id: str
    first: ChannelSenderKey
    second: ChannelSenderKey
    approved_by: str
    created_at: datetime


class CrossChannelIdentityLinkStore(Protocol):
    async def create(self, link: CrossChannelIdentityLink) -> bool: ...

    async def get(self, link_id: str) -> CrossChannelIdentityLink | None: ...

    async def list_for_principal(
        self,
        principal_id: str,
    ) -> Sequence[CrossChannelIdentityLink]: ...


class CrossChannelIdentityLinkError(ValueError):
    """An explicit identity link failed closed."""


class InMemoryCrossChannelIdentityLinkStore:
    def __init__(self) -> None:
        self._links: dict[str, CrossChannelIdentityLink] = {}

    async def create(self, link: CrossChannelIdentityLink) -> bool:
        if link.link_id in self._links:
            return False
        self._links[link.link_id] = link
        return True

    async def get(self, link_id: str) -> CrossChannelIdentityLink | None:
        return self._links.get(link_id)

    async def list_for_principal(
        self,
        principal_id: str,
    ) -> Sequence[CrossChannelIdentityLink]:
        return tuple(link for link in self._links.values() if link.principal_id == principal_id)


class CrossChannelIdentityLinkService:
    """Record relations without changing either sender-to-principal mapping."""

    def __init__(
        self,
        *,
        pairings: ChannelPairingStore,
        links: CrossChannelIdentityLinkStore,
        authorizer: PairingApprovalAuthorizer,
    ) -> None:
        self._pairings = pairings
        self._links = links
        self._authorizer = authorizer

    async def link(
        self,
        first: ChannelSenderKey,
        second: ChannelSenderKey,
        *,
        principal_id: str,
        actor_id: str,
        at: datetime,
    ) -> CrossChannelIdentityLink:
        if not principal_id or not actor_id:
            raise CrossChannelIdentityLinkError("identity link principal and actor are required")
        if first.channel_kind is second.channel_kind:
            raise CrossChannelIdentityLinkError("identity link MUST cross channel kinds")
        if not self._authorizer.can_approve_pairing(actor_id):
            raise CrossChannelIdentityLinkError(
                "actor is not authorized to link channel identities"
            )
        if actor_id.strip().casefold() == principal_id.strip().casefold():
            raise CrossChannelIdentityLinkError("identity link requires a distinct approver")
        first_pairing = await self._pairings.get(first)
        second_pairing = await self._pairings.get(second)
        mapped_principals = {
            request.approved_principal_id
            for request in (first_pairing, second_pairing)
            if request is not None and request.approved
        }
        if len(mapped_principals) > 1:
            raise CrossChannelIdentityLinkError(
                "identity link cannot merge distinct FDAI principals"
            )
        if mapped_principals != {principal_id} or first_pairing is None or second_pairing is None:
            raise CrossChannelIdentityLinkError(
                "both channel senders MUST be independently approved for the principal"
            )
        ordered = sorted((first, second), key=_sender_sort_key)
        link_id = _link_id(principal_id, ordered[0], ordered[1])
        link = CrossChannelIdentityLink(
            link_id=link_id,
            principal_id=principal_id,
            first=ordered[0],
            second=ordered[1],
            approved_by=actor_id,
            created_at=at,
        )
        if not await self._links.create(link):
            existing = await self._links.get(link_id)
            if existing is None:
                raise CrossChannelIdentityLinkError("identity link write conflicted")
            return existing
        return link


def _sender_sort_key(sender: ChannelSenderKey) -> tuple[str, str, str]:
    return sender.channel_kind.value, sender.channel_id, sender.sender_id


def _link_id(
    principal_id: str,
    first: ChannelSenderKey,
    second: ChannelSenderKey,
) -> str:
    raw = "\0".join((principal_id, *_sender_sort_key(first), *_sender_sort_key(second)))
    return "channel-link:" + hashlib.sha256(raw.encode()).hexdigest()[:40]


__all__ = [
    "CrossChannelIdentityLink",
    "CrossChannelIdentityLinkError",
    "CrossChannelIdentityLinkService",
    "CrossChannelIdentityLinkStore",
    "InMemoryCrossChannelIdentityLinkStore",
]
