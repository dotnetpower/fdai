from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.conversation.binding_delivery_context import (
    VerifiedBindingDeliveryContextResolver,
)
from fdai.core.conversation.identity_verification import (
    AuthorizedChannelPrincipal,
    ChannelIdentityVerificationHooks,
)
from fdai.core.conversation.principal_binding import (
    InMemoryPrincipalConversationBindingAuditSink,
    InMemoryPrincipalConversationBindingStore,
    PrincipalConversationBindingService,
)
from fdai.core.conversation.session import Principal, Role
from fdai.shared.providers.conversation_channel import (
    ConversationChannelKind,
    InboundTurn,
)

NOW = datetime(2026, 7, 20, 22, 0, tzinfo=UTC)


class _Mappings:
    async def resolve(
        self,
        *,
        channel_kind: ConversationChannelKind,
        channel_id: str,
        sender_id: str,
    ) -> AuthorizedChannelPrincipal:
        del channel_kind, channel_id, sender_id
        return AuthorizedChannelPrincipal(
            principal_id="principal-example",
            authorization_ref="mapping:example",
        )


class _Scopes:
    def can_access_scope(self, *, principal_id: str, scope_ref: str) -> bool:
        return principal_id == "principal-example" and scope_ref == "scope-example"


class _BindingAuthorizer:
    def can_manage_binding(self, *, actor_id: str, principal_id: str, scope_ref: str) -> bool:
        return actor_id == principal_id and scope_ref == "scope-example"


class _ScopeResolver:
    async def resolve_scope(self, *, turn: InboundTurn, principal: Principal) -> str | None:
        del turn
        return "scope-example" if principal.id == "principal-example" else None


def _turn() -> InboundTurn:
    return InboundTurn(
        channel_kind=ConversationChannelKind.SLACK,
        channel_id="channel-example",
        message_id="message-example",
        sender_id="vendor-sender-example",
        thread_id="thread-example",
        text="status",
    )


async def test_active_verified_binding_resolves_and_revocation_denies_delivery() -> None:
    store = InMemoryPrincipalConversationBindingStore()
    bindings = PrincipalConversationBindingService(
        store=store,
        audit=InMemoryPrincipalConversationBindingAuditSink(),
        authorizer=_BindingAuthorizer(),
    )
    identities = ChannelIdentityVerificationHooks(mappings=_Mappings(), scopes=_Scopes())
    endpoint = await identities.verify_external(
        turn=_turn(),
        scope_ref="scope-example",
        verified_at=NOW,
    )
    binding = await bindings.bind_new(
        endpoint=endpoint,
        conversation_id="conversation-example",
        actor_id="principal-example",
        at=NOW,
    )
    resolver = VerifiedBindingDeliveryContextResolver(
        identities=identities,
        bindings=bindings,
        scopes=_ScopeResolver(),
        clock=lambda: NOW,
    )
    principal = Principal(id="principal-example", role=Role.READER)

    context = await resolver.resolve(turn=_turn(), principal=principal, session_id="ignored")
    await bindings.revoke(
        binding_id=binding.binding_id,
        actor_id="principal-example",
        at=NOW,
    )
    revoked = await resolver.resolve(turn=_turn(), principal=principal, session_id="ignored")

    assert context is not None
    assert context.binding_id == binding.binding_id
    assert context.conversation_id == "conversation-example"
    assert revoked is None


async def test_revoked_authorization_mapping_denies_without_raising() -> None:
    class _RevokedMappings:
        async def resolve(
            self,
            *,
            channel_kind: ConversationChannelKind,
            channel_id: str,
            sender_id: str,
        ) -> None:
            del channel_kind, channel_id, sender_id
            return None

    identities = ChannelIdentityVerificationHooks(
        mappings=_RevokedMappings(),
        scopes=_Scopes(),
    )
    resolver = VerifiedBindingDeliveryContextResolver(
        identities=identities,
        bindings=PrincipalConversationBindingService(
            store=InMemoryPrincipalConversationBindingStore(),
            audit=InMemoryPrincipalConversationBindingAuditSink(),
            authorizer=_BindingAuthorizer(),
        ),
        scopes=_ScopeResolver(),
        clock=lambda: NOW,
    )

    context = await resolver.resolve(
        turn=_turn(),
        principal=Principal(id="principal-example", role=Role.READER),
        session_id="ignored",
    )

    assert context is None
