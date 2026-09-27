"""Direct Line custom-channel adapter: rendering, authentication, and fail-closed transport."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any

import httpx
import pytest
from fdai.delivery.notifications import (
    DirectLineConfig,
    DirectLineCredential,
    DirectLineNotificationChannel,
    direct_line_idempotency_key,
    render_direct_line_payload,
    static_direct_line_credential,
)
from fdai.delivery.notifications.direct_line import ACTIVITY_DIGEST_PREFIX
from fdai.shared.providers.notifications import (
    ChannelAmbiguousError,
    ChannelDeliveryError,
    ChannelKind,
    ChannelUnavailableError,
    DirectLineChannel,
    Link,
    NotificationMessage,
    NotificationPresentationEnvelope,
    PresentationRejectedError,
    Severity,
    TrustTier,
    render_presentation,
)

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
ENDPOINT = "https://directline.example.com"
CONVERSATION = "conversation-example-1"
CHANNEL = "direct-line-ops"
CREDENTIAL = "-".join(("synthetic", "direct", "line", "credential"))
ACTIVITIES_URL = f"{ENDPOINT}/v3/directline/conversations/{CONVERSATION}/activities"
A2_A4 = frozenset({TrustTier.A2_OPERATIONAL_ALERT, TrustTier.A4_DIGEST})


def _message(
    *,
    trust_tier: TrustTier = TrustTier.A2_OPERATIONAL_ALERT,
    title: str = "API latency recovered",
    body_markdown: str = "Rollback completed and verification is in progress.",
    metadata: dict[str, str] | None = None,
    links: tuple[Link, ...] = (),
) -> NotificationMessage:
    return NotificationMessage(
        category="operational_alert",
        trust_tier=trust_tier,
        correlation_id="inc-example-latency",
        audit_id="audit-example-1",
        title=title,
        body_markdown=body_markdown,
        severity=Severity.ERROR,
        metadata=metadata or {},
        links=links,
    )


def _provider(
    value: str = CREDENTIAL, expires_at: datetime | None = None
) -> Callable[[], Awaitable[DirectLineCredential]]:
    async def provider() -> DirectLineCredential:
        return DirectLineCredential(value=value, expires_at=expires_at)

    return provider


def _channel(
    client: httpx.AsyncClient,
    *,
    provider: Callable[[], Awaitable[DirectLineCredential]] | None = None,
    endpoint: str = ENDPOINT,
    trust_tiers: frozenset[TrustTier] = A2_A4,
) -> DirectLineNotificationChannel:
    return DirectLineNotificationChannel(
        config=DirectLineConfig(
            channel_id=CHANNEL,
            endpoint=endpoint,
            conversation_id=CONVERSATION,
            trust_tiers=trust_tiers,
        ),
        http_client=client,
        credential_provider=provider or _provider(),
        clock=lambda: NOW,
    )


def _client(handler: Callable[[httpx.Request], Any], requests: list[httpx.Request]) -> Any:
    def recording(request: httpx.Request) -> Any:
        requests.append(request)
        return handler(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(recording))


def _accepted(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"id": f"{CONVERSATION}|0000001"})


def test_renderer_emits_read_only_markdown_activity_with_canonical_record() -> None:
    envelope = render_presentation(
        _message(
            metadata={"incident_id": "inc-example", "order": "Huginn -> Forseti -> Thor"},
            links=(Link(label="Runbook (read only)", url="https://example.com/run(book)"),),
        ),
        channel_id=CHANNEL,
    )

    rendered = render_direct_line_payload(envelope)
    activity = json.loads(rendered.body)
    record = activity["channelData"]["fdai"]
    material = "\x1f".join((CHANNEL, "inc-example-latency", "audit-example-1", "operational_alert"))

    assert rendered.content_type == "application/json"
    assert activity["type"] == "message"
    assert activity["textFormat"] == "markdown"
    assert activity["from"] == {"id": "fdai-notifications", "name": "FDAI"}
    assert not {"attachments", "suggestedActions", "value"} & set(activity)
    assert activity["text"].startswith("**CRITICAL** API latency recovered")
    assert "- incident\\_id: inc-example" in activity["text"]
    assert "[Runbook (read only)](https://example.com/run%28book%29)" in activity["text"]
    assert record["read_only"] is True
    assert record["trust_tier"] == "a2_operational_alert"
    assert record["audit_id"] == "audit-example-1"
    assert record["correlation_id"] == "inc-example-latency"
    assert record["idempotency_key"] == hashlib.sha256(material.encode()).hexdigest()
    assert record["idempotency_key"] == direct_line_idempotency_key(envelope)
    assert record["metadata"] == {
        "incident_id": "inc-example",
        "order": "Huginn -> Forseti -> Thor",
    }


def test_renderer_bounds_text_and_neutralizes_inline_markdown() -> None:
    envelope = render_presentation(
        _message(
            title="T" * 280,
            body_markdown="B" * 3500,
            metadata={"note": "see [approve](https://example.com)\n# heading"},
        ),
        channel_id=CHANNEL,
    )

    text = json.loads(render_direct_line_payload(envelope).body)["text"]

    assert text.splitlines()[0].endswith("T" * 238 + " \\[truncated\\]")
    assert "B" * 2988 + " [truncated]" in text
    assert "- note: see \\[approve\\](https://example.com) # heading" in text
    assert "- rendering: truncated title, body" in text
    assert "\n# heading" not in text


def test_renderer_fails_closed_above_the_payload_ceiling() -> None:
    envelope = NotificationPresentationEnvelope(
        channel_id=CHANNEL,
        category="digest_shadow_accuracy_daily",
        trust_tier=TrustTier.A4_DIGEST,
        correlation_id="digest-example",
        title="Digest",
        body_markdown="Body",
        severity=Severity.INFO,
        links=(),
        metadata=MappingProxyType({f"key-{index}": "v" * 1000 for index in range(40)}),
    )

    with pytest.raises(ChannelDeliveryError, match="payload exceeds"):
        render_direct_line_payload(envelope)


async def test_send_authenticates_and_reports_provider_acceptance_only() -> None:
    requests: list[httpx.Request] = []
    async with _client(_accepted, requests) as client:
        channel = _channel(client)
        receipt = await channel.send(_message())

    expected = render_direct_line_payload(render_presentation(_message(), channel_id=CHANNEL))
    digest = hashlib.sha256(f"{CONVERSATION}|0000001".encode()).hexdigest()
    assert isinstance(channel, DirectLineChannel)
    assert channel.channel_kind is ChannelKind.DIRECT_LINE
    assert receipt.channel_kind is ChannelKind.DIRECT_LINE
    assert receipt.accepted is True
    assert receipt.delivered is False
    assert receipt.provider_message_id == f"{ACTIVITY_DIGEST_PREFIX}{digest}"
    assert CONVERSATION not in receipt.provider_message_id
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert str(requests[0].url) == ACTIVITIES_URL
    assert requests[0].headers["Authorization"] == f"Bearer {CREDENTIAL}"
    assert requests[0].content == expected.body
    assert CREDENTIAL.encode() not in requests[0].content
    assert CONVERSATION.encode() not in requests[0].content


@pytest.mark.parametrize(
    "endpoint",
    ["https://bot.example.com/.bot", "https://bot.example.com/.bot/v3/directline/"],
)
async def test_endpoint_accepts_an_explicit_api_suffix_once(endpoint: str) -> None:
    requests: list[httpx.Request] = []
    async with _client(_accepted, requests) as client:
        await _channel(client, endpoint=endpoint).send(_message())

    assert requests[0].url.path == f"/.bot/v3/directline/conversations/{CONVERSATION}/activities"


@pytest.mark.parametrize(
    ("endpoint", "netloc"),
    [
        ("https://bot.example.com:8443", "bot.example.com:8443"),
        ("https://[::1]:8443", "[::1]:8443"),
    ],
)
async def test_endpoint_preserves_explicit_ports_and_ipv6_hosts(endpoint: str, netloc: str) -> None:
    requests: list[httpx.Request] = []
    async with _client(_accepted, requests) as client:
        await _channel(client, endpoint=endpoint).send(_message())

    assert requests[0].url.netloc.decode() == netloc
    assert requests[0].url.path == f"/v3/directline/conversations/{CONVERSATION}/activities"


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"trust_tiers": frozenset({TrustTier.A1_HIL_APPROVAL})}, "a2_operational_alert"),
        ({"trust_tiers": frozenset({TrustTier.A3_CHAT_COMMAND})}, "a2_operational_alert"),
        ({"trust_tiers": frozenset()}, "a2_operational_alert"),
        ({"endpoint": "http://directline.example.com"}, "https URL"),
        ({"endpoint": "https://directline.example.com?code=1"}, "https URL"),
        ({"endpoint": "https://user:pw@directline.example.com"}, "https URL"),
        ({"conversation_id": "conversation/example"}, "conversation_id"),
        ({"conversation_id": ""}, "conversation_id"),
        ({"sender_id": "sender with space"}, "sender_id"),
    ],
)
def test_invalid_configuration_is_rejected_without_echoing_values(
    overrides: dict[str, Any], match: str
) -> None:
    values: dict[str, Any] = {
        "channel_id": CHANNEL,
        "endpoint": ENDPOINT,
        "conversation_id": CONVERSATION,
        "trust_tiers": A2_A4,
        **overrides,
    }

    with pytest.raises(ValueError, match=match) as captured:
        DirectLineNotificationChannel(
            config=DirectLineConfig(**values),
            http_client=httpx.AsyncClient(),
            credential_provider=_provider(),
        )

    assert "directline.example.com" not in str(captured.value)
    assert "conversation/example" not in str(captured.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"id": ""}),
        httpx.Response(200, json={"id": 7}),
        httpx.Response(200, json={"id": "has space"}),
        httpx.Response(202, json={}),
        httpx.Response(204),
        httpx.Response(200, json={"id": "x", "pad": "p" * 5000}),
    ],
)
async def test_acceptance_requires_a_valid_activity_id(response: httpx.Response) -> None:
    requests: list[httpx.Request] = []
    async with _client(lambda _: response, requests) as client:
        with pytest.raises(ChannelAmbiguousError, match="acknowledgement"):
            await _channel(client).send(_message())

    assert len(requests) == 1


@pytest.mark.parametrize("status", [401, 403])
async def test_unauthorized_responses_fail_closed_without_adapter_retry(status: int) -> None:
    requests: list[httpx.Request] = []

    def rejected(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"code": "TokenExpired"}})

    async with _client(rejected, requests) as client:
        with pytest.raises(ChannelDeliveryError, match="rejected the client credential") as caught:
            await _channel(client).send(_message())

    assert type(caught.value) is ChannelDeliveryError
    assert len(requests) == 1
    assert CREDENTIAL not in str(caught.value)


@pytest.mark.parametrize(
    ("status", "match"),
    [
        (400, "rejected the request"),
        (404, "rejected the request"),
        (429, "throttled the request"),
    ],
)
async def test_non_receipt_statuses_are_retryable_after_exactly_one_request(
    status: int, match: str
) -> None:
    requests: list[httpx.Request] = []
    reflected = "reflected-sensitive-body"
    headers = {"Retry-After": "30"} if status == 429 else {}
    async with _client(
        lambda _: httpx.Response(status, text=reflected, headers=headers), requests
    ) as client:
        with pytest.raises(ChannelDeliveryError, match=f"{match} with HTTP {status}") as caught:
            await _channel(client).send(_message())

    assert type(caught.value) is ChannelDeliveryError
    assert reflected not in str(caught.value)
    assert len(requests) == 1


@pytest.mark.parametrize("status", [500, 502, 503, 504, 302, 409, 413])
async def test_statuses_that_cannot_prove_non_receipt_are_ambiguous(status: int) -> None:
    requests: list[httpx.Request] = []
    reflected = "reflected-sensitive-body"
    async with _client(lambda _: httpx.Response(status, text=reflected), requests) as client:
        with pytest.raises(ChannelAmbiguousError, match=f"HTTP {status}") as caught:
            await _channel(client).send(_message())

    assert reflected not in str(caught.value)
    assert len(requests) == 1


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ConnectError("connect"), ChannelUnavailableError),
        (httpx.ConnectTimeout("connect timeout"), ChannelUnavailableError),
        (httpx.ReadTimeout("response lost"), ChannelAmbiguousError),
    ],
)
async def test_transport_failures_are_classified(
    error: httpx.HTTPError, expected: type[Exception]
) -> None:
    def failing(_: httpx.Request) -> httpx.Response:
        raise error

    async with _client(failing, []) as client:
        with pytest.raises(expected):
            await _channel(client).send(_message())


async def _raising_provider() -> DirectLineCredential:
    raise RuntimeError(CREDENTIAL)


@pytest.mark.parametrize(
    ("provider", "expected", "match"),
    [
        (_provider(expires_at=NOW - timedelta(seconds=1)), ChannelDeliveryError, "expired"),
        (_provider(expires_at=NOW + timedelta(seconds=30)), ChannelDeliveryError, "expired"),
        (_provider(expires_at=datetime(2026, 9, 27, 13)), ChannelDeliveryError, "timezone"),
        (_provider(value=""), ChannelDeliveryError, "malformed"),
        (_provider(value="has space"), ChannelDeliveryError, "malformed"),
        (_raising_provider, ChannelUnavailableError, "credential provider failed"),
    ],
)
async def test_unusable_credentials_fail_closed_before_transport(
    provider: Callable[[], Awaitable[DirectLineCredential]],
    expected: type[Exception],
    match: str,
) -> None:
    requests: list[httpx.Request] = []
    async with _client(_accepted, requests) as client:
        with pytest.raises(expected, match=match) as caught:
            await _channel(client, provider=provider).send(_message())

    assert requests == []
    assert CREDENTIAL not in str(caught.value)


async def test_unexpired_token_credential_is_used() -> None:
    requests: list[httpx.Request] = []
    token = _provider(expires_at=NOW + timedelta(minutes=10))
    async with _client(_accepted, requests) as client:
        receipt = await _channel(client, provider=token).send(_message())

    assert receipt.accepted is True
    assert len(requests) == 1


@pytest.mark.parametrize("tier", [TrustTier.A1_HIL_APPROVAL, TrustTier.A4_DIGEST])
async def test_undeclared_trust_tier_is_refused_before_transport(tier: TrustTier) -> None:
    requests: list[httpx.Request] = []
    a2_only = frozenset({TrustTier.A2_OPERATIONAL_ALERT})
    async with _client(_accepted, requests) as client:
        with pytest.raises(ChannelDeliveryError, match="does not carry trust tier"):
            await _channel(client, trust_tiers=a2_only).send(_message(trust_tier=tier))

    assert requests == []


async def test_secret_like_content_is_rejected_before_credential_or_transport() -> None:
    calls = 0
    requests: list[httpx.Request] = []

    async def counting() -> DirectLineCredential:
        nonlocal calls
        calls += 1
        return DirectLineCredential(value=CREDENTIAL)

    body = ": ".join(("api_key", "synthetic-value"))
    async with _client(_accepted, requests) as client:
        with pytest.raises(PresentationRejectedError, match="secret-like"):
            await _channel(client, provider=counting).send(_message(body_markdown=body))

    assert calls == 0
    assert requests == []


def test_deployment_values_stay_out_of_repr() -> None:
    config = DirectLineConfig(
        channel_id=CHANNEL,
        endpoint=ENDPOINT,
        conversation_id=CONVERSATION,
        trust_tiers=A2_A4,
    )

    assert ENDPOINT not in repr(config)
    assert CONVERSATION not in repr(config)
    assert CREDENTIAL not in repr(DirectLineCredential(value=CREDENTIAL))


@pytest.mark.parametrize("value", ["", "has space", "line\nbreak"])
def test_static_credential_rejects_malformed_values_without_echo(value: str) -> None:
    with pytest.raises(ValueError, match="printable ASCII") as caught:
        static_direct_line_credential(value)

    if value:
        assert value not in str(caught.value)
