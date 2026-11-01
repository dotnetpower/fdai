"""Tests for /commands/adapters/* controller and ConversationDeliveryPanel Console route."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fdai_operator_service.adapter_commands_api import (
    AdapterCommandController,
    AdapterCommandError,
    AdapterCommandPrincipal,
    InMemoryAdapterCommandBreakerStore,
)
from fdai_operator_service.conversation_delivery_panel_route import (
    BoundedProgressiveConversationCollector,
    ConversationDeliveryPanelRoute,
)
from fdai_operator_service.families.conversation.channel_delivery_models import (
    ChannelAdapterBreaker,
    ChannelBreakerMode,
    ChannelDeliveryAcknowledgement,
    ChannelDeliveryAttempt,
    ChannelDeliveryRecord,
    ChannelDeliverySnapshot,
    ChannelDeliveryState,
    ChannelKind,
    channel_response_digest,
)
from fdai_operator_service.families.conversation.contracts import JsonObject

NOW = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)


class _SnapshotStore:
    def __init__(self, snapshot: ChannelDeliverySnapshot) -> None:
        self._snapshot = snapshot
        self.limits: list[int] = []

    async def snapshot(self, *, limit: int = 200) -> ChannelDeliverySnapshot:
        self.limits.append(limit)
        return self._snapshot


def _delivery_record(
    suffix: str,
    *,
    state: ChannelDeliveryState,
    attempt_count: int = 1,
    duplicate_risk: bool = False,
    latency_ms: int | None = 200,
) -> ChannelDeliveryRecord:
    response: JsonObject = {"text": f"confidential-answer-{suffix}", "channel_id": f"chan-{suffix}"}
    return ChannelDeliveryRecord(
        delivery_id=f"deliv-{suffix}",
        idempotency_key=f"idem-{suffix}",
        principal_id=f"principal-{suffix}",
        scope_ref=f"scope-{suffix}",
        conversation_id=f"conv-{suffix}",
        binding_id=f"bind-{suffix}",
        channel_kind=ChannelKind.SLACK,
        response=response,
        response_digest=channel_response_digest(response),
        state=state,
        created_at=NOW,
        due_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        retention_until=NOW + timedelta(days=7),
        attempt_count=attempt_count,
        duplicate_risk=duplicate_risk,
        terminal_at=(NOW + timedelta(milliseconds=latency_ms)) if latency_ms is not None else None,
    )


async def test_adapter_commands_status_pause_resume_rbac_and_audit_receipts() -> None:
    store = InMemoryAdapterCommandBreakerStore()
    controller = AdapterCommandController(store=store, clock=lambda: NOW)

    owner = AdapterCommandPrincipal(
        principal_id="operator:owner-1",
        roles=frozenset({"Owner"}),
    )
    approver = AdapterCommandPrincipal(
        principal_id="operator:approver-1",
        roles=frozenset({"Approver"}),
    )
    reader = AdapterCommandPrincipal(
        principal_id="operator:reader-1",
        roles=frozenset({"Reader"}),
    )

    initial_status = await controller.handle(
        path="/commands/adapters/slack/status",
        method="GET",
        principal=reader,
    )
    assert initial_status.mode == "closed"
    assert initial_status.can_send is True
    assert initial_status.execution_authority == "none"
    assert initial_status.mounted_in_console_api is False
    assert initial_status.state_digest.startswith("sha256:")
    assert len(initial_status.state_digest) == 71
    assert initial_status.to_json()["state_digest"] == initial_status.state_digest

    # Reader cannot pause or resume.
    with pytest.raises(AdapterCommandError) as forbidden_exc:
        await controller.handle(
            path="/commands/adapters/slack/pause",
            method="POST",
            principal=reader,
            payload={"reason": "provider maintenance"},
        )
    assert forbidden_exc.value.status_code == 403
    assert forbidden_exc.value.code == "forbidden_role"

    # Console surface token cannot invoke /commands/adapters/*.
    console_principal = AdapterCommandPrincipal(
        principal_id="operator:owner-1",
        roles=frozenset({"Owner"}),
        authenticated_surface="console-operator-api",
    )
    with pytest.raises(AdapterCommandError) as surface_exc:
        await controller.handle(
            path="/commands/adapters/slack/pause",
            method="POST",
            principal=console_principal,
            payload={"reason": "attempted from console"},
        )
    assert surface_exc.value.status_code == 403
    assert surface_exc.value.code == "invalid_auth_surface"

    # Blank reason is rejected without mutating state or appending audit.
    with pytest.raises(AdapterCommandError) as reason_exc:
        await controller.handle(
            path="/commands/adapters/slack/pause",
            method="POST",
            principal=owner,
            payload={"reason": "   "},
        )
    assert reason_exc.value.status_code == 400
    assert reason_exc.value.code == "invalid_reason"
    assert len(controller.audit_receipts) == 0

    paused = await controller.handle(
        path="/commands/adapters/slack/pause",
        method="POST",
        principal=owner,
        payload={"reason": "Planned Slack webhook maintenance"},
    )
    assert paused.mode == "paused"
    assert paused.can_send is False
    assert paused.execution_authority == "none"
    assert paused.audit_receipt_id is not None
    assert paused.audit_receipt_digest is not None
    assert len(controller.audit_receipts) == 1
    assert controller.audit_receipts[0].command == "pause"
    assert controller.audit_receipts[0].previous_mode == "closed"
    assert controller.audit_receipts[0].new_mode == "paused"
    assert controller.audit_receipts[0].execution_authority == "none"

    resumed = await controller.handle(
        path="/commands/adapters/slack/resume",
        method="POST",
        principal=approver,
        payload={"reason": "Slack webhook verified healthy"},
    )
    assert resumed.mode == "closed"
    assert resumed.can_send is True
    assert resumed.revision == 1
    assert resumed.execution_authority == "none"
    assert len(controller.audit_receipts) == 2
    assert controller.audit_receipts[1].command == "resume"
    assert controller.audit_receipts[1].actor_id == "operator:approver-1"

    # Resuming an already closed adapter fails with 409.
    with pytest.raises(AdapterCommandError) as conflict_exc:
        await controller.handle(
            path="/commands/adapters/slack/resume",
            method="POST",
            principal=owner,
            payload={"reason": "duplicate resume"},
        )
    assert conflict_exc.value.status_code == 409
    assert conflict_exc.value.code == "adapter_not_paused_or_open"


async def test_conversation_delivery_panel_route_projects_store_and_progressive_collector() -> None:
    snapshot = ChannelDeliverySnapshot(
        deliveries=(
            _delivery_record("a", state=ChannelDeliveryState.DELIVERED, latency_ms=120),
            _delivery_record(
                "b",
                state=ChannelDeliveryState.DELIVERED,
                attempt_count=3,
                latency_ms=360,
            ),
            _delivery_record(
                "c",
                state=ChannelDeliveryState.AMBIGUOUS,
                attempt_count=2,
                duplicate_risk=True,
                latency_ms=800,
            ),
            _delivery_record(
                "d",
                state=ChannelDeliveryState.ABANDONED,
                attempt_count=4,
                latency_ms=1200,
            ),
        ),
        attempts=(
            ChannelDeliveryAttempt(
                attempt_id="att-1",
                delivery_id="deliv-a",
                sequence=1,
                worker_id="worker-1",
                started_at=NOW,
            ),
            ChannelDeliveryAttempt(
                attempt_id="att-2",
                delivery_id="deliv-b",
                sequence=1,
                worker_id="worker-1",
                started_at=NOW,
            ),
        ),
        acknowledgements=(
            ChannelDeliveryAcknowledgement(
                delivery_id="deliv-a",
                attempt_id="att-1",
                provider_message_id="prov-msg-a",
                acknowledged_at=NOW + timedelta(milliseconds=120),
            ),
        ),
        breakers=(
            ChannelAdapterBreaker(
                adapter_id="slack",
                channel_kind=ChannelKind.SLACK,
                mode=ChannelBreakerMode.CLOSED,
                revision=1,
                updated_at=NOW,
                updated_by="operator:owner-1",
                reason="healthy",
            ),
            ChannelAdapterBreaker(
                adapter_id="teams",
                channel_kind=ChannelKind.TEAMS,
                mode=ChannelBreakerMode.PAUSED,
                revision=2,
                updated_at=NOW,
                updated_by="operator:owner-1",
                reason="maintenance",
            ),
        ),
    )
    collector = BoundedProgressiveConversationCollector(max_samples=100)
    collector.record_turn(
        first_progress_ms=95.0,
        first_confirmed_ms=410.0,
        branch_ms=(60.0, 140.0),
    )
    collector.record_turn(
        first_progress_ms=155.0,
        first_confirmed_ms=590.0,
        branch_ms=(100.0,),
    )

    store = _SnapshotStore(snapshot)
    route = ConversationDeliveryPanelRoute(
        store=store,
        progressive_collector=collector,
        snapshot_limit=150,
    )

    with pytest.raises(PermissionError, match="authenticated principal"):
        await route.get_panel(principal_id=None, roles=frozenset({"reader"}))

    with pytest.raises(PermissionError, match="GET-only"):
        await route.get_panel(
            principal_id="operator:reader-1",
            roles=frozenset({"reader"}),
            method="POST",
        )

    payload = await route.get_panel(
        principal_id="operator:reader-1",
        roles=frozenset({"Reader"}),
    )
    assert store.limits == [150]
    assert payload["read_only"] is True
    assert payload["mutations_available"] is False
    assert payload["execution_authority"] == "none"
    assert payload["delivery_count"] == 4
    assert payload["duplicate_risk_count"] == 1
    assert payload["retry_count"] == 6
    assert payload["abandoned_count"] == 1
    assert payload["attempt_count"] == 2
    assert payload["acknowledgement_count"] == 1
    assert payload["breaker_state_counts"] == {"closed": 1, "open": 0, "paused": 1}

    progressive = payload["progressive"]
    assert isinstance(progressive, dict)
    assert progressive["conversation_count"] == 2
    assert progressive["first_progress_latency"] == {
        "count": 2,
        "average_ms": 125.0,
        "p95_ms": 155.0,
    }

    serialized = json.dumps(payload)
    for forbidden in (
        "confidential-answer",
        "principal-a",
        "scope-a",
        "conv-a",
        "deliv-a",
        "prov-msg-a",
    ):
        assert forbidden not in serialized


async def test_adapter_commands_rejects_unauthenticated_and_unknown_adapter_or_path() -> None:
    store = InMemoryAdapterCommandBreakerStore()
    controller = AdapterCommandController(store=store, clock=lambda: NOW)
    owner = AdapterCommandPrincipal(principal_id="operator:owner-1", roles=frozenset({"Owner"}))

    with pytest.raises(AdapterCommandError) as unauth_exc:
        await controller.handle(
            path="/commands/adapters/slack/status",
            method="GET",
            principal=None,
        )
    assert unauth_exc.value.status_code == 401

    with pytest.raises(AdapterCommandError) as path_exc:
        await controller.handle(
            path="/api/adapters/slack/pause",
            method="POST",
            principal=owner,
            payload={"reason": "wrong path"},
        )
    assert path_exc.value.status_code == 404

    with pytest.raises(AdapterCommandError) as unknown_exc:
        await controller.handle(
            path="/commands/adapters/pagerduty/status",
            method="GET",
            principal=owner,
        )
    assert unknown_exc.value.status_code == 404


async def test_adapter_commands_enforces_adapter_scope_allowlist() -> None:
    store = InMemoryAdapterCommandBreakerStore()
    controller = AdapterCommandController(store=store, clock=lambda: NOW)
    scoped_approver = AdapterCommandPrincipal(
        principal_id="operator:approver-teams-only",
        roles=frozenset({"Approver"}),
        allowed_adapters=frozenset({"teams"}),
    )

    with pytest.raises(AdapterCommandError) as scope_exc:
        await controller.handle(
            path="/commands/adapters/slack/pause",
            method="POST",
            principal=scoped_approver,
            payload={"reason": "out of adapter scope"},
        )
    assert scope_exc.value.status_code == 403
    assert scope_exc.value.code == "adapter_scope_denied"


@pytest.mark.parametrize(
    "forbidden_key",
    ["recipient", "user_id", "channel_id", "conversation_id", "webhook_url", "email"],
)
def test_delivery_panel_recursively_rejects_nested_forbidden_identifier_keys(
    forbidden_key: str,
) -> None:
    from fdai_operator_service.conversation_delivery_panel_route import (
        project_conversation_delivery_panel_payload,
    )

    empty_snapshot = ChannelDeliverySnapshot(
        deliveries=(), attempts=(), acknowledgements=(), breakers=()
    )
    with pytest.raises(ValueError, match="MUST NOT expose identifier key"):
        project_conversation_delivery_panel_payload(
            empty_snapshot,
            progressive={"nested": [{"deep": {forbidden_key: "leaked"}}]},
        )


async def test_adapter_commands_expected_revision_cas_and_panel_digest_and_negative_counts() -> (
    None
):
    from fdai_operator_service.conversation_delivery_panel_route import (
        project_conversation_delivery_panel_payload,
    )

    store = InMemoryAdapterCommandBreakerStore()
    controller = AdapterCommandController(store=store, clock=lambda: NOW)
    owner = AdapterCommandPrincipal(principal_id="operator:owner-1", roles=frozenset({"Owner"}))

    with pytest.raises(AdapterCommandError) as pause_cas_exc:
        await controller.pause(
            principal=owner,
            adapter_id="slack",
            reason="maintenance",
            expected_revision=5,
        )
    assert pause_cas_exc.value.status_code == 409
    assert pause_cas_exc.value.code == "revision_conflict"

    paused = await controller.pause(
        principal=owner,
        adapter_id="slack",
        reason="maintenance",
        expected_revision=0,
    )
    assert paused.revision == 0

    with pytest.raises(AdapterCommandError) as resume_cas_exc:
        await controller.resume(
            principal=owner,
            adapter_id="slack",
            reason="recovered",
            expected_revision=99,
        )
    assert resume_cas_exc.value.status_code == 409
    assert resume_cas_exc.value.code == "revision_conflict"

    resumed = await controller.resume(
        principal=owner,
        adapter_id="slack",
        reason="recovered",
        expected_revision=0,
    )
    assert resumed.revision == 1
    assert resumed.state_digest != paused.state_digest

    empty_snapshot = ChannelDeliverySnapshot(
        deliveries=(), attempts=(), acknowledgements=(), breakers=()
    )
    panel = project_conversation_delivery_panel_payload(empty_snapshot)
    assert str(panel["panel_digest"]).startswith("sha256:")
    assert len(str(panel["panel_digest"])) == 71

    with pytest.raises(ValueError, match="dead_letter_count"):
        project_conversation_delivery_panel_payload(empty_snapshot, dead_letter_count=-1)
    with pytest.raises(ValueError, match="breaker_open_count"):
        project_conversation_delivery_panel_payload(empty_snapshot, breaker_open_count=-1)
