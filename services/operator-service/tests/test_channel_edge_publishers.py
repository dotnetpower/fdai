"""Fixed destination and acknowledgement tests for Operator channel publishers."""

from __future__ import annotations

import json

import httpx
import pytest
from fdai_operator_service.families.conversation.channel_delivery_models import ChannelKind
from fdai_operator_service.families.conversation.channel_edge.models import (
    ChannelDeliveryError,
    RenderedChannelMessage,
)
from fdai_operator_service.families.conversation.channel_edge.publishers import (
    TEAMS_BOT_SCOPE,
    ChannelAccessToken,
    SlackPublisherConfig,
    SlackResponsePublisher,
    TeamsResponsePublisher,
)
from fdai_operator_service.families.conversation.channel_edge.queues import (
    TeamsEndpointRegistry,
)

_SERVICE_URL = "https://smba.trafficmanager.net/example"


class _Identity:
    def __init__(self, *, audience: str = TEAMS_BOT_SCOPE) -> None:
        self.audience = audience
        self.requests: list[str] = []

    async def get_token(self, audience: str) -> ChannelAccessToken:
        self.requests.append(audience)
        return ChannelAccessToken(token="test-token", audience=self.audience)


def _message(
    kind: ChannelKind,
    *,
    edit_message_id: str | None = None,
    payload: dict[str, object] | None = None,
) -> RenderedChannelMessage:
    return RenderedChannelMessage(
        channel_kind=kind,
        channel_id="conversation-example" if kind is ChannelKind.TEAMS else "channel-example",
        thread_id="thread-example",
        edit_message_id=edit_message_id,
        payload=payload or {"text": "Verified answer"},  # type: ignore[arg-type]
    )


async def test_slack_uses_fixed_method_and_server_owned_routing() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "ts": "1724068801.000200"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await SlackResponsePublisher(
            config=SlackPublisherConfig(bot_token="test-bot-token"),  # noqa: S106
            http_client=client,
        ).send(_message(ChannelKind.SLACK))

    payload = json.loads(seen[0].content)
    assert str(seen[0].url) == "https://slack.com/api/chat.postMessage"
    assert payload["channel"] == "channel-example"
    assert payload["thread_ts"] == "thread-example"
    assert receipt.message_id == "1724068801.000200"


async def test_slack_rejects_renderer_owned_routing_and_uses_fixed_update() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "ts": "1724068801.000200"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = SlackResponsePublisher(
            config=SlackPublisherConfig(bot_token="test-bot-token"),  # noqa: S106
            http_client=client,
        )
        with pytest.raises(ChannelDeliveryError) as reserved:
            await publisher.send(_message(ChannelKind.SLACK, payload={"channel": "other"}))
        assert reserved.value.acknowledgement_ambiguous is False
        await publisher.send(_message(ChannelKind.SLACK, edit_message_id="message-original"))

    assert str(seen[0].url) == "https://slack.com/api/chat.update"
    assert json.loads(seen[0].content)["ts"] == "message-original"


async def test_teams_uses_only_allowlisted_registry_endpoint_and_fixed_scope() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"id": "activity-response"})

    endpoints = TeamsEndpointRegistry(allowed_service_urls=frozenset({_SERVICE_URL}))
    endpoints.bind(conversation_id="conversation-example", service_url=_SERVICE_URL)
    identity = _Identity()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await TeamsResponsePublisher(
            http_client=client,
            identity=identity,
            endpoints=endpoints,
        ).send(_message(ChannelKind.TEAMS))

    assert str(seen[0].url) == _SERVICE_URL + "/v3/conversations/conversation-example/activities"
    assert identity.requests == [TEAMS_BOT_SCOPE]
    assert receipt.message_id == "activity-response"


@pytest.mark.parametrize(
    ("response", "ambiguous"),
    [
        (httpx.Response(400, json={"error": "rejected"}), False),
        (httpx.Response(302, headers={"location": "https://evil.invalid"}), False),
        (httpx.Response(201, content=b"not-json"), True),
        (httpx.Response(201, json={}), True),
        (httpx.Response(201, content=b'{"id":"one","id":"two"}'), True),
    ],
)
async def test_teams_classifies_acknowledgements(
    response: httpx.Response,
    ambiguous: bool,
) -> None:
    endpoints = TeamsEndpointRegistry(allowed_service_urls=frozenset({_SERVICE_URL}))
    endpoints.bind(conversation_id="conversation-example", service_url=_SERVICE_URL)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: response)
    ) as client:
        publisher = TeamsResponsePublisher(
            http_client=client,
            identity=_Identity(),
            endpoints=endpoints,
        )
        with pytest.raises(ChannelDeliveryError) as raised:
            await publisher.send(_message(ChannelKind.TEAMS))

    assert raised.value.acknowledgement_ambiguous is ambiguous


async def test_teams_rejects_unallowlisted_endpoint_and_wrong_token_audience() -> None:
    endpoints = TeamsEndpointRegistry(allowed_service_urls=frozenset({_SERVICE_URL}))
    with pytest.raises(ValueError, match="not authorized"):
        endpoints.bind(
            conversation_id="conversation-example",
            service_url="https://evil.invalid",
        )
    endpoints.bind(conversation_id="conversation-example", service_url=_SERVICE_URL)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(201))
    ) as client:
        publisher = TeamsResponsePublisher(
            http_client=client,
            identity=_Identity(audience="https://management.azure.com/.default"),
            endpoints=endpoints,
        )
        with pytest.raises(ChannelDeliveryError) as raised:
            await publisher.send(_message(ChannelKind.TEAMS))
    assert raised.value.code == "identity_audience_mismatch"
    assert raised.value.acknowledgement_ambiguous is False
