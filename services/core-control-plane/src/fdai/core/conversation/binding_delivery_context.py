"""Resolve durable delivery context from verified active channel bindings."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from fdai.core.conversation.channel_gateway import ChannelDeliveryContext
from fdai.core.conversation.identity_verification import (
    ChannelIdentityVerificationError,
    ChannelIdentityVerificationHooks,
)
from fdai.core.conversation.principal_binding import PrincipalConversationBindingService
from fdai.core.conversation.session import Principal
from fdai.shared.providers.conversation_channel import InboundTurn


class ChannelScopeResolver(Protocol):
    async def resolve_scope(
        self,
        *,
        turn: InboundTurn,
        principal: Principal,
    ) -> str | None: ...


class VerifiedBindingDeliveryContextResolver:
    """Require identity mapping, scope authorization, and an active endpoint binding."""

    def __init__(
        self,
        *,
        identities: ChannelIdentityVerificationHooks,
        bindings: PrincipalConversationBindingService,
        scopes: ChannelScopeResolver,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._identities = identities
        self._bindings = bindings
        self._scopes = scopes
        self._clock = clock or (lambda: datetime.now(UTC))

    async def resolve(
        self,
        *,
        turn: InboundTurn,
        principal: Principal,
        session_id: str,
    ) -> ChannelDeliveryContext | None:
        del session_id
        scope_ref = await self._scopes.resolve_scope(turn=turn, principal=principal)
        if scope_ref is None:
            return None
        try:
            endpoint = await self._identities.verify_external(
                turn=turn,
                scope_ref=scope_ref,
                verified_at=self._clock(),
            )
        except ChannelIdentityVerificationError:
            return None
        if endpoint.principal_id != principal.id:
            return None
        binding = await self._bindings.resolve_endpoint(endpoint=endpoint)
        if binding is None:
            return None
        return ChannelDeliveryContext(
            principal_id=binding.principal_id,
            scope_ref=binding.scope_ref,
            conversation_id=binding.conversation_id,
            binding_id=binding.binding_id,
        )


__all__ = ["ChannelScopeResolver", "VerifiedBindingDeliveryContextResolver"]
