"""Teams and Slack provider rendering across shadow and enforce boundaries."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fdai.core.notifications import (
    InMemoryShadowDeliveryRecorder,
    ShadowNotificationChannel,
)
from fdai.delivery.integration_readiness import integration_projection
from fdai.delivery.notifications import (
    ShadowDeliveryConflictError,
    StateStoreShadowDeliveryRecorder,
    parse_notification_bindings,
    render_slack_payload,
    render_teams_payload,
)
from fdai.runtime.delivery import _build_notification_registry
from fdai.shared.providers.notifications import (
    ChannelAmbiguousError,
    ChannelDeliveryError,
    ChannelKind,
    ChannelMode,
    ChannelUnavailableError,
    Link,
    NotificationChannel,
    NotificationMessage,
    NotificationPayloadRenderer,
    PresentationRejectedError,
    RenderedNotificationPayload,
    Severity,
    TrustTier,
    render_presentation,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _message(
    *,
    title: str = "API latency recovered",
    body_markdown: str = "Rollback completed and verification is in progress.",
    metadata: dict[str, str] | None = None,
    links: tuple[Link, ...] = (),
) -> NotificationMessage:
    return NotificationMessage(
        category="operational_alert",
        trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
        correlation_id="inc-example-latency",
        audit_id="audit-example-1",
        title=title,
        body_markdown=body_markdown,
        severity=Severity.ERROR,
        metadata=metadata or {},
        links=links,
    )


def _payload_json(payload: bytes) -> dict[str, Any]:
    value = json.loads(payload)
    assert isinstance(value, dict)
    return value


def test_teams_renderer_is_bounded_and_preserves_canonical_metadata() -> None:
    envelope = render_presentation(
        _message(
            title="T" * 280,
            body_markdown="B" * 3500,
            metadata={
                "incident_id": "inc-example-latency",
                "responsibility_order": "Huginn -> Forseti -> Thor -> Vidar",
            },
        ),
        channel_id="teams-ops",
    )

    payload = _payload_json(render_teams_payload(envelope).body)
    card = payload["attachments"][0]["content"]
    body = card["body"]
    text_blocks = [item for item in body if item["type"] == "TextBlock"]
    facts = next(item["facts"] for item in body if item["type"] == "FactSet")

    assert card["fallbackText"].startswith("T" * 20)
    assert card["speak"] == card["fallbackText"]
    assert body[0] == {
        "type": "TextBlock",
        "text": "CRITICAL",
        "weight": "Bolder",
        "size": "Small",
        "color": "Attention",
        "horizontalAlignment": "Center",
        "spacing": "None",
    }
    assert text_blocks[1]["size"] == "ExtraLarge"
    assert text_blocks[1]["horizontalAlignment"] == "Center"
    assert len(text_blocks[1]["text"]) == 250
    assert len(text_blocks[2]["text"]) == 3000
    assert text_blocks[1]["text"].endswith(" [truncated]")
    assert text_blocks[2]["text"].endswith(" [truncated]")
    assert next(item for item in body if item["type"] == "FactSet")["separator"] is True
    assert {"title": "incident_id", "value": "inc-example-latency"} in facts
    assert {
        "title": "responsibility_order",
        "value": "Huginn -> Forseti -> Thor -> Vidar",
    } in facts
    assert {"title": "rendering", "value": "truncated: title, body"} in facts
    assert all(action["type"] == "Action.OpenUrl" for action in card.get("actions", ()))


def test_slack_renderer_uses_read_only_links_and_escapes_facts() -> None:
    envelope = render_presentation(
        _message(
            metadata={
                "incident_id": "inc-<example>&",
                "responsibility_order": "Huginn -> Forseti -> Thor -> Vidar",
            },
            links=(Link(label="Runbook | read only", url="https://example.com/runbook"),),
        ),
        channel_id="slack-ops",
    )

    payload = _payload_json(render_slack_payload(envelope).body)
    attachment = payload["attachments"][0]
    blocks = attachment["blocks"]

    assert attachment["color"] == "#E01E5A"
    assert "blocks" not in payload
    assert isinstance(blocks, list)
    assert all(block["type"] != "actions" for block in blocks)
    rendered = json.dumps(blocks)
    assert "inc-&lt;example&gt;&amp;" in rendered
    assert "Runbook &#124; read only" in rendered
    assert "Huginn -&gt; Forseti -&gt; Thor -&gt; Vidar" in rendered
    assert "https://example.com/runbook" in rendered


def test_slack_renderer_chunks_fields_to_provider_limit() -> None:
    envelope = render_presentation(
        _message(metadata={f"key-{index}": f"value-{index}" for index in range(16)}),
        channel_id="slack-ops",
    )

    payload = _payload_json(render_slack_payload(envelope).body)
    field_sections = [
        block["fields"] for block in payload["attachments"][0]["blocks"] if "fields" in block
    ]

    assert [len(fields) for fields in field_sections] == [10, 8]
    assert sum(len(fields) for fields in field_sections) == 18


@pytest.mark.parametrize(
    ("channel_kind", "renderer"),
    [
        (ChannelKind.TEAMS, render_teams_payload),
        (ChannelKind.SLACK, render_slack_payload),
    ],
)
async def test_shadow_channel_records_provider_payload_without_http(
    channel_kind: ChannelKind,
    renderer: NotificationPayloadRenderer,
) -> None:
    recorder = InMemoryShadowDeliveryRecorder()
    channel = ShadowNotificationChannel(
        channel_kind=channel_kind,
        channel_id=f"{channel_kind.value}-ops",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
        recorder=recorder,
        payload_renderer=renderer,
    )

    receipt = await channel.send(_message())

    assert receipt.delivered is True
    assert len(recorder.entries) == 1
    assert recorder.entries[0].rendered_payload is not None
    assert recorder.entries[0].rendered_payload.content_type == "application/json"


async def test_shadow_binding_composes_without_endpoint_or_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "FDAI_NOTIFICATION_BINDINGS_JSON",
        json.dumps(
            {
                "teams-shadow": {
                    "kind": "teams_workflow",
                    "enabled": True,
                    "mode": "shadow",
                    "trust_tiers": ["a2_operational_alert"],
                },
                "slack-shadow": {
                    "kind": "slack_webhook",
                    "enabled": True,
                    "mode": "shadow",
                    "trust_tiers": ["a2_operational_alert"],
                },
            }
        ),
    )
    recorder = InMemoryShadowDeliveryRecorder()

    registry = _build_notification_registry(None, shadow_recorder=recorder)
    teams_receipt = await registry.channels["teams-shadow"].send(_message())
    slack_receipt = await registry.channels["slack-shadow"].send(_message())

    assert teams_receipt.delivered is True
    assert slack_receipt.delivered is True
    assert {entry.channel_id for entry in recorder.entries} == {
        "teams-shadow",
        "slack-shadow",
    }
    payloads = {
        entry.channel_id: _payload_json(entry.rendered_payload.body)
        for entry in recorder.entries
        if entry.rendered_payload is not None
    }
    assert payloads["teams-shadow"]["type"] == "message"
    assert "attachments" in payloads["slack-shadow"]


def test_shadow_bindings_are_visible_in_shared_readiness_projection() -> None:
    bindings = {
        "teams-shadow": {
            "kind": "teams_workflow",
            "enabled": True,
            "mode": "shadow",
            "trust_tiers": ["a2_operational_alert"],
        },
        "slack-shadow": {
            "kind": "slack_webhook",
            "enabled": True,
            "mode": "shadow",
            "trust_tiers": ["a2_operational_alert"],
        },
    }

    rows = {
        str(row["key"]): row
        for row in integration_projection({"FDAI_NOTIFICATION_BINDINGS_JSON": json.dumps(bindings)})
    }

    assert rows["teams-shadow"]["kind"] == "teams_workflow"
    assert rows["teams-shadow"]["ready"] is True
    assert rows["teams-shadow"]["mode"] == "shadow"
    assert rows["slack-shadow"]["kind"] == "slack_webhook"
    assert rows["slack-shadow"]["ready"] is True
    assert rows["slack-shadow"]["mode"] == "shadow"
    assert rows["notification-bindings"]["mode"] == "shadow"


@pytest.mark.parametrize("channel_id", ["", " teams-ops", "teams/ops", "x" * 129])
def test_channel_ids_are_bounded_ascii_identifiers(channel_id: str) -> None:
    raw = json.dumps(
        {
            channel_id: {
                "kind": "slack_webhook",
                "enabled": False,
                "trust_tiers": ["a2_operational_alert"],
            }
        }
    )

    with pytest.raises(ValueError, match="channel_id MUST be 1-128 ASCII"):
        parse_notification_bindings(raw)


async def test_state_store_recorder_is_idempotent_and_rejects_content_conflicts() -> None:
    store = InMemoryStateStore()
    recorder = StateStoreShadowDeliveryRecorder(store)
    channel = ShadowNotificationChannel(
        channel_kind=ChannelKind.TEAMS,
        channel_id="teams-shadow",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
        recorder=recorder,
        payload_renderer=render_teams_payload,
    )

    receipt = await channel.send(_message())
    await channel.send(_message())
    stored = await store.read_state(f"notification-shadow:{receipt.provider_message_id}")

    assert stored is not None
    assert stored["channel_id"] == "teams-shadow"
    assert stored["rendered_payload"]["content_type"] == "application/json"

    with pytest.raises(ShadowDeliveryConflictError, match="different bounded content"):
        await channel.send(_message(body_markdown="A different bounded body."))


async def test_in_memory_recorder_rejects_content_conflicts() -> None:
    recorder = InMemoryShadowDeliveryRecorder()
    channel = ShadowNotificationChannel(
        channel_kind=ChannelKind.SLACK,
        channel_id="slack-shadow",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
        recorder=recorder,
        payload_renderer=render_slack_payload,
    )

    await channel.send(_message())
    with pytest.raises(ShadowDeliveryConflictError, match="different bounded content"):
        await channel.send(_message(body_markdown="A different bounded body."))


async def test_shadow_channel_rejects_unbounded_injected_renderer_payload() -> None:
    recorder = InMemoryShadowDeliveryRecorder()

    def oversized_renderer(_: object) -> RenderedNotificationPayload:
        return RenderedNotificationPayload(
            content_type="application/json",
            body=b"x" * (64 * 1024 + 1),
        )

    channel = ShadowNotificationChannel(
        channel_kind=ChannelKind.SLACK,
        channel_id="slack-shadow",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
        recorder=recorder,
        payload_renderer=oversized_renderer,
    )

    with pytest.raises(PresentationRejectedError, match="shadow record limit"):
        await channel.send(_message())
    assert recorder.entries == ()


def test_enforce_binding_still_requires_endpoint_and_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = json.dumps(
        {
            "slack-enforce": {
                "kind": "slack_webhook",
                "enabled": True,
                "trust_tiers": ["a2_operational_alert"],
                "endpoint_env": "FDAI_SLACK_OPS_WEBHOOK_URL",
            }
        }
    )
    monkeypatch.setenv("FDAI_NOTIFICATION_BINDINGS_JSON", raw)
    monkeypatch.setenv("FDAI_SLACK_OPS_WEBHOOK_URL", "https://hooks.slack.example/ops")

    spec = parse_notification_bindings(raw)[0]
    assert spec.mode is ChannelMode.ENFORCE
    with pytest.raises(RuntimeError, match="requires an HTTP client"):
        _build_notification_registry(None)


async def test_secret_like_content_is_rejected_before_provider_transport() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    from fdai.delivery.notifications import SlackWebhookChannel, SlackWebhookConfig

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        channel = SlackWebhookChannel(
            config=SlackWebhookConfig(
                channel_id="slack-enforce",
                webhook_url="https://hooks.slack.example/ops",
                trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
            ),
            http_client=client,
        )
        with pytest.raises(PresentationRejectedError, match="secret-like"):
            await channel.send(_message(body_markdown=": ".join(("api_key", "synthetic-value"))))

    assert calls == 0


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ConnectError("connect"), ChannelUnavailableError),
        (httpx.ReadTimeout("response lost"), ChannelAmbiguousError),
    ],
)
async def test_slack_transport_distinguishes_unavailable_from_ambiguous(
    error: httpx.HTTPError,
    expected: type[Exception],
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise error

    from fdai.delivery.notifications import SlackWebhookChannel, SlackWebhookConfig

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        channel = SlackWebhookChannel(
            config=SlackWebhookConfig(
                channel_id="slack-enforce",
                webhook_url="https://hooks.slack.example/ops",
                trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
            ),
            http_client=client,
        )
        with pytest.raises(expected):
            await channel.send(_message())


@pytest.mark.parametrize("provider", ["teams", "slack"])
async def test_provider_rejection_does_not_echo_response_body(provider: str) -> None:
    reflected = "reflected-sensitive-body"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=reflected)

    from fdai.delivery.notifications import (
        SlackWebhookChannel,
        SlackWebhookConfig,
        TeamsWebhookChannel,
        TeamsWebhookConfig,
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        channel: NotificationChannel
        if provider == "teams":
            channel = TeamsWebhookChannel(
                config=TeamsWebhookConfig(
                    channel_id="teams-enforce",
                    webhook_url="https://flow.example.com/ops",
                    trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
                ),
                http_client=client,
            )
        else:
            channel = SlackWebhookChannel(
                config=SlackWebhookConfig(
                    channel_id="slack-enforce",
                    webhook_url="https://hooks.slack.example/ops",
                    trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
                ),
                http_client=client,
            )

        with pytest.raises(ChannelDeliveryError, match="HTTP 400") as captured:
            await channel.send(_message())

    assert reflected not in str(captured.value)
