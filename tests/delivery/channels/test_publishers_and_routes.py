"""Credential-backed channel publishers and authenticated route tests."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime

import httpx
import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.delivery.channels import (
    SlackBotChannel,
    SlackReplyPublisherConfig,
    SlackWebApiReplyPublisher,
    TeamsBotChannel,
    TeamsBotFrameworkReplyPublisher,
    TeamsReplyPublisherConfig,
    make_slack_events_route,
    make_teams_activity_route,
)
from fdai.shared.providers.conversation_channel import (
    AgentHandoffActivity,
    ChannelDeliveryError,
    ChannelDeliveryOperation,
    ChannelDeliveryReceipt,
    ChannelMention,
    ChannelProgressStatus,
    ChannelProgressUpdate,
    ChannelThreadMode,
    ConversationChannelKind,
    ConversationExecutionStatus,
    ObservedExecutionActivity,
    OutboundResponse,
)
from fdai.shared.providers.workload_identity import IdentityToken
from fdai.shared.telemetry import ConversationProgressMetrics


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="workload-token",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            audience=audience,
        )


class _DiscardPublisher:
    async def publish(self, response: OutboundResponse) -> ChannelDeliveryReceipt:
        return ChannelDeliveryReceipt(
            channel_kind=response.channel_kind,
            channel_id=response.channel_id,
            operation=response.operation,
            message_id="discarded-message",
        )


def _response(kind: ConversationChannelKind, **changes: object) -> OutboundResponse:
    values: dict[str, object] = {
        "channel_kind": kind,
        "channel_id": "channel-1",
        "in_reply_to": "message-1",
        "thread_id": "thread-1",
        "status": "ok",
        "text": "reply",
    }
    values.update(changes)
    return OutboundResponse(**values)  # type: ignore[arg-type]


def _activities() -> tuple[AgentHandoffActivity, ObservedExecutionActivity]:
    return (
        AgentHandoffActivity(
            from_agent="Bragi",
            to_agent="Heimdall",
            task="Inspect the bounded metric evidence.",
        ),
        ObservedExecutionActivity(
            agent="Heimdall",
            label="Query metric evidence",
            tool="query_metric",
            command="query_metric --metric <redacted> --window <redacted>",
            status=ConversationExecutionStatus.COMPLETED,
            redacted=True,
            output='{"point_count":2,"status":"completed"}',
            exit_code=0,
            authority="server_read_model",
        ),
    )


async def test_slack_publisher_uses_fixed_endpoint_token_and_thread() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "ts": "2.0"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = SlackWebApiReplyPublisher(
            config=SlackReplyPublisherConfig(),
            token="app-token",
            http_client=client,
        )
        await publisher.publish(_response(ConversationChannelKind.SLACK))

    assert captured["url"] == "https://slack.com/api/chat.postMessage"
    assert captured["authorization"] == "Bearer app-token"
    assert captured["body"] == {"channel": "channel-1", "text": "reply", "thread_ts": "thread-1"}


async def test_teams_publisher_uses_server_owned_endpoint_and_identity() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "activity-2"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = TeamsBotFrameworkReplyPublisher(
            config=TeamsReplyPublisherConfig(),
            identity=_Identity(),
            endpoint_resolver=lambda _: "https://bot.example.com/conversations/1/activities",
            http_client=client,
        )
        await publisher.publish(_response(ConversationChannelKind.TEAMS))

    assert captured["url"] == "https://bot.example.com/conversations/1/activities"
    assert captured["authorization"] == "Bearer workload-token"
    assert captured["body"] == {"type": "message", "text": "reply", "replyToId": "message-1"}


async def test_slack_publisher_renders_agent_activity_blocks() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "ts": "2.0"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = SlackWebApiReplyPublisher(
            config=SlackReplyPublisherConfig(), token="app-token", http_client=client
        )
        await publisher.publish(_response(ConversationChannelKind.SLACK, activities=_activities()))

    text = str(captured["text"])
    blocks = captured["blocks"]
    assert "Bragi -> @Heimdall" in text
    assert "Command: query_metric" in text
    assert isinstance(blocks, list)
    assert "*Bragi* -> *@Heimdall*" in str(blocks[0])
    assert "query_metric" in str(blocks[1])
    assert blocks[2]["text"] == {
        "type": "plain_text",
        "text": "Command\nquery_metric --metric <redacted> --window <redacted>",
    }
    assert "point_count" in str(blocks[3])


async def test_slack_activity_preserves_command_backticks_verbatim() -> None:
    captured: dict[str, object] = {}
    command = "printf '%s' `date -u`"
    activity = ObservedExecutionActivity(
        agent="Heimdall",
        label="Inspect clock evidence",
        tool="query_log",
        command=command,
        status=ConversationExecutionStatus.COMPLETED,
        redacted=True,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "ts": "2.0"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = SlackWebApiReplyPublisher(
            config=SlackReplyPublisherConfig(), token="app-token", http_client=client
        )
        await publisher.publish(_response(ConversationChannelKind.SLACK, activities=(activity,)))

    blocks = captured["blocks"]
    assert isinstance(blocks, list)
    assert blocks[1]["text"] == {
        "type": "plain_text",
        "text": f"Command\n{command}",
    }


async def test_teams_publisher_renders_agent_activity_adaptive_card() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(201, json={"id": "activity-2"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = TeamsBotFrameworkReplyPublisher(
            config=TeamsReplyPublisherConfig(),
            identity=_Identity(),
            endpoint_resolver=lambda _: "https://bot.example.com/conversations/1/activities",
            http_client=client,
        )
        await publisher.publish(_response(ConversationChannelKind.TEAMS, activities=_activities()))

    assert "Bragi -> @Heimdall" in str(captured["text"])
    attachments = captured["attachments"]
    assert isinstance(attachments, list)
    card = attachments[0]["content"]
    assert card["type"] == "AdaptiveCard"
    assert "Bragi" in str(card["body"][0])
    assert "query_metric" in str(card["body"])
    assert "point_count" in str(card["body"])


async def test_teams_activity_card_stays_under_byte_budget() -> None:
    captured: dict[str, object] = {}
    activities = tuple(
        ObservedExecutionActivity(
            agent="Heimdall",
            label=f"Large evidence {index}",
            tool="query_log",
            command="q" * 7_000,
            status=ConversationExecutionStatus.COMPLETED,
            redacted=True,
            output="o" * 8_000,
        )
        for index in range(3)
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(201, json={"id": "activity-2"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = TeamsBotFrameworkReplyPublisher(
            config=TeamsReplyPublisherConfig(),
            identity=_Identity(),
            endpoint_resolver=lambda _: "https://bot.example.com/conversations/1/activities",
            http_client=client,
        )
        await publisher.publish(
            _response(ConversationChannelKind.TEAMS, activities=activities, text="a" * 16_000)
        )

    attachments = captured["attachments"]
    assert isinstance(attachments, list)
    card = attachments[0]["content"]
    assert len(json.dumps(card, separators=(",", ":")).encode("utf-8")) <= 24_000
    assert "additional activity" in str(card)
    assert "**Bragi**" in str(card["body"][-1])
    assert len(str(captured["text"])) <= 4_000


async def test_teams_multibyte_answer_stays_under_card_byte_budget() -> None:
    captured: dict[str, object] = {}
    activity = ObservedExecutionActivity(
        agent="Heimdall",
        label="Inspect health",
        tool="query_resource_health",
        command="query_resource_health --scope <redacted>",
        status=ConversationExecutionStatus.COMPLETED,
        redacted=True,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(201, json={"id": "activity-multibyte"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await TeamsBotFrameworkReplyPublisher(
            config=TeamsReplyPublisherConfig(),
            identity=_Identity(),
            endpoint_resolver=lambda _: "https://bot.example.com/conversations/1/activities",
            http_client=client,
        ).publish(
            _response(
                ConversationChannelKind.TEAMS,
                activities=(activity,),
                text="가" * 4_000,
            )
        )

    attachments = captured["attachments"]
    assert isinstance(attachments, list)
    card = attachments[0]["content"]
    assert len(json.dumps(card, separators=(",", ":")).encode("utf-8")) <= 24_000
    assert "[TRUNCATED]" in str(card["body"][-1])


async def test_activity_output_distinguishes_upstream_and_channel_truncation() -> None:
    slack_body: dict[str, object] = {}
    teams_body: dict[str, object] = {}
    upstream_activity = ObservedExecutionActivity(
        agent="Heimdall",
        label="Partial evidence",
        tool="query_log",
        command="query_log --scope <redacted>",
        status=ConversationExecutionStatus.COMPLETED,
        redacted=True,
        output="partial evidence",
        output_truncated=True,
    )
    both_activity = ObservedExecutionActivity(
        agent="Heimdall",
        label="Large partial evidence",
        tool="query_log",
        command="query_log --scope <redacted>",
        status=ConversationExecutionStatus.COMPLETED,
        redacted=True,
        output="x" * 5_000,
        output_truncated=True,
    )

    def slack_handler(request: httpx.Request) -> httpx.Response:
        slack_body.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "ts": "2.0"})

    def teams_handler(request: httpx.Request) -> httpx.Response:
        teams_body.update(json.loads(request.content))
        return httpx.Response(201, json={"id": "activity-2"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(slack_handler)) as client:
        await SlackWebApiReplyPublisher(
            config=SlackReplyPublisherConfig(), token="app-token", http_client=client
        ).publish(_response(ConversationChannelKind.SLACK, activities=(upstream_activity,)))
    async with httpx.AsyncClient(transport=httpx.MockTransport(teams_handler)) as client:
        await TeamsBotFrameworkReplyPublisher(
            config=TeamsReplyPublisherConfig(),
            identity=_Identity(),
            endpoint_resolver=lambda _: "https://bot.example.com/conversations/1/activities",
            http_client=client,
        ).publish(_response(ConversationChannelKind.TEAMS, activities=(both_activity,)))

    assert "[UPSTREAM OUTPUT TRUNCATED]" in str(slack_body["blocks"])
    assert "[CHANNEL OUTPUT TRUNCATED]" not in str(slack_body["blocks"])
    teams_card = teams_body["attachments"][0]["content"]  # type: ignore[index]
    assert "[UPSTREAM OUTPUT TRUNCATED]" in str(teams_card)
    assert "[CHANNEL OUTPUT TRUNCATED]" in str(teams_card)


async def test_teams_dedicated_thread_starts_without_reply_target() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "activity-dedicated"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = TeamsBotFrameworkReplyPublisher(
            config=TeamsReplyPublisherConfig(),
            identity=_Identity(),
            endpoint_resolver=lambda _: "https://bot.example.com/conversations/1/activities",
            http_client=client,
        )
        await publisher.publish(
            _response(
                ConversationChannelKind.TEAMS,
                thread_id=None,
                thread_mode=ChannelThreadMode.DEDICATED,
            )
        )

    assert captured["body"] == {"type": "message", "text": "reply"}


async def test_slack_native_rich_operations_return_acknowledgements() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path.endswith("chat.postMessage"):
            return httpx.Response(200, json={"ok": True, "ts": "2.0"})
        return httpx.Response(200, json={"ok": True})

    mention = ChannelMention(target_id="U123", display_text="Operator")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = SlackWebApiReplyPublisher(
            config=SlackReplyPublisherConfig(),
            token="app-token",
            http_client=client,
        )
        streamed = await publisher.publish(
            _response(
                ConversationChannelKind.SLACK,
                text="hello world",
                stream_chunks=("hello", " world"),
                mentions=(mention,),
            )
        )
        edited = await publisher.publish(
            _response(
                ConversationChannelKind.SLACK,
                text="corrected",
                edit_message_id="2.0",
            )
        )
        reacted = await publisher.publish(
            _response(
                ConversationChannelKind.SLACK,
                text="acknowledged",
                reaction="eyes",
            )
        )

    assert calls == [
        (
            "/api/chat.postMessage",
            {"channel": "channel-1", "text": "<@U123> hello", "thread_ts": "thread-1"},
        ),
        (
            "/api/chat.update",
            {"channel": "channel-1", "ts": "2.0", "text": "<@U123> hello world"},
        ),
        (
            "/api/chat.update",
            {"channel": "channel-1", "ts": "2.0", "text": "corrected"},
        ),
        (
            "/api/reactions.add",
            {"channel": "channel-1", "timestamp": "message-1", "name": "eyes"},
        ),
    ]
    assert (streamed.operation, streamed.message_id) == (ChannelDeliveryOperation.STREAM, "2.0")
    assert (edited.operation, edited.message_id) == (ChannelDeliveryOperation.EDIT, "2.0")
    assert (reacted.operation, reacted.message_id) == (
        ChannelDeliveryOperation.REACTION,
        "message-1",
    )


async def test_slack_stream_and_edit_updates_preserve_activity_blocks() -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    activity = ObservedExecutionActivity(
        agent="Heimdall",
        label="Inspect health",
        tool="query_resource_health",
        command="az resource show --ids <redacted-resource>",
        status=ConversationExecutionStatus.COMPLETED,
        redacted=True,
        output="state: Available",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path.endswith("chat.postMessage"):
            return httpx.Response(200, json={"ok": True, "ts": "2.0"})
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = SlackWebApiReplyPublisher(
            config=SlackReplyPublisherConfig(),
            token="app-token",
            http_client=client,
        )
        await publisher.publish(
            _response(
                ConversationChannelKind.SLACK,
                text="final answer",
                stream_chunks=("partial",),
                activities=(activity,),
            )
        )
        await publisher.publish(
            _response(
                ConversationChannelKind.SLACK,
                text="corrected",
                edit_message_id="2.0",
                activities=(activity,),
            )
        )

    update_bodies = [body for path, body in calls if path.endswith("chat.update")]
    assert len(update_bodies) == 2
    assert all("blocks" in body for body in update_bodies)
    assert all("Heimdall" in str(body["blocks"]) for body in update_bodies)
    assert "final answer" in str(update_bodies[0]["blocks"])
    assert "corrected" in str(update_bodies[1]["blocks"])


async def test_slack_progress_snapshots_post_once_then_edit_canonical_answer() -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    activities = (
        AgentHandoffActivity(from_agent="Bragi", to_agent="Heimdall", task="Inspect evidence"),
        ObservedExecutionActivity(
            agent="Heimdall",
            label="Inspect health",
            tool="query_resource_health",
            command="query_resource_health --scope <redacted>",
            status=ConversationExecutionStatus.COMPLETED,
            redacted=True,
        ),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"ok": True, "ts": "2.0"})

    metrics = ConversationProgressMetrics()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = SlackWebApiReplyPublisher(
            config=SlackReplyPublisherConfig(),
            token="app-token",
            http_client=client,
            progress_metrics=metrics,
        )
        await publisher.publish(
            _response(
                ConversationChannelKind.SLACK,
                text="Canonical answer",
                activities=activities,
                progress_updates=(
                    ChannelProgressUpdate(0, ChannelProgressStatus.RUNNING, "Inspect evidence", 1),
                    ChannelProgressUpdate(
                        1, ChannelProgressStatus.CONFIRMED, "Canonical answer", 2
                    ),
                ),
            )
        )

    assert [path for path, _body in calls] == ["/api/chat.postMessage", "/api/chat.update"]
    assert "blocks" not in calls[0][1]
    final_blocks = calls[1][1]["blocks"]
    assert str(final_blocks).count("Inspect evidence") == 1
    assert str(final_blocks).count("query_resource_health --scope <redacted>") == 1
    assert final_blocks[-1]["text"]["text"] == "*Bragi*\nCanonical answer"  # type: ignore[index]
    snapshot = metrics.snapshot()
    assert snapshot.counts["terminal_completed"] == 1
    assert snapshot.latency_ms["time_to_first_progress"].count == 1
    assert snapshot.latency_ms["time_to_first_confirmed"].count == 1


async def test_slack_progress_counts_canonical_answer_clipping_as_truncation() -> None:
    answer = "a" * 5_000
    activity = ObservedExecutionActivity(
        agent="Heimdall",
        label="Inspect health",
        tool="query_resource_health",
        command="query_resource_health --scope <redacted>",
        status=ConversationExecutionStatus.COMPLETED,
        redacted=True,
    )
    metrics = ConversationProgressMetrics()
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "ts": "2.0"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await SlackWebApiReplyPublisher(
            config=SlackReplyPublisherConfig(),
            token="app-token",
            http_client=client,
            progress_metrics=metrics,
        ).publish(
            _response(
                ConversationChannelKind.SLACK,
                text=answer,
                activities=(activity,),
                progress_updates=(
                    ChannelProgressUpdate(0, ChannelProgressStatus.RUNNING, "Checking", 0),
                    ChannelProgressUpdate(1, ChannelProgressStatus.CONFIRMED, answer, 1),
                ),
            )
        )

    assert "[TRUNCATED]" in str(calls[-1]["blocks"])
    assert metrics.snapshot().counts["truncations"] == 1


async def test_slack_progress_update_failure_is_ambiguous_after_initial_ack() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path.endswith("chat.postMessage"):
            return httpx.Response(200, json={"ok": True, "ts": "2.0"})
        return httpx.Response(500, json={"ok": False})

    metrics = ConversationProgressMetrics()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = SlackWebApiReplyPublisher(
            config=SlackReplyPublisherConfig(),
            token="app-token",
            http_client=client,
            progress_metrics=metrics,
        )
        with pytest.raises(ChannelDeliveryError) as raised:
            await publisher.publish(
                _response(
                    ConversationChannelKind.SLACK,
                    text="Canonical answer",
                    progress_updates=(
                        ChannelProgressUpdate(0, ChannelProgressStatus.RUNNING, "Checking", 0),
                        ChannelProgressUpdate(
                            1,
                            ChannelProgressStatus.CONFIRMED,
                            "Canonical answer",
                            0,
                        ),
                    ),
                )
            )

    assert calls == 2
    assert raised.value.acknowledgement_ambiguous is True
    assert metrics.snapshot().counts["channel_update_ambiguous"] == 1


async def test_slack_rich_features_degrade_to_thread_text() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "ts": f"{len(bodies)}.0"})

    config = SlackReplyPublisherConfig(
        supports_mentions=False,
        supports_streaming=False,
        supports_edits=False,
        supports_reactions=False,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = SlackWebApiReplyPublisher(
            config=config,
            token="app-token",
            http_client=client,
        )
        mentioned = await publisher.publish(
            _response(
                ConversationChannelKind.SLACK,
                mentions=(ChannelMention(target_id="U123", display_text="Operator"),),
            )
        )
        reacted = await publisher.publish(_response(ConversationChannelKind.SLACK, reaction="eyes"))

    assert bodies == [
        {"channel": "channel-1", "text": "@Operator reply", "thread_ts": "thread-1"},
        {
            "channel": "channel-1",
            "text": "reply\n\nReaction: eyes",
            "thread_ts": "thread-1",
        },
    ]
    assert mentioned.degraded_to_text is True
    assert reacted.degraded_to_text is True


async def test_teams_native_rich_operations_return_acknowledgements() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((request.method, str(request.url), body))
        if request.method == "POST":
            return httpx.Response(201, json={"id": "activity-2"})
        return httpx.Response(200)

    mention = ChannelMention(target_id="29:operator", display_text="Operator")
    endpoint = "https://bot.example.com/conversations/1/activities"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = TeamsBotFrameworkReplyPublisher(
            config=TeamsReplyPublisherConfig(),
            identity=_Identity(),
            endpoint_resolver=lambda _: endpoint,
            http_client=client,
        )
        streamed = await publisher.publish(
            _response(
                ConversationChannelKind.TEAMS,
                text="hello world",
                stream_chunks=("hello", " world"),
                mentions=(mention,),
            )
        )
        edited = await publisher.publish(
            _response(
                ConversationChannelKind.TEAMS,
                text="corrected",
                edit_message_id="activity-2",
            )
        )
        reacted = await publisher.publish(_response(ConversationChannelKind.TEAMS, reaction="like"))

    assert calls[0] == (
        "POST",
        endpoint,
        {
            "type": "message",
            "text": "<at>Operator</at> hello",
            "entities": [
                {
                    "type": "mention",
                    "text": "<at>Operator</at>",
                    "mentioned": {"id": "29:operator", "name": "Operator"},
                }
            ],
            "replyToId": "message-1",
        },
    )
    assert calls[1][0:2] == ("PUT", f"{endpoint}/activity-2")
    assert calls[1][2]["text"] == "<at>Operator</at> hello world"
    assert calls[2] == (
        "PUT",
        f"{endpoint}/activity-2",
        {"type": "message", "text": "corrected"},
    )
    assert calls[3] == (
        "POST",
        endpoint,
        {
            "type": "messageReaction",
            "replyToId": "message-1",
            "reactionsAdded": [{"type": "like"}],
        },
    )
    assert streamed.message_id == edited.message_id == "activity-2"
    assert reacted.operation is ChannelDeliveryOperation.REACTION


async def test_teams_progress_snapshots_post_once_then_edit_canonical_answer() -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    endpoint = "https://bot.example.com/conversations/1/activities"
    activity = ObservedExecutionActivity(
        agent="Heimdall",
        label="Inspect health",
        tool="query_resource_health",
        command="query_resource_health --scope <redacted>",
        status=ConversationExecutionStatus.COMPLETED,
        redacted=True,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, json.loads(request.content)))
        return httpx.Response(201 if request.method == "POST" else 200, json={"id": "activity-2"})

    metrics = ConversationProgressMetrics()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = TeamsBotFrameworkReplyPublisher(
            config=TeamsReplyPublisherConfig(),
            identity=_Identity(),
            endpoint_resolver=lambda _: endpoint,
            http_client=client,
            progress_metrics=metrics,
        )
        await publisher.publish(
            _response(
                ConversationChannelKind.TEAMS,
                text="Canonical answer",
                activities=(activity,),
                progress_updates=(
                    ChannelProgressUpdate(0, ChannelProgressStatus.RUNNING, "Inspecting", 0),
                    ChannelProgressUpdate(
                        1, ChannelProgressStatus.CONFIRMED, "Canonical answer", 1
                    ),
                ),
            )
        )

    assert [method for method, _body in calls] == ["POST", "PUT"]
    assert "attachments" not in calls[0][1]
    assert "Inspect health" in str(calls[1][1])
    assert "Canonical answer" in str(calls[1][1])
    assert metrics.snapshot().counts["terminal_completed"] == 1
    assert metrics.snapshot().counts.get("truncations", 0) == 0


async def test_teams_progress_counts_card_budget_activity_omission_as_truncation() -> None:
    activities = tuple(
        ObservedExecutionActivity(
            agent="Heimdall",
            label=f"Inspect evidence {index}",
            tool="query_resource_health",
            command=f"query_resource_health --scope <redacted> {'x' * 3_500}",
            status=ConversationExecutionStatus.COMPLETED,
            redacted=True,
        )
        for index in range(8)
    )
    metrics = ConversationProgressMetrics()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201 if request.method == "POST" else 200,
            json={"id": "activity-omission"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = TeamsBotFrameworkReplyPublisher(
            config=TeamsReplyPublisherConfig(),
            identity=_Identity(),
            endpoint_resolver=lambda _: "https://bot.example.com/conversations/1/activities",
            http_client=client,
            progress_metrics=metrics,
        )
        await publisher.publish(
            _response(
                ConversationChannelKind.TEAMS,
                text="Canonical answer",
                activities=activities,
                progress_updates=(
                    ChannelProgressUpdate(0, ChannelProgressStatus.RUNNING, "Checking", 0),
                    ChannelProgressUpdate(
                        1,
                        ChannelProgressStatus.CONFIRMED,
                        "Canonical answer",
                        len(activities),
                    ),
                ),
            )
        )

    assert metrics.snapshot().counts["truncations"] == 1


async def test_teams_progress_counts_canonical_answer_clipping_as_truncation() -> None:
    answer = "a" * 5_000
    activity = ObservedExecutionActivity(
        agent="Heimdall",
        label="Inspect health",
        tool="query_resource_health",
        command="query_resource_health --scope <redacted>",
        status=ConversationExecutionStatus.COMPLETED,
        redacted=True,
    )
    metrics = ConversationProgressMetrics()
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            201 if request.method == "POST" else 200,
            json={"id": "activity-answer-clipping"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = TeamsBotFrameworkReplyPublisher(
            config=TeamsReplyPublisherConfig(),
            identity=_Identity(),
            endpoint_resolver=lambda _: "https://bot.example.com/conversations/1/activities",
            http_client=client,
            progress_metrics=metrics,
        )
        await publisher.publish(
            _response(
                ConversationChannelKind.TEAMS,
                text=answer,
                activities=(activity,),
                progress_updates=(
                    ChannelProgressUpdate(0, ChannelProgressStatus.RUNNING, "Checking", 0),
                    ChannelProgressUpdate(1, ChannelProgressStatus.CONFIRMED, answer, 1),
                ),
            )
        )

    assert "[TRUNCATED]" in str(captured["attachments"])
    assert metrics.snapshot().counts["truncations"] == 1


async def test_teams_progress_update_failure_is_ambiguous_after_initial_ack() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.method == "POST":
            return httpx.Response(201, json={"id": "activity-2"})
        return httpx.Response(500, json={"error": "rejected"})

    metrics = ConversationProgressMetrics()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = TeamsBotFrameworkReplyPublisher(
            config=TeamsReplyPublisherConfig(),
            identity=_Identity(),
            endpoint_resolver=lambda _: "https://bot.example.com/conversations/1/activities",
            http_client=client,
            progress_metrics=metrics,
        )
        with pytest.raises(ChannelDeliveryError) as raised:
            await publisher.publish(
                _response(
                    ConversationChannelKind.TEAMS,
                    text="Canonical answer",
                    progress_updates=(
                        ChannelProgressUpdate(0, ChannelProgressStatus.RUNNING, "Checking", 0),
                        ChannelProgressUpdate(
                            1,
                            ChannelProgressStatus.CONFIRMED,
                            "Canonical answer",
                            0,
                        ),
                    ),
                )
            )

    assert calls == 2
    assert raised.value.acknowledgement_ambiguous is True
    assert metrics.snapshot().counts["channel_update_ambiguous"] == 1


async def test_teams_rich_features_degrade_to_thread_text() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"id": f"activity-{len(bodies)}"})

    config = TeamsReplyPublisherConfig(
        supports_mentions=False,
        supports_streaming=False,
        supports_edits=False,
        supports_reactions=False,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = TeamsBotFrameworkReplyPublisher(
            config=config,
            identity=_Identity(),
            endpoint_resolver=lambda _: "https://bot.example.com/conversations/1/activities",
            http_client=client,
        )
        streamed = await publisher.publish(
            _response(
                ConversationChannelKind.TEAMS,
                text="final answer",
                stream_chunks=("partial",),
                mentions=(ChannelMention(target_id="29:operator", display_text="Operator"),),
            )
        )
        edited = await publisher.publish(
            _response(
                ConversationChannelKind.TEAMS,
                text="corrected",
                edit_message_id="activity-1",
            )
        )

    assert bodies == [
        {
            "type": "message",
            "text": "@Operator final answer",
            "replyToId": "message-1",
        },
        {"type": "message", "text": "Update: corrected", "replyToId": "message-1"},
    ]
    assert streamed.degraded_to_text is True
    assert edited.degraded_to_text is True


async def test_provider_failure_classification_controls_safe_retry() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(429))
    ) as client:
        slack = SlackWebApiReplyPublisher(
            config=SlackReplyPublisherConfig(),
            token="app-token",
            http_client=client,
        )
        with pytest.raises(ChannelDeliveryError) as rejected:
            await slack.publish(_response(ConversationChannelKind.SLACK))

    assert rejected.value.code == "http_429"
    assert rejected.value.acknowledgement_ambiguous is False

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(201, content=b"not-json"))
    ) as client:
        teams = TeamsBotFrameworkReplyPublisher(
            config=TeamsReplyPublisherConfig(),
            identity=_Identity(),
            endpoint_resolver=lambda _: "https://bot.example.com/conversations/1/activities",
            http_client=client,
        )
        with pytest.raises(ChannelDeliveryError) as ambiguous:
            await teams.publish(_response(ConversationChannelKind.TEAMS))

    assert ambiguous.value.code == "ack_invalid"
    assert ambiguous.value.acknowledgement_ambiguous is True


def test_slack_route_rejects_bad_signature_and_accepts_signed_event() -> None:
    secret = "test-secret"
    timestamp = "1700000000"
    body = json.dumps(
        {
            "type": "event_callback",
            "event_id": "event-1",
            "event": {
                "type": "message",
                "channel": "channel-1",
                "user": "user-1",
                "text": "query_inventory compute.vm",
                "ts": "1.0",
            },
        }
    ).encode()
    base = b"v0:" + timestamp.encode() + b":" + body
    signature = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    channel = SlackBotChannel(
        signing_secret=secret,
        publisher=_DiscardPublisher(),
        clock=lambda: float(timestamp),
    )
    client = TestClient(Starlette(routes=[make_slack_events_route(channel=channel)]))

    assert client.post("/channels/slack/events", content=body).status_code == 401
    accepted = client.post(
        "/channels/slack/events",
        content=body,
        headers={"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature},
    )
    assert accepted.status_code == 202


def test_teams_route_authenticates_before_activity_parse() -> None:
    calls: list[str] = []

    async def authenticate(token: str) -> bool:
        calls.append(token)
        return token == "valid"

    channel = TeamsBotChannel(publisher=_DiscardPublisher())
    client = TestClient(
        Starlette(routes=[make_teams_activity_route(channel=channel, authenticate=authenticate)])
    )
    activity = {
        "type": "message",
        "id": "activity-1",
        "text": "query_audit",
        "from": {"id": "sender-1"},
        "conversation": {"id": "conversation-1"},
    }

    assert client.post("/channels/teams/activities", content=b"not-json").status_code == 401
    accepted = client.post(
        "/channels/teams/activities",
        json=activity,
        headers={"Authorization": "Bearer valid"},
    )
    assert accepted.status_code == 202
    assert calls == ["valid"]
