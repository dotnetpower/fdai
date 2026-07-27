"""Channel sender pairing, allowlisting, and FDAI principal resolution."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from fdai.core.conversation.session import Principal
from fdai.shared.providers.conversation_channel import (
    ConversationChannelKind,
    InboundTurn,
)
from fdai.shared.telemetry.transitions import (
    RoutingTransition,
    RoutingTransitionSink,
    default_transition_emitter,
    emit_transition_safely,
)


class ChannelAccessMode(StrEnum):
    DISABLED = "disabled"
    ALLOWLIST = "allowlist"
    PAIRING = "pairing"


@dataclass(frozen=True, slots=True)
class ChannelSenderKey:
    channel_kind: ConversationChannelKind
    channel_id: str
    sender_id: str


@dataclass(frozen=True, slots=True)
class PairingRequest:
    sender: ChannelSenderKey
    code_digest: str
    created_at: datetime
    expires_at: datetime
    approved_principal_id: str | None = None
    approved_at: datetime | None = None

    @property
    def approved(self) -> bool:
        return self.approved_principal_id is not None


@dataclass(frozen=True, slots=True)
class PairingChallenge:
    code: str
    expires_at: datetime


class PairingCreateResult(StrEnum):
    CREATED = "created"
    ALREADY_PENDING = "already_pending"
    ALREADY_APPROVED = "already_approved"
    CAP_REACHED = "cap_reached"


class ChannelPairingStore(Protocol):
    async def get(self, sender: ChannelSenderKey) -> PairingRequest | None: ...

    async def create_pending(
        self,
        request: PairingRequest,
        *,
        max_pending: int,
    ) -> PairingCreateResult: ...

    async def approve_pending(
        self,
        sender: ChannelSenderKey,
        *,
        code_digest: str,
        principal_id: str,
        at: datetime,
    ) -> PairingRequest | None: ...

    async def cancel_pending(
        self,
        sender: ChannelSenderKey,
        *,
        code_digest: str,
    ) -> bool: ...


class ChannelIdentityDirectory(Protocol):
    async def principal_for_id(self, principal_id: str) -> Principal | None: ...


class PairingApprovalAuthorizer(Protocol):
    def can_approve_pairing(self, actor_id: str) -> bool: ...


class ChannelAccessError(ValueError):
    """Pairing or sender authorization failed closed."""


class InMemoryChannelPairingStore:
    def __init__(self) -> None:
        self._requests: dict[ChannelSenderKey, PairingRequest] = {}

    async def get(self, sender: ChannelSenderKey) -> PairingRequest | None:
        return self._requests.get(sender)

    async def create_pending(
        self,
        request: PairingRequest,
        *,
        max_pending: int,
    ) -> PairingCreateResult:
        current = self._requests.get(request.sender)
        if current is not None and current.approved:
            return PairingCreateResult.ALREADY_APPROVED
        if current is not None and request.created_at < current.expires_at:
            return PairingCreateResult.ALREADY_PENDING
        active_pending = sum(
            1
            for candidate in self._requests.values()
            if candidate.sender.channel_kind is request.sender.channel_kind
            and not candidate.approved
            and request.created_at < candidate.expires_at
        )
        if active_pending >= max_pending:
            return PairingCreateResult.CAP_REACHED
        self._requests[request.sender] = request
        return PairingCreateResult.CREATED

    async def approve_pending(
        self,
        sender: ChannelSenderKey,
        *,
        code_digest: str,
        principal_id: str,
        at: datetime,
    ) -> PairingRequest | None:
        current = self._requests.get(sender)
        if (
            current is None
            or current.approved
            or at >= current.expires_at
            or not _constant_digest_equal(current.code_digest, code_digest)
        ):
            return None
        approved = replace(
            current,
            approved_principal_id=principal_id,
            approved_at=at,
        )
        self._requests[sender] = approved
        return approved

    async def cancel_pending(
        self,
        sender: ChannelSenderKey,
        *,
        code_digest: str,
    ) -> bool:
        current = self._requests.get(sender)
        if (
            current is None
            or current.approved
            or not _constant_digest_equal(current.code_digest, code_digest)
        ):
            return False
        del self._requests[sender]
        return True


class ChannelAccessService:
    """Resolve approved senders and manage bounded pairing requests."""

    def __init__(
        self,
        *,
        modes: Mapping[ConversationChannelKind, ChannelAccessMode],
        store: ChannelPairingStore,
        identities: ChannelIdentityDirectory,
        authorizer: PairingApprovalAuthorizer,
        code_factory: Callable[[], str],
        pairing_ttl_seconds: int = 3600,
        max_pending_per_channel: int = 3,
        transition_sink: RoutingTransitionSink | None = None,
    ) -> None:
        if pairing_ttl_seconds < 60 or max_pending_per_channel < 1:
            raise ValueError("channel pairing TTL and pending cap are invalid")
        self._modes = dict(modes)
        self._store = store
        self._identities = identities
        self._authorizer = authorizer
        self._code_factory = code_factory
        self._ttl = pairing_ttl_seconds
        self._max_pending = max_pending_per_channel
        self._transition_sink = transition_sink or default_transition_emitter()

    async def resolve(self, turn: InboundTurn) -> Principal | None:
        sender = _sender_key(turn)
        mode = self._modes.get(turn.channel_kind, ChannelAccessMode.DISABLED)
        if mode is ChannelAccessMode.DISABLED:
            return None
        request = await self._store.get(sender)
        if request is None or not request.approved:
            return None
        return await self._identities.principal_for_id(request.approved_principal_id or "")

    async def request_pairing(self, turn: InboundTurn, *, at: datetime) -> PairingChallenge:
        sender = _sender_key(turn)
        if self._modes.get(turn.channel_kind) is not ChannelAccessMode.PAIRING:
            raise ChannelAccessError("channel does not allow pairing")
        code = self._code_factory()
        if not code or len(code) > 64:
            raise ChannelAccessError("pairing code factory returned an invalid code")
        expires_at = at + timedelta(seconds=self._ttl)
        result = await self._store.create_pending(
            PairingRequest(
                sender=sender,
                code_digest=_code_digest(code),
                created_at=at,
                expires_at=expires_at,
            ),
            max_pending=self._max_pending,
        )
        if result is PairingCreateResult.ALREADY_PENDING:
            raise ChannelAccessError("a pairing request is already pending for this sender")
        if result is PairingCreateResult.ALREADY_APPROVED:
            raise ChannelAccessError("channel sender is already paired")
        if result is PairingCreateResult.CAP_REACHED:
            raise ChannelAccessError("channel pairing request cap is reached")
        self._emit(turn.channel_kind, "pairing.requested", "accepted")
        return PairingChallenge(code=code, expires_at=expires_at)

    async def approve(
        self,
        sender: ChannelSenderKey,
        *,
        code: str,
        principal_id: str,
        actor_id: str,
        at: datetime,
    ) -> PairingRequest:
        if not self._authorizer.can_approve_pairing(actor_id):
            raise ChannelAccessError("actor is not authorized to approve channel pairing")
        if actor_id.strip().casefold() == principal_id.strip().casefold():
            raise ChannelAccessError("channel sender pairing requires a distinct approver")
        if await self._identities.principal_for_id(principal_id) is None:
            raise ChannelAccessError("pairing target principal is unknown")
        current = await self._store.get(sender)
        if current is None or current.approved:
            raise ChannelAccessError("pairing request is missing or already approved")
        if at >= current.expires_at:
            raise ChannelAccessError("pairing request has expired")
        if not _constant_digest_equal(current.code_digest, _code_digest(code)):
            raise ChannelAccessError("pairing code is invalid")
        approved = await self._store.approve_pending(
            sender,
            code_digest=current.code_digest,
            principal_id=principal_id,
            at=at,
        )
        if approved is None:
            raise ChannelAccessError("pairing request changed before approval")
        self._emit(sender.channel_kind, "pairing.approved", "accepted")
        return approved

    async def cancel_pairing(self, turn: InboundTurn, *, code: str) -> bool:
        """Remove only the still-pending request created for ``code``."""
        return await self._store.cancel_pending(
            _sender_key(turn),
            code_digest=_code_digest(code),
        )

    def _emit(
        self,
        channel_kind: ConversationChannelKind,
        name: str,
        outcome: str,
    ) -> None:
        emit_transition_safely(
            self._transition_sink,
            RoutingTransition(
                domain="security",
                name=name,
                outcome=outcome,
                attributes={"channel_kind": channel_kind.value},
            ),
        )


def _sender_key(turn: InboundTurn) -> ChannelSenderKey:
    return ChannelSenderKey(turn.channel_kind, turn.channel_id, turn.sender_id)


def _code_digest(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _constant_digest_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


__all__ = [
    "ChannelAccessError",
    "ChannelAccessMode",
    "ChannelAccessService",
    "ChannelIdentityDirectory",
    "ChannelPairingStore",
    "ChannelSenderKey",
    "InMemoryChannelPairingStore",
    "PairingApprovalAuthorizer",
    "PairingChallenge",
    "PairingCreateResult",
    "PairingRequest",
]
