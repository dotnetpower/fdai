"""No-network Slack approval dispatch and non-authorizing replay behavior."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from fdai.delivery.chatops.slack_adapter import (
    HIL_BINDING_FIELD,
    SLACK_POST_URL,
    SlackHilAdapter,
    SlackHilAdapterConfig,
)
from fdai.shared.providers.hil_channel import HilApprovalRequest, HilChannelError, HilDecision

_TOKEN = "synthetic-bot-credential"  # noqa: S105 - MockTransport fixture only
_CHANNEL = "CEXAMPLE1"


def _config(**overrides: object) -> SlackHilAdapterConfig:
    return SlackHilAdapterConfig(
        **{
            "api_url": SLACK_POST_URL,
            "channel_id": _CHANNEL,
            "bot_token": _TOKEN,
            **overrides,
        }
    )


def _request(**overrides: object) -> HilApprovalRequest:
    return HilApprovalRequest(
        **{
            "approval_id": "approval-1",
            "correlation_id": "correlation-1",
            "action_id": "action-1",
            "action_type": "action.example",
            "rule_ids": (),
            "target_resource_ref": "sensitive-resource",
            "blast_radius_summary": "sensitive-radius",
            "reasons": ("sensitive-reason",),
            "action_hash": "hash-1",
            "metadata": {
                HIL_BINDING_FIELD: "a",
                "presentation_note": "omit this display note",
            },
            **overrides,
        }
    )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"api_url": "http://slack.com/api/chat.postMessage"}, "HTTPS"),
        ({"api_url": "https://example.com/api/chat.postMessage"}, "HTTPS"),
        ({"channel_id": ""}, "channel_id"),
        ({"bot_token": ""}, "bot_token"),
        ({"timeout_seconds": float("inf")}, "timeout_seconds"),
    ],
)
def test_config_fails_closed(overrides: dict[str, object], expected: str) -> None:
    with pytest.raises(ValueError, match=expected):
        _config(**overrides)
    assert _TOKEN not in repr(_config())


async def test_send_returns_exact_receipt_and_local_replay_without_second_post() -> None:
    posts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posts.append(request)
        return httpx.Response(200, json={"ok": True, "ts": "12345.6789", "channel": _CHANNEL})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        channel = SlackHilAdapter(config=_config(), http_client=client)
        request = _request()
        first, duplicate = await asyncio.gather(channel.send(request), channel.send(request))
        response = await channel.poll(first)
        with pytest.raises(HilChannelError, match="conflicting bindings"):
            await channel.send(replace(request, action_hash="different"))

    assert first is duplicate
    assert first.approval_id == request.approval_id
    assert first.channel_ref == "slack:CEXAMPLE1/12345.6789"
    assert first.sent_at.tzinfo is not None
    assert response.approval_id == request.approval_id
    assert response.decision is HilDecision.PENDING
    assert len(posts) == 1
    post = posts[0]
    assert str(post.url) == SLACK_POST_URL
    assert post.method == "POST"
    assert post.headers["authorization"] == f"Bearer {_TOKEN}"
    body = json.loads(post.content)
    assert body["channel"] == _CHANNEL
    assert body["blocks"][0]["type"] == "section"
    assert body["blocks"][-1] == {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve"},
                "action_id": "fdai_hil_approve",
                "value": request.approval_id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Reject"},
                "action_id": "fdai_hil_reject",
                "value": request.approval_id,
            },
        ],
    }
    assert "a click is not an approval" in body["text"]
    for name in (
        "approval_id",
        "correlation_id",
        "action_id",
        HIL_BINDING_FIELD,
        "approval_dispatch_id",
    ):
        assert name in post.content.decode()
    assert "approval_dispatch_id: initial" in post.content.decode()
    assert "action_hash" not in post.content.decode()
    assert request.action_hash not in post.content.decode()
    for button in body["blocks"][-1]["elements"]:
        assert set(button) == {"type", "text", "action_id", "value"}
    for forbidden in (
        "sensitive-resource",
        "sensitive-radius",
        "sensitive-reason",
        "omit this display note",
        "action.example",
        _TOKEN,
        "approver_oid",
        "executor_identity",
    ):
        assert forbidden not in post.content.decode()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="secret provider body"),
        httpx.Response(302, headers={"Location": "https://example.com/elsewhere"}),
        httpx.Response(200, json={"ok": False, "error": "secret provider body"}),
        httpx.Response(200, json={"ok": True, "channel": _CHANNEL}),
        httpx.Response(200, json={"ok": True, "ts": "12345.6789", "channel": "COTHER"}),
        httpx.Response(200, text="not-json"),
        httpx.Response(200, content=b"x" * 4097),
    ],
)
async def test_unaccepted_or_unknown_ack_never_reposts(response: httpx.Response) -> None:
    posts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        channel = SlackHilAdapter(config=_config(), http_client=client)
        with pytest.raises(HilChannelError) as failure:
            await channel.send(_request())
        assert "secret provider body" not in str(failure.value)
        with pytest.raises(HilChannelError, match="unknown; reconcile"):
            await channel.send(_request())
    assert posts == 1


async def test_ambiguous_timeout_does_not_retry() -> None:
    posts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        raise httpx.ReadTimeout("sensitive provider error", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        channel = SlackHilAdapter(config=_config(), http_client=client)
        with pytest.raises(HilChannelError, match="unknown; reconcile") as failure:
            await channel.send(_request())
        assert "sensitive provider error" not in str(failure.value)
        with pytest.raises(HilChannelError, match="unknown; reconcile"):
            await channel.send(_request())
    assert posts == 1


@pytest.mark.parametrize(
    "approval_request",
    [
        _request(action_hash=""),
        _request(metadata={}),
        _request(metadata={HIL_BINDING_FIELD: "xoxb-leak"}),
        _request(correlation_id="https://example.com"),
        _request(approval_id="a" * 201),
        _request(approval_id="a" * 129),
    ],
)
async def test_invalid_context_is_rejected_before_transport(
    approval_request: HilApprovalRequest,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("invalid context must not send")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        channel = SlackHilAdapter(config=_config(), http_client=client)
        with pytest.raises(HilChannelError, match="incomplete or unsafe"):
            await channel.send(approval_request)
