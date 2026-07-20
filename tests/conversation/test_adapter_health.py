from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.conversation.adapter_health import (
    AdapterFallbackRoute,
    AdapterHealthConfig,
    AdapterHealthError,
    AdapterHealthService,
    InMemoryAdapterHealthAuditSink,
)
from fdai.shared.providers.conversation_channel import ConversationChannelKind
from fdai.shared.providers.conversation_delivery import (
    AdapterBreakerMode,
    AdapterBreakerRecord,
    InMemoryConversationDeliveryStore,
)

NOW = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)


class _Authorizer:
    def can_manage_adapter(self, *, actor_id: str, adapter_id: str) -> bool:
        return actor_id == "owner-example" and adapter_id == "slack"


class _FallbackAuthorizer:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed

    def can_notify(self, route: AdapterFallbackRoute) -> bool:
        return self.allowed and route.category == "A2"


class _Notifier:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def notify(
        self,
        *,
        route: AdapterFallbackRoute,
        breaker: AdapterBreakerRecord,
    ) -> None:
        self.calls += 1
        if self.fail:
            raise RuntimeError("synthetic fallback failure")


def _service(
    *,
    notifier: _Notifier | None = None,
    fallback_allowed: bool = True,
) -> tuple[AdapterHealthService, InMemoryAdapterHealthAuditSink]:
    store = InMemoryConversationDeliveryStore()
    audit = InMemoryAdapterHealthAuditSink()
    service = AdapterHealthService(
        store=store,
        audit=audit,
        authorizer=_Authorizer(),
        config=AdapterHealthConfig(failure_threshold=2, failure_window_seconds=60),
        fallback_routes=(
            AdapterFallbackRoute(
                source_adapter_id="slack",
                target_adapter_id="teams-ops",
                target_channel_kind=ConversationChannelKind.TEAMS,
            ),
        )
        if notifier is not None
        else (),
        fallback_authorizer=(
            _FallbackAuthorizer(fallback_allowed) if notifier is not None else None
        ),
        fallback_notifier=notifier,
    )
    return service, audit


async def test_failure_window_opens_and_never_auto_resumes() -> None:
    service, audit = _service()
    await service.record_failure(
        adapter_id="slack",
        channel_kind=ConversationChannelKind.SLACK,
        at=NOW,
        error_code="http_503",
    )
    assert await service.can_send(adapter_id="slack") is True
    await service.record_failure(
        adapter_id="slack",
        channel_kind=ConversationChannelKind.SLACK,
        at=NOW + timedelta(seconds=1),
        error_code="http_503",
    )

    assert await service.can_send(adapter_id="slack") is False
    status = await service.status(adapter_id="slack")
    assert status is not None and status.mode is AdapterBreakerMode.OPEN
    assert audit.events[-1].action == "opened"


async def test_authorized_pause_and_explicit_resume_are_audited() -> None:
    service, audit = _service()
    paused = await service.pause(
        adapter_id="slack",
        channel_kind=ConversationChannelKind.SLACK,
        actor_id="owner-example",
        reason="maintenance",
        at=NOW,
    )
    assert paused.mode is AdapterBreakerMode.PAUSED
    assert await service.can_send(adapter_id="slack") is False

    with pytest.raises(AdapterHealthError, match="authorized"):
        await service.resume(
            adapter_id="slack",
            actor_id="reader-example",
            reason="unsafe",
            at=NOW,
        )
    resumed = await service.resume(
        adapter_id="slack",
        actor_id="owner-example",
        reason="provider verified",
        at=NOW + timedelta(minutes=1),
    )
    assert resumed.mode is AdapterBreakerMode.CLOSED
    assert [event.action for event in audit.events] == ["paused", "resumed"]


async def test_fallback_notification_is_authorized_and_failure_is_visible() -> None:
    notifier = _Notifier(fail=True)
    service, audit = _service(notifier=notifier)
    for offset in range(2):
        await service.record_failure(
            adapter_id="slack",
            channel_kind=ConversationChannelKind.SLACK,
            at=NOW + timedelta(seconds=offset),
            error_code="http_503",
        )
    assert notifier.calls == 1
    assert [event.action for event in audit.events[-2:]] == ["opened", "fallback_failed"]


async def test_unauthorized_fallback_never_calls_notifier() -> None:
    notifier = _Notifier()
    service, audit = _service(notifier=notifier, fallback_allowed=False)
    for offset in range(2):
        await service.record_failure(
            adapter_id="slack",
            channel_kind=ConversationChannelKind.SLACK,
            at=NOW + timedelta(seconds=offset),
            error_code="http_503",
        )
    assert notifier.calls == 0
    assert audit.events[-1].action == "fallback_denied"
