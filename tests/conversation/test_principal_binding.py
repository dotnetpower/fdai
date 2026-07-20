from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from fdai.core.conversation.principal_binding import (
    InMemoryPrincipalConversationBindingAuditSink,
    InMemoryPrincipalConversationBindingStore,
    PrincipalConversationBindingError,
    PrincipalConversationBindingService,
)
from fdai.shared.providers.conversation_channel import ConversationChannelKind
from fdai.shared.providers.conversation_delivery import (
    PrincipalConversationBindingState,
    VerifiedChannelEndpoint,
)

NOW = datetime(2026, 7, 20, 13, 0, tzinfo=UTC)


class _Authorizer:
    def can_manage_binding(self, *, actor_id: str, principal_id: str, scope_ref: str) -> bool:
        return actor_id == principal_id and scope_ref == "scope-example"


def _endpoint(
    kind: ConversationChannelKind,
    *,
    principal_id: str = "principal-example",
) -> VerifiedChannelEndpoint:
    return VerifiedChannelEndpoint(
        principal_id=principal_id,
        scope_ref="scope-example",
        channel_kind=kind,
        channel_id=f"{kind.value}-channel",
        sender_id=f"{kind.value}-sender",
        thread_id=f"{kind.value}-thread",
        verification_ref=f"verified:{kind.value}",
        verified_at=NOW,
    )


def _service() -> tuple[
    PrincipalConversationBindingService,
    InMemoryPrincipalConversationBindingAuditSink,
]:
    audit = InMemoryPrincipalConversationBindingAuditSink()
    service = PrincipalConversationBindingService(
        store=InMemoryPrincipalConversationBindingStore(),
        audit=audit,
        authorizer=_Authorizer(),
    )
    return service, audit


async def test_explicit_cross_channel_resume_preserves_principal_scope_and_conversation() -> None:
    service, audit = _service()
    source = await service.bind_new(
        endpoint=_endpoint(ConversationChannelKind.WEB),
        conversation_id="conversation-example",
        actor_id="principal-example",
        at=NOW,
    )
    resumed = await service.resume_cross_channel(
        source_binding_id=source.binding_id,
        endpoint=_endpoint(ConversationChannelKind.SLACK),
        actor_id="principal-example",
        at=NOW,
    )

    assert resumed.conversation_id == source.conversation_id
    assert resumed.resumed_from_binding_id == source.binding_id
    assert resumed.endpoint.thread_id == "slack-thread"
    assert [event.action for event in audit.events] == ["created", "cross_channel_resumed"]


@pytest.mark.parametrize(
    ("changed_field", "message"),
    [
        ("principal_id", "cross-principal"),
        ("scope_ref", "cross-scope"),
    ],
)
async def test_cross_principal_and_scope_resume_are_denied(
    changed_field: str,
    message: str,
) -> None:
    service, _ = _service()
    source = await service.bind_new(
        endpoint=_endpoint(ConversationChannelKind.WEB),
        conversation_id="conversation-example",
        actor_id="principal-example",
        at=NOW,
    )
    target_endpoint = _endpoint(ConversationChannelKind.SLACK)
    target = (
        replace(target_endpoint, principal_id="other-principal")
        if changed_field == "principal_id"
        else replace(target_endpoint, scope_ref="other-scope")
    )
    with pytest.raises(PrincipalConversationBindingError, match=message):
        await service.resume_cross_channel(
            source_binding_id=source.binding_id,
            endpoint=target,
            actor_id=target.principal_id,
            at=NOW,
        )


async def test_thread_isolation_and_revocation_fail_closed() -> None:
    service, audit = _service()
    endpoint = _endpoint(ConversationChannelKind.TEAMS)
    binding = await service.bind_new(
        endpoint=endpoint,
        conversation_id="conversation-example",
        actor_id="principal-example",
        at=NOW,
    )

    assert await service.resolve(binding_id=binding.binding_id, endpoint=endpoint) == binding
    assert (
        await service.resolve(
            binding_id=binding.binding_id,
            endpoint=replace(endpoint, thread_id="other-thread"),
        )
        is None
    )

    revoked = await service.revoke(
        binding_id=binding.binding_id,
        actor_id="principal-example",
        at=NOW,
    )
    assert revoked.state is PrincipalConversationBindingState.REVOKED
    assert await service.resolve(binding_id=binding.binding_id, endpoint=endpoint) is None
    assert audit.events[-1].action == "revoked"
