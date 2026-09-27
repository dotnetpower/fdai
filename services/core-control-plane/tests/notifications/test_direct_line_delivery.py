"""Direct Line custom-channel bindings, composition, routing, receipts, and replay."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fdai.core.notifications import (
    ChannelBinding,
    ChannelDeliveryState,
    ChannelRegistry,
    InMemoryNotificationDeliveryStore,
    InMemoryShadowDeliveryRecorder,
    NotificationRouter,
    RouteOutcome,
    ShadowNotificationChannel,
    load_matrix_from_mapping,
)
from fdai.delivery.integration_readiness import integration_projection
from fdai.delivery.notifications import (
    DirectLineConfig,
    DirectLineCredential,
    DirectLineNotificationChannel,
    NotificationBindingKind,
    NotificationDeliveryReceiptApplier,
    StateStoreShadowDeliveryRecorder,
    parse_notification_bindings,
    render_direct_line_payload,
    static_direct_line_credential,
)
from fdai.delivery.notifications.direct_line import ACTIVITY_DIGEST_PREFIX
from fdai.runtime.delivery import _build_notification_registry, _build_notification_router
from fdai.runtime.notification_direct_line import require_fanout_for_governed_direct_line
from fdai.shared.providers.notifications import (
    ChannelKind,
    ChannelMode,
    NotificationChannel,
    NotificationMessage,
    TrustTier,
)
from fdai.shared.providers.testing.notifications import FakeHilEscalationSink
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.notification_receipt import NotificationDeliveryReceipt

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
CHANNEL = "direct-line-ops"
ENDPOINT = "https://directline.example.com"
CONVERSATION = "conversation-example-1"
CREDENTIAL = "-".join(("synthetic", "direct", "line", "credential"))
ACTIVITY_ID = f"{CONVERSATION}|0000001"
ACCEPTED_ID = f"{ACTIVITY_DIGEST_PREFIX}{hashlib.sha256(ACTIVITY_ID.encode()).hexdigest()}"
ENV = {
    "FDAI_DIRECT_LINE_OPS_ENDPOINT": ENDPOINT,
    "FDAI_DIRECT_LINE_OPS_CONVERSATION_ID": CONVERSATION,
    "FDAI_DIRECT_LINE_OPS_SECRET": CREDENTIAL,
}
GOVERNED = {
    "kind": "direct_line",
    "enabled": True,
    "mode": "enforce",
    "trust_tiers": ["a2_operational_alert", "a4_digest"],
    "endpoint_env": "FDAI_DIRECT_LINE_OPS_ENDPOINT",
    "conversation_id_env": "FDAI_DIRECT_LINE_OPS_CONVERSATION_ID",
    "secret_env": "FDAI_DIRECT_LINE_OPS_SECRET",
}
REHEARSAL = {"kind": "direct_line", "enabled": True, "trust_tiers": ["a2_operational_alert"]}
CORE_ROOT = Path(__file__).resolve().parents[2] / "src" / "fdai" / "core"


def _message() -> NotificationMessage:
    return NotificationMessage(
        category="operational_alert",
        trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
        correlation_id="inc-example-latency",
        audit_id="audit-example-1",
        title="API latency recovered",
        body_markdown="Rollback completed and verification is in progress.",
    )


def _bindings(
    monkeypatch: pytest.MonkeyPatch,
    spec: Mapping[str, Any],
    *,
    channel_id: str = CHANNEL,
) -> None:
    for name in ("FDAI_TEAMS_OPS_ENDPOINT", "FDAI_SLACK_OPS_WEBHOOK_URL", "FDAI_EMAIL_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FDAI_NOTIFICATION_BINDINGS_JSON", json.dumps({channel_id: dict(spec)}))


def _router(
    channel: NotificationChannel | None,
    *,
    store: InMemoryNotificationDeliveryStore,
    binding: ChannelBinding | None = None,
    max_attempts: int = 3,
) -> tuple[NotificationRouter, InMemoryStateStore, FakeHilEscalationSink]:
    audit = InMemoryStateStore()
    sink = FakeHilEscalationSink()
    channels = {CHANNEL: channel} if channel is not None else {}
    bindings = {CHANNEL: binding} if binding is not None else {}
    matrix = load_matrix_from_mapping(
        {
            "matrix": {
                "version": 1,
                "default_route": "operational_alert",
                "routes": {
                    "operational_alert": {
                        "trust_tier": "a2_operational_alert",
                        "delivery_mode": "fanout",
                        "channels": [CHANNEL],
                    }
                },
            }
        }
    )
    router = NotificationRouter(
        matrix=matrix,
        registry=ChannelRegistry(channels=channels, bindings=bindings),
        audit_store=audit,
        hil_sink=sink,
        delivery_store=store,
        max_attempts=max_attempts,
        retry_backoff_seconds=0,
    )
    return router, audit, sink


def _governed(client: httpx.AsyncClient, credential: DirectLineCredential | None = None) -> Any:
    async def provider() -> DirectLineCredential:
        return credential or DirectLineCredential(value=CREDENTIAL)

    return DirectLineNotificationChannel(
        config=DirectLineConfig(
            channel_id=CHANNEL,
            endpoint=ENDPOINT,
            conversation_id=CONVERSATION,
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
        ),
        http_client=client,
        credential_provider=provider,
        clock=lambda: NOW,
    )


def _client(handler: Callable[[httpx.Request], Any], requests: list[httpx.Request]) -> Any:
    def recording(request: httpx.Request) -> Any:
        requests.append(request)
        return handler(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(recording))


def test_direct_line_binding_defaults_to_rehearsal_without_references() -> None:
    spec = parse_notification_bindings(json.dumps({CHANNEL: REHEARSAL}))[0]

    assert spec.kind is NotificationBindingKind.DIRECT_LINE
    assert spec.mode is ChannelMode.SHADOW
    assert (spec.endpoint_env, spec.conversation_id_env, spec.secret_env) == (None, None, None)


@pytest.mark.parametrize("missing", ["endpoint_env", "conversation_id_env", "secret_env"])
def test_governed_binding_requires_every_protected_reference(missing: str) -> None:
    spec = {key: value for key, value in GOVERNED.items() if key != missing}

    with pytest.raises(ValueError, match="requires endpoint, conversation, and secret"):
        parse_notification_bindings(json.dumps({CHANNEL: spec}))


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"secret_env": "FDAI_DIRECT_LINE_OPS_ENDPOINT"}, "distinct environment references"),
        ({"auth_mode": "anyone"}, "does not support fields"),
        ({"identity_client_id_env": "FDAI_NOTIFICATION_MI_CLIENT_ID"}, "does not support"),
        ({"trust_tiers": ["a1_hil_approval"]}, "a1_hil_approval"),
        ({"trust_tiers": ["a2_operational_alert", "a3_chat_command"]}, "a3_chat_command"),
        ({"secret_env": "lower-case"}, "MUST name an environment variable"),
    ],
)
def test_direct_line_binding_rejects_unsafe_shapes(overrides: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        parse_notification_bindings(json.dumps({CHANNEL: {**GOVERNED, **overrides}}))


def test_other_binding_kinds_reject_direct_line_references() -> None:
    raw = {
        "kind": "slack_webhook",
        "enabled": False,
        "trust_tiers": ["a2_operational_alert"],
        "secret_env": "FDAI_DIRECT_LINE_OPS_SECRET",
    }

    with pytest.raises(ValueError, match="does not support fields"):
        parse_notification_bindings(json.dumps({"slack-ops": raw}))


async def test_rehearsal_composes_without_values_and_records_zero_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bindings(monkeypatch, REHEARSAL)
    requests: list[httpx.Request] = []
    recorder = InMemoryShadowDeliveryRecorder()
    async with _client(lambda _: httpx.Response(200), requests) as client:
        registry = _build_notification_registry(client, shadow_recorder=recorder)
        channel = registry.channels[CHANNEL]
        first = await channel.send(_message())
        second = await channel.send(_message())

    assert isinstance(channel, ShadowNotificationChannel)
    assert channel.channel_kind is ChannelKind.DIRECT_LINE
    assert first.delivered is True
    assert first.provider_message_id == second.provider_message_id
    assert requests == []
    assert len(recorder.entries) == 1
    payload = recorder.entries[0].rendered_payload
    assert payload is not None
    assert json.loads(payload.body)["channelData"]["fdai"]["read_only"] is True


async def test_rehearsal_record_is_bounded_auditable_and_value_free() -> None:
    store = InMemoryStateStore()
    channel = ShadowNotificationChannel(
        channel_kind=ChannelKind.DIRECT_LINE,
        channel_id=CHANNEL,
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
        recorder=StateStoreShadowDeliveryRecorder(store),
        payload_renderer=render_direct_line_payload,
    )

    receipt = await channel.send(_message())
    stored = await store.read_state(f"notification-shadow:{receipt.provider_message_id}")

    assert stored is not None
    assert stored["channel_id"] == CHANNEL
    assert stored["audit_id"] == "audit-example-1"
    assert stored["trust_tier"] == "a2_operational_alert"
    activity = json.loads(base64.b64decode(stored["rendered_payload"]["body_base64"]))
    assert activity["type"] == "message"
    serialized = json.dumps(stored)
    assert all(value not in serialized for value in ENV.values())


def test_governed_binding_resolves_protected_references(monkeypatch: pytest.MonkeyPatch) -> None:
    _bindings(monkeypatch, GOVERNED)
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)

    registry = _build_notification_registry(httpx.AsyncClient())

    assert isinstance(registry.channels[CHANNEL], DirectLineNotificationChannel)
    assert registry.bindings[CHANNEL].configured is True
    assert CREDENTIAL not in repr(registry.channels[CHANNEL]._config)


@pytest.mark.parametrize(
    ("overrides", "client", "match"),
    [
        ({"FDAI_DIRECT_LINE_OPS_SECRET": ""}, True, "requires environment variable"),
        ({"FDAI_DIRECT_LINE_OPS_ENDPOINT": "unconfigured"}, True, "placeholder"),
        ({"FDAI_DIRECT_LINE_OPS_SECRET": "placeholder"}, True, "placeholder"),
        ({"FDAI_DIRECT_LINE_OPS_CONVERSATION_ID": "unconfigured"}, True, "placeholder"),
        ({"FDAI_DIRECT_LINE_OPS_CONVERSATION_ID": "bad/id"}, True, "is invalid"),
        ({"FDAI_DIRECT_LINE_OPS_SECRET": "has space"}, True, "is invalid"),
        ({}, False, "requires an HTTP client"),
    ],
)
def test_governed_binding_fails_startup_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, str],
    client: bool,
    match: str,
) -> None:
    _bindings(monkeypatch, GOVERNED)
    for name, value in {**ENV, **overrides}.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match=match) as caught:
        _build_notification_registry(httpx.AsyncClient() if client else None)

    assert CREDENTIAL not in str(caught.value)
    assert CONVERSATION not in str(caught.value)


async def test_disabled_binding_is_excluded_and_escalates_without_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bindings(monkeypatch, {**GOVERNED, "enabled": False})
    registry = _build_notification_registry(None)
    store = InMemoryNotificationDeliveryStore()
    router, _, sink = _router(None, store=store, binding=registry.bindings[CHANNEL])

    result = await router.dispatch(_message())

    assert CHANNEL not in registry.channels
    assert result.outcome is RouteOutcome.NO_ELIGIBLE_CHANNELS
    assert result.excluded_channels == {CHANNEL: "disabled"}
    assert len(sink.entries) == 1


async def test_unconfigured_route_target_escalates_without_sending() -> None:
    router, _, sink = _router(None, store=InMemoryNotificationDeliveryStore())

    result = await router.dispatch(_message())

    assert result.outcome is RouteOutcome.NO_ELIGIBLE_CHANNELS
    assert result.excluded_channels == {CHANNEL: "configuration_invalid"}
    assert len(sink.entries) == 1


async def test_governed_delivery_writes_intent_before_transport_and_accepts_on_ack() -> None:
    store = InMemoryNotificationDeliveryStore()
    observed: list[ChannelDeliveryState] = []
    requests: list[httpx.Request] = []

    async def provider_ack(_: httpx.Request) -> httpx.Response:
        plan = await store.snapshot(audit_id="audit-example-1", now=NOW)
        observed.extend(item.state for item in plan.deliveries)
        assert plan.deliveries[0].attempts == 1
        assert plan.deliveries[0].lease_until is not None
        return httpx.Response(200, json={"id": ACTIVITY_ID})

    async with _client(provider_ack, requests) as client:
        router, audit, sink = _router(_governed(client), store=store)
        result = await router.dispatch(_message())

    assert observed == [ChannelDeliveryState.SENDING]
    assert result.deliveries[0].state is ChannelDeliveryState.ACCEPTED
    assert result.deliveries[0].provider_message_id == ACCEPTED_ID
    assert result.outcome is RouteOutcome.FAILED_ALL
    assert result.terminal is False
    assert len(requests) == 1
    assert tuple(sink.entries) == ()
    audit_text = json.dumps([item["entry"] for item in audit.audit_entries])
    assert all(value not in audit_text for value in ENV.values())


def _accepting(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"id": ACTIVITY_ID})


async def test_publication_receipt_promotes_acceptance_and_replay_never_resends() -> None:
    store = InMemoryNotificationDeliveryStore()
    requests: list[httpx.Request] = []
    async with _client(_accepting, requests) as client:
        router, audit, _ = _router(_governed(client), store=store)
        await router.dispatch(_message())
        applier = NotificationDeliveryReceiptApplier(
            delivery_store=store, audit_store=audit, clock=lambda: NOW
        )
        record = await applier.apply(
            NotificationDeliveryReceipt(
                audit_id="audit-example-1",
                channel_id=CHANNEL,
                publication_result="published",
                observed_at=NOW,
                provider_message_id=ACCEPTED_ID,
            )
        )
        replayed = await router.dispatch(_message())

    assert record.state is ChannelDeliveryState.DELIVERED
    assert record.provider_message_id == ACCEPTED_ID
    assert replayed.outcome is RouteOutcome.DELIVERED_ALL
    assert replayed.terminal is True
    assert len(requests) == 1


async def test_lost_acknowledgement_is_ambiguous_and_never_resent() -> None:
    store = InMemoryNotificationDeliveryStore()
    requests: list[httpx.Request] = []

    def lost(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("response lost")

    async with _client(lost, requests) as client:
        router, _, _ = _router(_governed(client), store=store)
        first = await router.dispatch(_message())
        await router.dispatch(_message())

    assert first.deliveries[0].state is ChannelDeliveryState.AMBIGUOUS
    assert len(requests) == 1


@pytest.mark.parametrize(
    ("credential", "status", "expected_requests"),
    [
        (None, 401, 3),
        (None, 403, 3),
        (DirectLineCredential(value=CREDENTIAL, expires_at=NOW), 200, 0),
    ],
)
async def test_rejected_or_expired_credentials_are_bounded_then_escalated(
    credential: DirectLineCredential | None,
    status: int,
    expected_requests: int,
) -> None:
    store = InMemoryNotificationDeliveryStore()
    requests: list[httpx.Request] = []

    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"id": ACTIVITY_ID})

    async with _client(respond, requests) as client:
        router, _, sink = _router(_governed(client, credential), store=store)
        result = await router.dispatch(_message())

    assert result.deliveries[0].state is ChannelDeliveryState.ABANDONED
    assert result.deliveries[0].attempts == 3
    assert result.outcome is RouteOutcome.FAILED_ALL
    assert result.terminal is True
    assert len(requests) == expected_requests
    assert len(sink.entries) == 1
    assert CREDENTIAL not in (result.deliveries[0].error or "")


async def test_transport_failure_is_retried_within_the_attempt_bound() -> None:
    store = InMemoryNotificationDeliveryStore()
    requests: list[httpx.Request] = []
    responses: list[Any] = [httpx.ConnectError("down"), httpx.Response(200, json={"id": "a-2"})]

    def flaky(_: httpx.Request) -> httpx.Response:
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async with _client(flaky, requests) as client:
        router, _, _ = _router(_governed(client), store=store)
        result = await router.dispatch(_message())

    assert result.deliveries[0].state is ChannelDeliveryState.ACCEPTED
    assert result.deliveries[0].attempts == 2
    assert len(requests) == 2


@pytest.mark.parametrize("max_attempts", [2, 3])
async def test_throttling_posts_are_bounded_by_the_router_attempt_ceiling(
    max_attempts: int,
) -> None:
    store = InMemoryNotificationDeliveryStore()
    requests: list[httpx.Request] = []

    def throttled(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "30"})

    async with _client(throttled, requests) as client:
        router, _, sink = _router(_governed(client), store=store, max_attempts=max_attempts)
        first = await router.dispatch(_message())
        escalations = len(sink.entries)
        replayed = await router.dispatch(_message())

    assert len(requests) == max_attempts
    assert first.deliveries[0].state is ChannelDeliveryState.ABANDONED
    assert first.deliveries[0].attempts == max_attempts
    assert replayed.deliveries[0].state is ChannelDeliveryState.ABANDONED
    assert escalations == 1


async def test_throttling_recovers_through_one_router_retry() -> None:
    store = InMemoryNotificationDeliveryStore()
    requests: list[httpx.Request] = []
    responses = [httpx.Response(429), httpx.Response(200, json={"id": ACTIVITY_ID})]

    async with _client(lambda _: responses.pop(0), requests) as client:
        router, _, _ = _router(_governed(client), store=store)
        result = await router.dispatch(_message())

    assert result.deliveries[0].state is ChannelDeliveryState.ACCEPTED
    assert result.deliveries[0].attempts == 2
    assert len(requests) == 2


@pytest.mark.parametrize("status", [500, 502, 504])
async def test_relay_reflected_failures_are_ambiguous_and_never_resent(status: int) -> None:
    store = InMemoryNotificationDeliveryStore()
    requests: list[httpx.Request] = []

    def relay_failed(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status)

    async with _client(relay_failed, requests) as client:
        router, _, sink = _router(_governed(client), store=store)
        first = await router.dispatch(_message())
        escalations = len(sink.entries)
        replayed = await router.dispatch(_message())

    assert len(requests) == 1
    assert first.deliveries[0].state is ChannelDeliveryState.AMBIGUOUS
    assert first.deliveries[0].attempts == 1
    assert replayed.deliveries[0].state is ChannelDeliveryState.AMBIGUOUS
    assert first.outcome is RouteOutcome.FAILED_ALL
    assert first.terminal is True
    assert escalations == 1


def _composition_env(monkeypatch: pytest.MonkeyPatch, channel_id: str) -> None:
    _bindings(monkeypatch, GOVERNED, channel_id=channel_id)
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    for name in ("FDAI_STATE_STORE_DSN", "FDAI_CATALOG_ROOT"):
        monkeypatch.delenv(name, raising=False)


def test_router_composition_refuses_governed_direct_line_on_a_shipped_failover_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _composition_env(monkeypatch, "teams-hil-standby")

    with pytest.raises(RuntimeError, match="declare delivery_mode: fanout") as caught:
        _build_notification_router(InMemoryStateStore(), http_client=httpx.AsyncClient())

    assert "hil_approval" in str(caught.value)
    assert CREDENTIAL not in str(caught.value)


def test_router_composition_accepts_governed_direct_line_on_a_shipped_fanout_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _composition_env(monkeypatch, "teams-ops-prd")

    router = _build_notification_router(InMemoryStateStore(), http_client=httpx.AsyncClient())

    assert isinstance(router._registry.resolve("teams-ops-prd"), DirectLineNotificationChannel)


def test_readiness_rows_report_state_without_values() -> None:
    placeholder_secret = {**GOVERNED, "secret_env": "FDAI_DIRECT_LINE_DIGEST_SECRET"}
    env = {
        **ENV,
        "FDAI_DIRECT_LINE_DIGEST_SECRET": "unconfigured",
        "FDAI_NOTIFICATION_BINDINGS_JSON": json.dumps(
            {
                "direct-line-rehearsal": REHEARSAL,
                "direct-line-governed": GOVERNED,
                "direct-line-placeholder": placeholder_secret,
            }
        ),
    }

    rows = {str(row["key"]): row for row in integration_projection(env)}

    assert rows["direct-line-rehearsal"]["kind"] == "direct_line"
    assert rows["direct-line-rehearsal"]["mode"] == "shadow"
    assert rows["direct-line-rehearsal"]["ready"] is True
    assert rows["direct-line-governed"]["mode"] == "enforce"
    assert rows["direct-line-governed"]["ready"] is True
    assert rows["direct-line-placeholder"]["ready"] is False
    assert rows["notification-bindings"]["ready"] is True
    serialized = json.dumps(list(rows.values()))
    assert all(value not in serialized for value in ENV.values())


def test_bindings_projection_flags_missing_protected_references() -> None:
    env = {
        "FDAI_DIRECT_LINE_OPS_ENDPOINT": ENDPOINT,
        "FDAI_NOTIFICATION_BINDINGS_JSON": json.dumps({CHANNEL: GOVERNED}),
    }

    rows = {str(row["key"]): row for row in integration_projection(env)}

    assert rows["notification-bindings"]["ready"] is False
    assert rows[CHANNEL]["ready"] is False


@pytest.mark.parametrize(
    ("delivery_mode", "governed", "refused"),
    [("failover", True, True), ("failover", False, False), ("fanout", True, False)],
)
def test_governed_direct_line_requires_a_fanout_route(
    delivery_mode: str, governed: bool, refused: bool
) -> None:
    route: dict[str, Any] = {"trust_tier": "a2_operational_alert", "delivery_mode": delivery_mode}
    route.update({"channels": [CHANNEL]} if delivery_mode == "fanout" else {"primary": CHANNEL})
    matrix = load_matrix_from_mapping(
        {
            "matrix": {
                "version": 1,
                "default_route": "operational_alert",
                "routes": {"operational_alert": route},
            }
        }
    )
    channel: NotificationChannel = (
        _governed(httpx.AsyncClient())
        if governed
        else ShadowNotificationChannel(
            channel_kind=ChannelKind.DIRECT_LINE,
            channel_id=CHANNEL,
            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
            recorder=InMemoryShadowDeliveryRecorder(),
            payload_renderer=render_direct_line_payload,
        )
    )
    registry = ChannelRegistry(channels={CHANNEL: channel})

    if refused:
        with pytest.raises(RuntimeError, match="declare delivery_mode: fanout"):
            require_fanout_for_governed_direct_line(matrix, registry)
    else:
        require_fanout_for_governed_direct_line(matrix, registry)


def test_core_decision_logic_has_no_direct_line_branch_or_provider_import() -> None:
    name = re.compile(r"direct[_ ]?line", re.IGNORECASE)
    provider_import = re.compile(r"^\s*(?:from|import)\s+fdai\.delivery\b", re.MULTILINE)
    offenders = [
        path.relative_to(CORE_ROOT).as_posix()
        for path in CORE_ROOT.rglob("*.py")
        if name.search(text := path.read_text(encoding="utf-8")) or provider_import.search(text)
    ]

    assert offenders == []


async def test_static_credential_provider_returns_a_non_expiring_secret() -> None:
    credential = await static_direct_line_credential(CREDENTIAL)()

    assert credential.value == CREDENTIAL
    assert credential.expires_at is None
