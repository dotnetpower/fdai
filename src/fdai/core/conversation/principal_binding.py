"""Verified principal-to-conversation bindings with explicit channel resume."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from fdai.shared.providers.conversation_delivery import (
    PrincipalConversationBinding,
    PrincipalConversationBindingState,
    VerifiedChannelEndpoint,
)


@dataclass(frozen=True, slots=True)
class PrincipalConversationBindingAuditEvent:
    event_id: str
    binding_id: str
    action: str
    principal_id: str
    actor_id: str
    scope_ref: str
    occurred_at: datetime
    source_binding_id: str | None = None


class PrincipalConversationBindingStore(Protocol):
    async def create(
        self,
        binding: PrincipalConversationBinding,
    ) -> PrincipalConversationBinding: ...

    async def get(self, binding_id: str) -> PrincipalConversationBinding | None: ...

    async def revoke(
        self,
        *,
        binding_id: str,
        expected_state: PrincipalConversationBindingState,
        actor_id: str,
        at: datetime,
    ) -> PrincipalConversationBinding | None: ...

    async def list_for_principal(
        self,
        *,
        principal_id: str,
        include_revoked: bool = False,
    ) -> Sequence[PrincipalConversationBinding]: ...


class PrincipalConversationBindingAuditSink(Protocol):
    async def append(self, event: PrincipalConversationBindingAuditEvent) -> None: ...


class PrincipalConversationBindingAuthorizer(Protocol):
    def can_manage_binding(self, *, actor_id: str, principal_id: str, scope_ref: str) -> bool: ...


class PrincipalConversationBindingError(ValueError):
    """A binding operation failed closed without changing durable state."""


class InMemoryPrincipalConversationBindingStore:
    def __init__(self) -> None:
        self._bindings: dict[str, PrincipalConversationBinding] = {}

    async def create(
        self,
        binding: PrincipalConversationBinding,
    ) -> PrincipalConversationBinding:
        current = self._bindings.get(binding.binding_id)
        if current is not None:
            if current != binding:
                raise PrincipalConversationBindingError(
                    "binding id was reused with different immutable content"
                )
            return current
        self._bindings[binding.binding_id] = binding
        return binding

    async def get(self, binding_id: str) -> PrincipalConversationBinding | None:
        return self._bindings.get(binding_id)

    async def revoke(
        self,
        *,
        binding_id: str,
        expected_state: PrincipalConversationBindingState,
        actor_id: str,
        at: datetime,
    ) -> PrincipalConversationBinding | None:
        current = self._bindings.get(binding_id)
        if current is None or current.state is not expected_state:
            return None
        revoked = replace(
            current,
            state=PrincipalConversationBindingState.REVOKED,
            revoked_by=actor_id,
            revoked_at=at,
        )
        self._bindings[binding_id] = revoked
        return revoked

    async def list_for_principal(
        self,
        *,
        principal_id: str,
        include_revoked: bool = False,
    ) -> Sequence[PrincipalConversationBinding]:
        return tuple(
            binding
            for binding in self._bindings.values()
            if binding.principal_id == principal_id
            and (include_revoked or binding.state is PrincipalConversationBindingState.ACTIVE)
        )


class InMemoryPrincipalConversationBindingAuditSink:
    def __init__(self) -> None:
        self.events: list[PrincipalConversationBindingAuditEvent] = []

    async def append(self, event: PrincipalConversationBindingAuditEvent) -> None:
        self.events.append(event)


class PrincipalConversationBindingService:
    """Persist only verified mappings and never infer cross-channel continuity."""

    def __init__(
        self,
        *,
        store: PrincipalConversationBindingStore,
        audit: PrincipalConversationBindingAuditSink,
        authorizer: PrincipalConversationBindingAuthorizer,
    ) -> None:
        self._store = store
        self._audit = audit
        self._authorizer = authorizer

    async def bind_new(
        self,
        *,
        endpoint: VerifiedChannelEndpoint,
        conversation_id: str,
        actor_id: str,
        at: datetime,
    ) -> PrincipalConversationBinding:
        self._authorize(endpoint, actor_id=actor_id)
        binding = _binding(
            endpoint=endpoint,
            conversation_id=conversation_id,
            actor_id=actor_id,
            at=at,
            source_binding_id=None,
        )
        stored = await self._store.create(binding)
        await self._audit_once(stored, action="created", source_binding_id=None)
        return stored

    async def resume_cross_channel(
        self,
        *,
        source_binding_id: str,
        endpoint: VerifiedChannelEndpoint,
        actor_id: str,
        at: datetime,
    ) -> PrincipalConversationBinding:
        source = await self._store.get(source_binding_id)
        if source is None or source.state is not PrincipalConversationBindingState.ACTIVE:
            raise PrincipalConversationBindingError("source binding is unavailable")
        if source.principal_id != endpoint.principal_id:
            raise PrincipalConversationBindingError("cross-principal resume is denied")
        if source.scope_ref != endpoint.scope_ref:
            raise PrincipalConversationBindingError("cross-scope resume is denied")
        if source.endpoint.channel_kind is endpoint.channel_kind:
            raise PrincipalConversationBindingError("cross-channel resume requires another channel")
        self._authorize(endpoint, actor_id=actor_id)
        binding = _binding(
            endpoint=endpoint,
            conversation_id=source.conversation_id,
            actor_id=actor_id,
            at=at,
            source_binding_id=source.binding_id,
        )
        stored = await self._store.create(binding)
        await self._audit_once(
            stored,
            action="cross_channel_resumed",
            source_binding_id=source.binding_id,
        )
        return stored

    async def resolve(
        self,
        *,
        binding_id: str,
        endpoint: VerifiedChannelEndpoint,
    ) -> PrincipalConversationBinding | None:
        binding = await self._store.get(binding_id)
        if binding is None or binding.state is not PrincipalConversationBindingState.ACTIVE:
            return None
        if (
            binding.principal_id != endpoint.principal_id
            or binding.scope_ref != endpoint.scope_ref
            or binding.endpoint.channel_kind is not endpoint.channel_kind
            or binding.endpoint.channel_id != endpoint.channel_id
            or binding.endpoint.sender_id != endpoint.sender_id
            or binding.endpoint.thread_id != endpoint.thread_id
        ):
            return None
        return binding

    async def resolve_endpoint(
        self,
        *,
        endpoint: VerifiedChannelEndpoint,
    ) -> PrincipalConversationBinding | None:
        bindings = await self._store.list_for_principal(principal_id=endpoint.principal_id)
        for binding in bindings:
            if (
                binding.state is PrincipalConversationBindingState.ACTIVE
                and binding.scope_ref == endpoint.scope_ref
                and binding.endpoint.channel_kind is endpoint.channel_kind
                and binding.endpoint.channel_id == endpoint.channel_id
                and binding.endpoint.sender_id == endpoint.sender_id
                and binding.endpoint.thread_id == endpoint.thread_id
            ):
                return binding
        return None

    async def revoke(
        self,
        *,
        binding_id: str,
        actor_id: str,
        at: datetime,
    ) -> PrincipalConversationBinding:
        current = await self._store.get(binding_id)
        if current is None:
            raise PrincipalConversationBindingError("binding is unavailable")
        if not self._authorizer.can_manage_binding(
            actor_id=actor_id,
            principal_id=current.principal_id,
            scope_ref=current.scope_ref,
        ):
            raise PrincipalConversationBindingError("actor is not authorized to revoke binding")
        if current.state is PrincipalConversationBindingState.REVOKED:
            return current
        revoked = await self._store.revoke(
            binding_id=binding_id,
            expected_state=PrincipalConversationBindingState.ACTIVE,
            actor_id=actor_id,
            at=at,
        )
        if revoked is None:
            raise PrincipalConversationBindingError("binding changed before revocation")
        await self._audit_once(revoked, action="revoked", source_binding_id=None)
        return revoked

    def _authorize(self, endpoint: VerifiedChannelEndpoint, *, actor_id: str) -> None:
        if endpoint.verified_at.tzinfo is None:
            raise PrincipalConversationBindingError("verified endpoint timestamp is invalid")
        if not self._authorizer.can_manage_binding(
            actor_id=actor_id,
            principal_id=endpoint.principal_id,
            scope_ref=endpoint.scope_ref,
        ):
            raise PrincipalConversationBindingError("actor is not authorized to create binding")

    async def _audit_once(
        self,
        binding: PrincipalConversationBinding,
        *,
        action: str,
        source_binding_id: str | None,
    ) -> None:
        actor_id = binding.revoked_by or binding.created_by
        occurred_at = binding.revoked_at or binding.created_at
        event_id = _event_id(binding.binding_id, action)
        await self._audit.append(
            PrincipalConversationBindingAuditEvent(
                event_id=event_id,
                binding_id=binding.binding_id,
                action=action,
                principal_id=binding.principal_id,
                actor_id=actor_id,
                scope_ref=binding.scope_ref,
                occurred_at=occurred_at,
                source_binding_id=source_binding_id,
            )
        )


def _binding(
    *,
    endpoint: VerifiedChannelEndpoint,
    conversation_id: str,
    actor_id: str,
    at: datetime,
    source_binding_id: str | None,
) -> PrincipalConversationBinding:
    raw = "\0".join(
        (
            endpoint.principal_id,
            endpoint.scope_ref,
            conversation_id,
            endpoint.channel_kind.value,
            endpoint.channel_id,
            endpoint.sender_id,
            endpoint.thread_id or "",
            source_binding_id or "",
        )
    )
    binding_id = "principal-conversation:" + hashlib.sha256(raw.encode()).hexdigest()[:40]
    return PrincipalConversationBinding(
        binding_id=binding_id,
        principal_id=endpoint.principal_id,
        scope_ref=endpoint.scope_ref,
        conversation_id=conversation_id,
        endpoint=endpoint,
        created_by=actor_id,
        created_at=at,
        resumed_from_binding_id=source_binding_id,
    )


def _event_id(binding_id: str, action: str) -> str:
    digest = hashlib.sha256(f"{binding_id}\0{action}".encode()).hexdigest()[:32]
    return f"binding-audit:{digest}"


__all__ = [
    "InMemoryPrincipalConversationBindingAuditSink",
    "InMemoryPrincipalConversationBindingStore",
    "PrincipalConversationBindingAuditEvent",
    "PrincipalConversationBindingAuditSink",
    "PrincipalConversationBindingAuthorizer",
    "PrincipalConversationBindingError",
    "PrincipalConversationBindingService",
    "PrincipalConversationBindingStore",
]
