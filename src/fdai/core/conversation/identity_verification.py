"""Verify channel identity and scope before creating conversation bindings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.shared.providers.conversation_channel import ConversationChannelKind, InboundTurn
from fdai.shared.providers.conversation_delivery import VerifiedChannelEndpoint


@dataclass(frozen=True, slots=True)
class AuthorizedChannelPrincipal:
    """Canonical principal returned by an explicit vendor identity mapping."""

    principal_id: str
    authorization_ref: str

    def __post_init__(self) -> None:
        if not self.principal_id.strip() or not self.authorization_ref.strip():
            raise ValueError("authorized channel principal fields MUST be non-empty")


class ChannelPrincipalAuthorizationMapping(Protocol):
    async def resolve(
        self,
        *,
        channel_kind: ConversationChannelKind,
        channel_id: str,
        sender_id: str,
    ) -> AuthorizedChannelPrincipal | None: ...


class PrincipalScopeAuthorization(Protocol):
    def can_access_scope(self, *, principal_id: str, scope_ref: str) -> bool: ...


class ChannelIdentityVerificationError(ValueError):
    """Channel identity could not be promoted to an authorized endpoint."""


class ChannelIdentityVerificationHooks:
    """Create binding endpoints only from authenticated and authorized identities."""

    def __init__(
        self,
        *,
        mappings: ChannelPrincipalAuthorizationMapping,
        scopes: PrincipalScopeAuthorization,
    ) -> None:
        self._mappings = mappings
        self._scopes = scopes

    async def verify_external(
        self,
        *,
        turn: InboundTurn,
        scope_ref: str,
        verified_at: datetime,
    ) -> VerifiedChannelEndpoint:
        if turn.channel_kind is ConversationChannelKind.WEB:
            raise ChannelIdentityVerificationError("web identity requires Entra verification")
        mapping = await self._mappings.resolve(
            channel_kind=turn.channel_kind,
            channel_id=turn.channel_id,
            sender_id=turn.sender_id,
        )
        if mapping is None:
            raise ChannelIdentityVerificationError("channel sender has no active authorization")
        if mapping.principal_id == turn.sender_id:
            raise ChannelIdentityVerificationError(
                "vendor sender id MUST NOT be used as the canonical principal id"
            )
        self._authorize_scope(principal_id=mapping.principal_id, scope_ref=scope_ref)
        return VerifiedChannelEndpoint(
            principal_id=mapping.principal_id,
            scope_ref=scope_ref,
            channel_kind=turn.channel_kind,
            channel_id=turn.channel_id,
            sender_id=turn.sender_id,
            thread_id=turn.thread_id,
            verification_ref=mapping.authorization_ref,
            verified_at=verified_at,
        )

    def verify_web(
        self,
        *,
        authenticated_principal_id: str,
        scope_ref: str,
        channel_id: str,
        browser_session_ref: str,
        verification_ref: str,
        verified_at: datetime,
        thread_id: str | None = None,
    ) -> VerifiedChannelEndpoint:
        if authenticated_principal_id == browser_session_ref:
            raise ChannelIdentityVerificationError(
                "browser session ref MUST remain distinct from principal id"
            )
        self._authorize_scope(
            principal_id=authenticated_principal_id,
            scope_ref=scope_ref,
        )
        return VerifiedChannelEndpoint(
            principal_id=authenticated_principal_id,
            scope_ref=scope_ref,
            channel_kind=ConversationChannelKind.WEB,
            channel_id=channel_id,
            sender_id=browser_session_ref,
            thread_id=thread_id,
            verification_ref=verification_ref,
            verified_at=verified_at,
        )

    def _authorize_scope(self, *, principal_id: str, scope_ref: str) -> None:
        if not self._scopes.can_access_scope(principal_id=principal_id, scope_ref=scope_ref):
            raise ChannelIdentityVerificationError(
                "principal is not authorized for the requested scope"
            )


__all__ = [
    "AuthorizedChannelPrincipal",
    "ChannelIdentityVerificationError",
    "ChannelIdentityVerificationHooks",
    "ChannelPrincipalAuthorizationMapping",
    "PrincipalScopeAuthorization",
]
