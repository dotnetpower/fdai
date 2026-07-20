from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.conversation.identity_verification import (
    AuthorizedChannelPrincipal,
    ChannelIdentityVerificationError,
    ChannelIdentityVerificationHooks,
)
from fdai.shared.providers.conversation_channel import (
    ConversationChannelKind,
    InboundTurn,
)

NOW = datetime(2026, 7, 20, 20, 0, tzinfo=UTC)


class _Mappings:
    def __init__(self) -> None:
        self.revoked = False

    async def resolve(
        self,
        *,
        channel_kind: ConversationChannelKind,
        channel_id: str,
        sender_id: str,
    ) -> AuthorizedChannelPrincipal | None:
        del channel_id
        if self.revoked:
            return None
        return AuthorizedChannelPrincipal(
            principal_id=f"principal-for-{channel_kind.value}",
            authorization_ref=f"mapping:{channel_kind.value}:{sender_id}",
        )


class _Scopes:
    def can_access_scope(self, *, principal_id: str, scope_ref: str) -> bool:
        return principal_id.startswith("principal-") and scope_ref == "scope-example"


def _turn(kind: ConversationChannelKind) -> InboundTurn:
    return InboundTurn(
        channel_kind=kind,
        channel_id=f"{kind.value}-channel",
        message_id=f"{kind.value}-message",
        sender_id=f"{kind.value}-vendor-user",
        thread_id=f"{kind.value}-thread",
        text="status",
    )


@pytest.mark.parametrize(
    "kind",
    [ConversationChannelKind.SLACK, ConversationChannelKind.TEAMS],
)
async def test_external_hooks_preserve_vendor_sender_separate_from_principal(
    kind: ConversationChannelKind,
) -> None:
    hooks = ChannelIdentityVerificationHooks(mappings=_Mappings(), scopes=_Scopes())

    endpoint = await hooks.verify_external(
        turn=_turn(kind),
        scope_ref="scope-example",
        verified_at=NOW,
    )

    assert endpoint.principal_id == f"principal-for-{kind.value}"
    assert endpoint.sender_id == f"{kind.value}-vendor-user"
    assert endpoint.principal_id != endpoint.sender_id
    assert endpoint.verification_ref.startswith("mapping:")


def test_web_hook_requires_authenticated_principal_and_distinct_session_ref() -> None:
    hooks = ChannelIdentityVerificationHooks(mappings=_Mappings(), scopes=_Scopes())

    endpoint = hooks.verify_web(
        authenticated_principal_id="principal-web",
        scope_ref="scope-example",
        channel_id="console",
        browser_session_ref="browser-session-example",
        verification_ref="entra:token-example",
        verified_at=NOW,
    )

    assert endpoint.channel_kind is ConversationChannelKind.WEB
    assert endpoint.principal_id == "principal-web"
    assert endpoint.sender_id == "browser-session-example"


async def test_revoked_mapping_and_cross_scope_are_denied() -> None:
    mappings = _Mappings()
    hooks = ChannelIdentityVerificationHooks(mappings=mappings, scopes=_Scopes())
    mappings.revoked = True

    with pytest.raises(ChannelIdentityVerificationError, match="no active authorization"):
        await hooks.verify_external(
            turn=_turn(ConversationChannelKind.SLACK),
            scope_ref="scope-example",
            verified_at=NOW,
        )

    mappings.revoked = False
    with pytest.raises(ChannelIdentityVerificationError, match="not authorized"):
        await hooks.verify_external(
            turn=_turn(ConversationChannelKind.TEAMS),
            scope_ref="other-scope",
            verified_at=NOW,
        )


async def test_vendor_sender_cannot_be_returned_as_principal() -> None:
    class _UnsafeMapping:
        async def resolve(
            self,
            *,
            channel_kind: ConversationChannelKind,
            channel_id: str,
            sender_id: str,
        ) -> AuthorizedChannelPrincipal:
            del channel_kind, channel_id
            return AuthorizedChannelPrincipal(
                principal_id=sender_id,
                authorization_ref="unsafe-mapping",
            )

    hooks = ChannelIdentityVerificationHooks(mappings=_UnsafeMapping(), scopes=_Scopes())
    with pytest.raises(ChannelIdentityVerificationError, match="vendor sender"):
        await hooks.verify_external(
            turn=_turn(ConversationChannelKind.SLACK),
            scope_ref="scope-example",
            verified_at=NOW,
        )
