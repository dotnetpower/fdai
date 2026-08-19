"""Slack A3 signature, queue, payload, and acknowledgement boundaries."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.channels.slack_ingress import (
    SlackIngressAction,
    SlackIngressConfig,
    SlackIngressError,
    SlackIngressResult,
    SlackIngressVerifier,
)
from fdai.delivery.channels.slack_publisher import (
    SlackPublisherConfig,
    SlackResponsePublisher,
)
from fdai.delivery.channels.slack_transport import SlackConversationAdapter
from fdai.shared.providers.conversation_channel import (
    ChannelDeliveryError,
    ConversationChannelKind,
    OutboundResponse,
)

_SECRET = "test-slack-signing-secret"  # noqa: S105
_BOT_TOKEN = "xoxb-test-bot-token"  # noqa: S105
_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def _verifier() -> SlackIngressVerifier:
    return SlackIngressVerifier(
        SlackIngressConfig(
            signing_secret=_SECRET,
            team_id="team-example",
            allowed_sender_ids=frozenset({"user-example"}),
        )
    )


def _event(*, event: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "type": "event_callback",
        "team_id": "team-example",
        "event_id": "event-example",
        "event": event
        or {
            "type": "message",
            "user": "user-example",
            "channel": "channel-example",
            "ts": "1724068800.000100",
            "text": "Show the current incident state",
        },
    }


def _signed(payload: object, *, at: datetime = _NOW) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(at.timestamp()))
    digest = hmac.new(
        _SECRET.encode(),
        b"v0:" + timestamp.encode() + b":" + body,
        hashlib.sha256,
    ).hexdigest()
    return body, {
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": "v0=" + digest,
    }


def test_ingress_verifies_exact_body_and_drops_file_urls() -> None:
    payload = _event(
        event={
            "type": "message",
            "subtype": "file_share",
            "user": "user-example",
            "channel": "channel-example",
            "ts": "1724068800.000100",
            "thread_ts": "1724068700.000010",
            "text": "Inspect this evidence",
            "files": [
                {
                    "id": "file-example",
                    "name": "evidence.txt",
                    "size": 128,
                    "mimetype": "text/plain",
                    "url_private": "https://files.invalid/private",
                    "permalink": "https://files.invalid/page",
                }
            ],
        }
    )
    body, headers = _signed(payload)

    result = _verifier().parse(body=body, headers=headers, received_at=_NOW)

    assert result.action is SlackIngressAction.ACCEPTED
    assert result.turn is not None
    assert result.turn.thread_id == "1724068700.000010"
    assert result.turn.attachments[0].source_ref == "slack-file:file-example"
    assert "invalid" not in repr(result.turn.attachments)


def test_signed_url_challenge_never_enters_the_message_path() -> None:
    body, headers = _signed({"type": "url_verification", "challenge": "challenge-example"})

    result = _verifier().parse(body=body, headers=headers, received_at=_NOW)

    assert result == SlackIngressResult(
        action=SlackIngressAction.CHALLENGE,
        challenge="challenge-example",
    )


@pytest.mark.parametrize("age", [timedelta(minutes=-6), timedelta(minutes=6)])
def test_ingress_rejects_request_outside_replay_window(age: timedelta) -> None:
    body, headers = _signed(_event(), at=_NOW + age)

    with pytest.raises(SlackIngressError, match="replay") as raised:
        _verifier().parse(body=body, headers=headers, received_at=_NOW)

    assert raised.value.http_status == 401


def test_ingress_rejects_signature_for_changed_body() -> None:
    body, headers = _signed(_event())

    with pytest.raises(SlackIngressError, match="signature"):
        _verifier().parse(body=body + b" ", headers=headers, received_at=_NOW)


def test_ingress_ignores_bot_loop_and_unsupported_event() -> None:
    bot_body, bot_headers = _signed(
        _event(event={"type": "message", "bot_id": "bot", "subtype": "bot_message"})
    )
    reaction_body, reaction_headers = _signed(
        _event(event={"type": "reaction_added", "user": "user-example"})
    )

    assert (
        _verifier().parse(body=bot_body, headers=bot_headers, received_at=_NOW).action
        is SlackIngressAction.IGNORED
    )
    assert (
        _verifier().parse(body=reaction_body, headers=reaction_headers, received_at=_NOW).action
        is SlackIngressAction.IGNORED
    )


def test_ingress_denies_unknown_sender_before_queue_admission() -> None:
    payload = _event()
    assert isinstance(payload["event"], dict)
    payload["event"]["user"] = "unknown-user"
    body, headers = _signed(payload)

    with pytest.raises(SlackIngressError, match="not authorized") as raised:
        _verifier().parse(body=body, headers=headers, received_at=_NOW)

    assert raised.value.http_status == 403


class _Publisher:
    async def send(self, response: OutboundResponse):  # type: ignore[no-untyped-def]
        del response
        raise AssertionError("send is not used")


async def test_adapter_applies_backpressure_and_closes_consumer() -> None:
    adapter = SlackConversationAdapter(
        ingress=_verifier(), publisher=_Publisher(), queue_capacity=1
    )
    body, headers = _signed(_event())
    adapter.accept(body=body, headers=headers, received_at=_NOW)

    with pytest.raises(SlackIngressError, match="queue is full") as raised:
        adapter.accept(body=body, headers=headers, received_at=_NOW)
    assert raised.value.http_status == 503

    consumer = adapter.receive()
    assert (await anext(consumer)).message_id == "event-example"
    await adapter.close()
    with pytest.raises(StopAsyncIteration):
        await anext(consumer)


def _response(*, edit_message_id: str | None = None) -> OutboundResponse:
    return OutboundResponse(
        channel_kind=ConversationChannelKind.SLACK,
        channel_id="channel-example",
        in_reply_to="event-example",
        thread_id="1724068800.000100",
        status="verified",
        text="The incident is stable.",
        data={
            "execution_authority": False,
            "authority": "server_read_model",
            "limitations": ["One source is delayed."],
        },
        evidence_refs=("evidence:incident-example",),
        edit_message_id=edit_message_id,
    )


async def test_publisher_uses_fixed_post_endpoint_thread_and_strict_ack() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "ts": "1724068801.000200"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await SlackResponsePublisher(
            config=SlackPublisherConfig(bot_token=_BOT_TOKEN),
            http_client=client,
        ).send(_response())

    assert str(seen[0].url) == "https://slack.com/api/chat.postMessage"
    assert seen[0].headers["Authorization"] == f"Bearer {_BOT_TOKEN}"
    payload = json.loads(seen[0].content)
    assert payload["channel"] == "channel-example"
    assert payload["thread_ts"] == "1724068800.000100"
    assert receipt.message_id == "1724068801.000200"


async def test_publisher_uses_fixed_update_endpoint() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "ts": "1724068801.000200"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await SlackResponsePublisher(
            config=SlackPublisherConfig(bot_token=_BOT_TOKEN),
            http_client=client,
        ).send(_response(edit_message_id="1724068800.000300"))

    payload = json.loads(seen[0].content)
    assert str(seen[0].url) == "https://slack.com/api/chat.update"
    assert payload["ts"] == "1724068800.000300"
    assert "thread_ts" not in payload


@pytest.mark.parametrize(
    ("provider_response", "ambiguous"),
    [
        (httpx.Response(200, json={"ok": False, "error": "channel_not_found"}), False),
        (httpx.Response(302, headers={"location": "https://evil.invalid"}), False),
        (httpx.Response(200, content=b"not-json"), True),
        (httpx.Response(200, json={"ok": True}), True),
    ],
)
async def test_publisher_classifies_provider_acknowledgement(
    provider_response: httpx.Response,
    ambiguous: bool,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: provider_response)
    ) as client:
        publisher = SlackResponsePublisher(
            config=SlackPublisherConfig(bot_token=_BOT_TOKEN),
            http_client=client,
        )
        with pytest.raises(ChannelDeliveryError) as raised:
            await publisher.send(_response())

    assert raised.value.acknowledgement_ambiguous is ambiguous


async def test_publisher_treats_transport_loss_as_ambiguous() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("connection lost")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = SlackResponsePublisher(
            config=SlackPublisherConfig(bot_token=_BOT_TOKEN),
            http_client=client,
        )
        with pytest.raises(ChannelDeliveryError) as raised:
            await publisher.send(_response())

    assert raised.value.acknowledgement_ambiguous is True


async def test_publisher_bounds_success_acknowledgement_body() -> None:
    response = httpx.Response(200, content=b"x" * 65)
    transport = httpx.MockTransport(lambda _request: response)
    async with httpx.AsyncClient(transport=transport) as client:
        publisher = SlackResponsePublisher(
            config=SlackPublisherConfig(bot_token=_BOT_TOKEN, max_response_bytes=64),
            http_client=client,
        )
        with pytest.raises(ChannelDeliveryError, match="byte limit") as raised:
            await publisher.send(_response())

    assert raised.value.acknowledgement_ambiguous is True
