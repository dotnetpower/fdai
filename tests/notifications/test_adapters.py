"""Notification adapter tests — HTTP-level round-trip via httpx.MockTransport.

Covers the six delivery adapters + the shared ``_http.post_json`` helper.
Each adapter test mimics the pattern used by
:mod:`tests.delivery.gitops_pr.test_adapter`: a small mock transport
records the request the adapter would send in production, so we assert
on the *contract* (URL, headers, payload shape) without touching a real
Teams / Slack / ACS endpoint.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from aiopspilot.delivery.notifications import (
    AzureCommunicationEmailChannel,
    AzureCommunicationEmailConfig,
    AzureCommunicationSmsChannel,
    AzureCommunicationSmsConfig,
    GenericWebhookChannel,
    GenericWebhookConfig,
    PagerDutyEventsV2Channel,
    PagerDutyEventsV2Config,
    SlackWebhookChannel,
    SlackWebhookConfig,
    TeamsWebhookChannel,
    TeamsWebhookConfig,
)
from aiopspilot.delivery.notifications._http import post_json, truncate
from aiopspilot.shared.providers.notifications import (
    ChannelDeliveryError,
    ChannelUnavailableError,
    NotificationMessage,
    Severity,
    TrustTier,
)
from aiopspilot.shared.providers.notifications.base import Link


def _message(**overrides: Any) -> NotificationMessage:
    defaults: dict[str, Any] = {
        "category": "operational_alert",
        "trust_tier": TrustTier.A2_OPERATIONAL_ALERT,
        "correlation_id": "cid-1",
        "title": "DLQ depth",
        "body_markdown": "Depth = 42",
        "severity": Severity.ERROR,
        "audit_id": "audit-1",
        "links": (Link(label="Runbook", url="https://example.com/rb/1"),),
        "metadata": {"tenant": "example"},
    }
    defaults.update(overrides)
    return NotificationMessage(**defaults)


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# _http helpers
# ---------------------------------------------------------------------------


class TestHttpHelper:
    def test_truncate_leaves_short_text_alone(self) -> None:
        assert truncate("hello") == "hello"

    def test_truncate_snips_long_text_with_marker(self) -> None:
        text = "a" * 700
        result = truncate(text)
        assert result.endswith("truncated 188 bytes>")
        assert len(result) < len(text)

    async def test_post_json_returns_status_and_body_on_2xx(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="ok")

        async with _client(handler) as http:
            status, body = await post_json(
                client=http,
                url="https://example.com/x",
                payload={"a": 1},
                timeout_seconds=1.0,
            )
        assert status == 200
        assert body == "ok"

    async def test_post_json_raises_delivery_error_on_4xx(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="bad")

        async with _client(handler) as http:
            with pytest.raises(ChannelDeliveryError, match="HTTP 400"):
                await post_json(
                    client=http,
                    url="https://example.com/x",
                    payload={},
                    timeout_seconds=1.0,
                )

    async def test_post_json_raises_unavailable_on_transport_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        async with _client(handler) as http:
            with pytest.raises(ChannelUnavailableError, match="transport error"):
                await post_json(
                    client=http,
                    url="https://example.com/x",
                    payload={},
                    timeout_seconds=1.0,
                )


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------


class TestTeamsAdapter:
    def test_construction_guards(self) -> None:
        good_http = httpx.AsyncClient()
        with pytest.raises(ValueError, match="timeout_seconds"):
            TeamsWebhookChannel(
                config=TeamsWebhookConfig(
                    channel_id="t",
                    webhook_url="https://example.com/wh",
                    trust_tiers=frozenset(),
                    timeout_seconds=0,
                ),
                http_client=good_http,
            )
        with pytest.raises(ValueError, match="webhook_url"):
            TeamsWebhookChannel(
                config=TeamsWebhookConfig(
                    channel_id="t",
                    webhook_url="",
                    trust_tiers=frozenset(),
                ),
                http_client=good_http,
            )

    async def test_posts_adaptive_card(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, text="1")

        async with _client(handler) as http:
            adapter = TeamsWebhookChannel(
                config=TeamsWebhookConfig(
                    channel_id="teams-1",
                    webhook_url="https://outlook.example.com/wh",
                    trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
                ),
                http_client=http,
            )
            receipt = await adapter.send(_message())

        assert receipt.delivered is True
        assert receipt.channel_id == "teams-1"
        assert len(captured) == 1
        import json as _json

        body = _json.loads(captured[0].content.decode("utf-8"))
        assert body["type"] == "message"
        card = body["attachments"][0]["content"]
        assert card["type"] == "AdaptiveCard"
        assert any(b.get("text") == "DLQ depth" for b in card["body"])
        # Severity ERROR maps to Attention color.
        header = next(b for b in card["body"] if b.get("weight") == "Bolder")
        assert header["color"] == "Attention"

    async def test_no_facts_no_actions_when_absent(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        async with _client(handler) as http:
            adapter = TeamsWebhookChannel(
                config=TeamsWebhookConfig(
                    channel_id="teams-2",
                    webhook_url="https://outlook.example.com/wh",
                    trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
                ),
                http_client=http,
            )
            # Empty correlation_id and no links.
            msg = NotificationMessage(
                category="x",
                trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
                correlation_id="",
                title="t",
                body_markdown="b",
            )
            await adapter.send(msg)

    async def test_all_severities_map(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        async with _client(handler) as http:
            adapter = TeamsWebhookChannel(
                config=TeamsWebhookConfig(
                    channel_id="teams-3",
                    webhook_url="https://outlook.example.com/wh",
                    trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
                ),
                http_client=http,
            )
            for sev in Severity:
                await adapter.send(_message(severity=sev))


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------


class TestSlackAdapter:
    def test_construction_guards(self) -> None:
        good_http = httpx.AsyncClient()
        with pytest.raises(ValueError, match="timeout_seconds"):
            SlackWebhookChannel(
                config=SlackWebhookConfig(
                    channel_id="s",
                    webhook_url="https://hooks.slack.example/wh",
                    trust_tiers=frozenset(),
                    timeout_seconds=0,
                ),
                http_client=good_http,
            )
        with pytest.raises(ValueError, match="webhook_url"):
            SlackWebhookChannel(
                config=SlackWebhookConfig(
                    channel_id="s",
                    webhook_url="",
                    trust_tiers=frozenset(),
                ),
                http_client=good_http,
            )

    async def test_posts_block_kit(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, text="ok")

        async with _client(handler) as http:
            adapter = SlackWebhookChannel(
                config=SlackWebhookConfig(
                    channel_id="slack-1",
                    webhook_url="https://hooks.slack.example/wh",
                    trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
                ),
                http_client=http,
            )
            receipt = await adapter.send(_message())

        assert receipt.delivered is True
        import json as _json

        body = _json.loads(captured[0].content.decode("utf-8"))
        assert "blocks" in body
        assert body["blocks"][0]["type"] == "header"
        # Link block appended.
        assert any(b["type"] == "actions" for b in body["blocks"])

    async def test_all_severities_render(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        async with _client(handler) as http:
            adapter = SlackWebhookChannel(
                config=SlackWebhookConfig(
                    channel_id="slack-2",
                    webhook_url="https://hooks.slack.example/wh",
                    trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
                ),
                http_client=http,
            )
            for sev in Severity:
                await adapter.send(
                    _message(severity=sev, correlation_id="", audit_id=None, links=())
                )


# ---------------------------------------------------------------------------
# Email (Azure Communication Services)
# ---------------------------------------------------------------------------


class TestEmailAdapter:
    def test_construction_guards(self) -> None:
        http = httpx.AsyncClient()
        with pytest.raises(ValueError, match="timeout_seconds"):
            AzureCommunicationEmailChannel(
                config=AzureCommunicationEmailConfig(
                    channel_id="e",
                    endpoint="https://acs.example",
                    recipient_addresses=("ops@example.com",),
                    timeout_seconds=0,
                ),
                http_client=http,
            )
        with pytest.raises(ValueError, match="endpoint"):
            AzureCommunicationEmailChannel(
                config=AzureCommunicationEmailConfig(
                    channel_id="e",
                    endpoint="",
                    recipient_addresses=("ops@example.com",),
                ),
                http_client=http,
            )
        with pytest.raises(ValueError, match="recipient_addresses"):
            AzureCommunicationEmailChannel(
                config=AzureCommunicationEmailConfig(
                    channel_id="e",
                    endpoint="https://acs.example",
                    recipient_addresses=(),
                ),
                http_client=http,
            )
        with pytest.raises(ValueError, match="A1 approvals"):
            AzureCommunicationEmailChannel(
                config=AzureCommunicationEmailConfig(
                    channel_id="e",
                    endpoint="https://acs.example",
                    recipient_addresses=("ops@example.com",),
                    trust_tiers=frozenset({TrustTier.A1_HIL_APPROVAL}),
                ),
                http_client=http,
            )

    async def test_posts_acs_payload_with_bearer(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(202, text="")

        async with _client(handler) as http:
            adapter = AzureCommunicationEmailChannel(
                config=AzureCommunicationEmailConfig(
                    channel_id="email-1",
                    endpoint="https://acs.example/",
                    sender_address="ops@example.com",
                    recipient_addresses=("recv@example.com",),
                    trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
                ),
                http_client=http,
                token_provider=lambda: "the-token",
            )
            receipt = await adapter.send(_message())
        assert receipt.delivered is True
        request = captured[0]
        assert request.headers.get("Authorization") == "Bearer the-token"
        assert "emails:send" in str(request.url)
        import json as _json

        body = _json.loads(request.content.decode("utf-8"))
        assert body["recipients"]["to"][0]["address"] == "recv@example.com"
        assert body["senderAddress"] == "ops@example.com"

    async def test_no_token_provider_omits_bearer(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "Authorization" not in request.headers
            return httpx.Response(202)

        async with _client(handler) as http:
            adapter = AzureCommunicationEmailChannel(
                config=AzureCommunicationEmailConfig(
                    channel_id="email-2",
                    endpoint="https://acs.example",
                    sender_address="ops@example.com",
                    recipient_addresses=("recv@example.com",),
                    trust_tiers=frozenset({TrustTier.A4_DIGEST}),
                ),
                http_client=http,
            )
            await adapter.send(_message())

    async def test_empty_token_omits_bearer(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "Authorization" not in request.headers
            return httpx.Response(202)

        async with _client(handler) as http:
            adapter = AzureCommunicationEmailChannel(
                config=AzureCommunicationEmailConfig(
                    channel_id="email-3",
                    endpoint="https://acs.example",
                    sender_address="ops@example.com",
                    recipient_addresses=("recv@example.com",),
                    trust_tiers=frozenset({TrustTier.A4_DIGEST}),
                ),
                http_client=http,
                token_provider=lambda: "",
            )
            await adapter.send(_message(audit_id=None))


# ---------------------------------------------------------------------------
# Generic webhook
# ---------------------------------------------------------------------------


class TestWebhookAdapter:
    def test_construction_guards(self) -> None:
        http = httpx.AsyncClient()
        with pytest.raises(ValueError, match="timeout_seconds"):
            GenericWebhookChannel(
                config=GenericWebhookConfig(
                    channel_id="w",
                    url="https://example.com/hook",
                    hmac_secret="secret",  # noqa: S106
                    timeout_seconds=0,
                ),
                http_client=http,
            )
        with pytest.raises(ValueError, match="url"):
            GenericWebhookChannel(
                config=GenericWebhookConfig(
                    channel_id="w",
                    url="",
                    hmac_secret="secret",  # noqa: S106
                ),
                http_client=http,
            )
        with pytest.raises(ValueError, match="hmac_secret"):
            GenericWebhookChannel(
                config=GenericWebhookConfig(
                    channel_id="w",
                    url="https://example.com/hook",
                    hmac_secret="",  # noqa: S106
                ),
                http_client=http,
            )
        with pytest.raises(ValueError, match="A1 approvals"):
            GenericWebhookChannel(
                config=GenericWebhookConfig(
                    channel_id="w",
                    url="https://example.com/hook",
                    hmac_secret="secret",  # noqa: S106
                    trust_tiers=frozenset({TrustTier.A1_HIL_APPROVAL}),
                ),
                http_client=http,
            )

    async def test_posts_with_signature_headers(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200)

        async with _client(handler) as http:
            adapter = GenericWebhookChannel(
                config=GenericWebhookConfig(
                    channel_id="webhook-1",
                    url="https://example.com/hook",
                    hmac_secret="topsecret",  # noqa: S106
                    trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
                    extra_headers={"X-Fork": "acme"},
                ),
                http_client=http,
            )
            receipt = await adapter.send(_message())
        assert receipt.delivered is True
        request = captured[0]
        assert request.headers.get("X-AIOpsPilot-Signature", "").startswith("sha256=")
        assert request.headers.get("X-AIOpsPilot-Timestamp")
        assert request.headers.get("X-Fork") == "acme"

    async def test_raises_delivery_error_on_4xx(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="rejected")

        async with _client(handler) as http:
            adapter = GenericWebhookChannel(
                config=GenericWebhookConfig(
                    channel_id="webhook-2",
                    url="https://example.com/hook",
                    hmac_secret="s",  # noqa: S106
                    trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
                ),
                http_client=http,
            )
            with pytest.raises(ChannelDeliveryError, match="HTTP 400"):
                await adapter.send(_message())

    async def test_raises_unavailable_on_transport_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        async with _client(handler) as http:
            adapter = GenericWebhookChannel(
                config=GenericWebhookConfig(
                    channel_id="webhook-3",
                    url="https://example.com/hook",
                    hmac_secret="s",  # noqa: S106
                    trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
                ),
                http_client=http,
            )
            with pytest.raises(ChannelUnavailableError):
                await adapter.send(_message())


# ---------------------------------------------------------------------------
# PagerDuty
# ---------------------------------------------------------------------------


class TestPagerDutyAdapter:
    def test_construction_guards(self) -> None:
        http = httpx.AsyncClient()
        with pytest.raises(ValueError, match="timeout_seconds"):
            PagerDutyEventsV2Channel(
                config=PagerDutyEventsV2Config(
                    channel_id="p",
                    routing_key="rk",
                    timeout_seconds=0,
                ),
                http_client=http,
            )
        with pytest.raises(ValueError, match="routing_key"):
            PagerDutyEventsV2Channel(
                config=PagerDutyEventsV2Config(channel_id="p", routing_key=""),
                http_client=http,
            )
        with pytest.raises(ValueError, match="A1 approvals"):
            PagerDutyEventsV2Channel(
                config=PagerDutyEventsV2Config(
                    channel_id="p",
                    routing_key="rk",
                    trust_tiers=frozenset({TrustTier.A1_HIL_APPROVAL}),
                ),
                http_client=http,
            )

    async def test_posts_events_v2_payload(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(202, text='{"status":"success"}')

        async with _client(handler) as http:
            adapter = PagerDutyEventsV2Channel(
                config=PagerDutyEventsV2Config(
                    channel_id="pd-1",
                    routing_key="ROUTING-KEY-123",
                    events_url="https://events.example/enqueue",
                    trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
                ),
                http_client=http,
            )
            receipt = await adapter.send(_message())
        assert receipt.delivered is True
        import json as _json

        body = _json.loads(captured[0].content.decode("utf-8"))
        assert body["routing_key"] == "ROUTING-KEY-123"
        assert body["event_action"] == "trigger"
        assert body["dedup_key"] == "cid-1"
        assert body["payload"]["severity"] == "error"

    async def test_severity_mapping(self) -> None:
        expected = {
            Severity.INFO: "info",
            Severity.WARN: "warning",
            Severity.ERROR: "error",
            Severity.CRITICAL: "critical",
        }
        for sev, expected_str in expected.items():
            captured: list[httpx.Request] = []

            def _make_handler(
                sink: list[httpx.Request],
            ) -> Callable[[httpx.Request], httpx.Response]:
                def handler(request: httpx.Request) -> httpx.Response:
                    sink.append(request)
                    return httpx.Response(202)

                return handler

            async with _client(_make_handler(captured)) as http:
                adapter = PagerDutyEventsV2Channel(
                    config=PagerDutyEventsV2Config(
                        channel_id="pd-x",
                        routing_key="rk",
                        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
                    ),
                    http_client=http,
                )
                await adapter.send(_message(severity=sev))
            import json as _json

            body = _json.loads(captured[0].content.decode("utf-8"))
            assert body["payload"]["severity"] == expected_str


# ---------------------------------------------------------------------------
# SMS
# ---------------------------------------------------------------------------


class TestSmsAdapter:
    def test_construction_guards(self) -> None:
        http = httpx.AsyncClient()
        with pytest.raises(ValueError, match="timeout_seconds"):
            AzureCommunicationSmsChannel(
                config=AzureCommunicationSmsConfig(
                    channel_id="s",
                    endpoint="https://acs.example",
                    from_phone_number="+10000000000",
                    to_phone_numbers=("+10000000001",),
                    timeout_seconds=0,
                ),
                http_client=http,
            )
        with pytest.raises(ValueError, match="endpoint"):
            AzureCommunicationSmsChannel(
                config=AzureCommunicationSmsConfig(
                    channel_id="s",
                    endpoint="",
                    from_phone_number="+10000000000",
                    to_phone_numbers=("+10000000001",),
                ),
                http_client=http,
            )
        with pytest.raises(ValueError, match="from_phone_number"):
            AzureCommunicationSmsChannel(
                config=AzureCommunicationSmsConfig(
                    channel_id="s",
                    endpoint="https://acs.example",
                    from_phone_number="",
                    to_phone_numbers=("+10000000001",),
                ),
                http_client=http,
            )
        with pytest.raises(ValueError, match="to_phone_numbers"):
            AzureCommunicationSmsChannel(
                config=AzureCommunicationSmsConfig(
                    channel_id="s",
                    endpoint="https://acs.example",
                    from_phone_number="+10000000000",
                    to_phone_numbers=(),
                ),
                http_client=http,
            )
        with pytest.raises(ValueError, match="A1 approvals"):
            AzureCommunicationSmsChannel(
                config=AzureCommunicationSmsConfig(
                    channel_id="s",
                    endpoint="https://acs.example",
                    from_phone_number="+10000000000",
                    to_phone_numbers=("+10000000001",),
                    trust_tiers=frozenset({TrustTier.A1_HIL_APPROVAL}),
                ),
                http_client=http,
            )

    async def test_posts_acs_sms_payload_with_bearer(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(202)

        async with _client(handler) as http:
            adapter = AzureCommunicationSmsChannel(
                config=AzureCommunicationSmsConfig(
                    channel_id="sms-1",
                    endpoint="https://acs.example/",
                    from_phone_number="+10000000000",
                    to_phone_numbers=("+10000000001",),
                    trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
                ),
                http_client=http,
                token_provider=lambda: "sms-token",
            )
            receipt = await adapter.send(_message())
        assert receipt.delivered is True
        request = captured[0]
        assert request.headers.get("Authorization") == "Bearer sms-token"
        import json as _json

        body = _json.loads(request.content.decode("utf-8"))
        assert body["from"] == "+10000000000"
        assert body["smsRecipients"][0]["to"] == "+10000000001"
        # SMS body is short-form: severity + audit_id + first link URL.
        assert body["message"].startswith("ERROR")
        assert "audit-1" in body["message"]
        assert "https://example.com/rb/1" in body["message"]

    async def test_sms_body_no_links_or_audit(self) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(202)

        async with _client(handler) as http:
            adapter = AzureCommunicationSmsChannel(
                config=AzureCommunicationSmsConfig(
                    channel_id="sms-2",
                    endpoint="https://acs.example",
                    from_phone_number="+10000000000",
                    to_phone_numbers=("+10000000001",),
                    trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
                ),
                http_client=http,
            )
            await adapter.send(_message(audit_id=None, links=()))
        import json as _json

        body = _json.loads(captured[0].content.decode("utf-8"))
        assert body["message"] == "ERROR"

    async def test_empty_token_omits_bearer(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "Authorization" not in request.headers
            return httpx.Response(202)

        async with _client(handler) as http:
            adapter = AzureCommunicationSmsChannel(
                config=AzureCommunicationSmsConfig(
                    channel_id="sms-3",
                    endpoint="https://acs.example",
                    from_phone_number="+10000000000",
                    to_phone_numbers=("+10000000001",),
                    trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
                ),
                http_client=http,
                token_provider=lambda: "",
            )
            await adapter.send(_message())
