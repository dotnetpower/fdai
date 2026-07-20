from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.delivery.read_api.app.config import ReadApiConfig
from fdai.delivery.read_api.app.factory import build_app
from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.conversation_delivery import ConversationDeliveryPanel
from fdai.shared.providers.conversation_channel import (
    ConversationChannelKind,
    OutboundResponse,
)
from fdai.shared.providers.conversation_delivery import (
    AdapterBreakerMode,
    AdapterBreakerRecord,
    InMemoryConversationDeliveryStore,
    OutboundDeliveryRecord,
    OutboundDeliveryState,
    new_delivery_record,
)

NOW = datetime(2026, 7, 20, 21, 0, tzinfo=UTC)


def _record(suffix: str) -> OutboundDeliveryRecord:
    return new_delivery_record(
        origin_ref=f"turn:{suffix}",
        principal_id="principal-example",
        scope_ref="scope-example",
        conversation_id="conversation-example",
        binding_id="binding-example",
        response=OutboundResponse(
            channel_kind=ConversationChannelKind.SLACK,
            channel_id="channel-example",
            in_reply_to=f"message-{suffix}",
            thread_id="thread-example",
            status="ok",
            text=f"response-{suffix}",
        ),
        created_at=NOW,
        freshness=timedelta(minutes=15),
        retention=timedelta(days=30),
    )


async def test_panel_projects_delivery_reliability_without_mutation_controls() -> None:
    store = InMemoryConversationDeliveryStore()
    await store.put(
        replace(
            _record("delivered"),
            state=OutboundDeliveryState.DELIVERED,
            attempt_count=1,
            terminal_at=NOW + timedelta(milliseconds=120),
        )
    )
    await store.put(
        replace(
            _record("ambiguous"),
            state=OutboundDeliveryState.AMBIGUOUS,
            attempt_count=1,
            duplicate_risk=True,
            terminal_at=NOW + timedelta(milliseconds=200),
        )
    )
    await store.put(
        replace(
            _record("failed"),
            state=OutboundDeliveryState.FAILED,
            attempt_count=2,
            due_at=NOW + timedelta(seconds=5),
        )
    )
    await store.put(
        replace(
            _record("abandoned"),
            state=OutboundDeliveryState.ABANDONED,
            attempt_count=4,
            terminal_at=NOW + timedelta(seconds=10),
        )
    )
    await store.put_breaker(
        AdapterBreakerRecord(
            adapter_id="slack",
            channel_kind=ConversationChannelKind.SLACK,
            mode=AdapterBreakerMode.OPEN,
            failure_timestamps=(NOW,),
            revision=0,
            updated_at=NOW,
            updated_by="system",
            reason="http_503",
        ),
        expected_revision=None,
    )

    result = await ConversationDeliveryPanel(store=store, source="postgres").render(params={})

    assert result["read_only"] is True
    assert result["mutations_available"] is False
    assert result["delivery_latency_ms"] == {"count": 1, "average": 120.0, "p95": 120}
    assert result["duplicate_risk_count"] == 1
    assert result["retry_count"] == 4
    assert result["abandonment_count"] == 1
    assert result["breaker_states"] == {"open": 1}


async def test_read_api_registers_get_only_delivery_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")
    store = InMemoryConversationDeliveryStore()
    await store.put(_record("pending"))
    placeholder = "00000000-0000-0000-0000-000000000000"
    authenticator = build_authenticator(
        verifier=lambda _: {"oid": "test-reader", "roles": ["Reader"]},
        resolver=RoleResolver(
            group_mapping=GroupMapping(
                reader_group_id=placeholder,
                contributor_group_id=placeholder,
                approver_group_id=placeholder,
                owner_group_id=placeholder,
                break_glass_group_id=placeholder,
            )
        ),
    )
    app = build_app(
        authenticator=authenticator,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            conversation_delivery_store=store,
            conversation_delivery_source="test",
        ),
    )

    with TestClient(app) as client:
        read = client.get("/conversation-delivery")
        mutation = client.post("/conversation-delivery", json={"action": "resume"})

    assert read.status_code == 200
    assert read.json()["source"] == "test"
    assert mutation.status_code == 405
