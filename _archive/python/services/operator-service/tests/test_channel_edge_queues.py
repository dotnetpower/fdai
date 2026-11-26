"""Focused queue and endpoint checks for the Operator channel edge."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai_operator_service.families.conversation.channel_delivery_models import ChannelKind
from fdai_operator_service.families.conversation.channel_edge.models import InboundChannelTurn
from fdai_operator_service.families.conversation.channel_edge.queues import (
    SlackIngressQueue,
    TeamsEndpointRegistry,
    TeamsIngressQueue,
)
from fdai_operator_service.families.conversation.channel_edge.slack_ingress import (
    SlackIngressAction,
    SlackIngressError,
    SlackIngressResult,
)
from fdai_operator_service.families.conversation.channel_edge.teams_ingress import (
    AuthenticatedTeamsTurn,
    TeamsIngressError,
)

_NOW = datetime(2026, 8, 19, tzinfo=UTC)
_SERVICE_URL = "https://service.example.com"


def _turn(kind: ChannelKind, conversation_id: str = "conversation-example") -> InboundChannelTurn:
    return InboundChannelTurn(
        channel_kind=kind,
        channel_id=conversation_id,
        message_id=f"message-{conversation_id}",
        sender_id="vendor-user",
        text="Show current evidence.",
        thread_id=conversation_id,
    )


class _SlackIngress:
    def __init__(self, turn: InboundChannelTurn) -> None:
        self.turn = turn

    def parse(self, **_kwargs: object) -> SlackIngressResult:
        return SlackIngressResult(
            action=SlackIngressAction.ACCEPTED,
            turn=self.turn,
            principal_id="principal-example",
            verification_ref="slack-mapping:example",
        )


class _TeamsIngress:
    def __init__(self) -> None:
        self.conversation_id = "conversation-example"

    async def parse(self, **_kwargs: object) -> AuthenticatedTeamsTurn:
        return AuthenticatedTeamsTurn(
            turn=_turn(ChannelKind.TEAMS, self.conversation_id),
            service_url=_SERVICE_URL,
            principal_id="principal-example",
            verification_ref="teams-service-key:example",
        )


async def test_slack_queue_preserves_principal_and_applies_backpressure() -> None:
    queue = SlackIngressQueue(ingress=_SlackIngress(_turn(ChannelKind.SLACK)), capacity=1)  # type: ignore[arg-type]
    queue.accept(body=b"{}", headers={}, received_at=_NOW)
    with pytest.raises(SlackIngressError, match="queue is full"):
        queue.accept(body=b"{}", headers={}, received_at=_NOW)

    consumer = queue.receive()
    item = await anext(consumer)
    assert item.principal_id == "principal-example"
    await queue.close()
    with pytest.raises(StopAsyncIteration):
        await anext(consumer)


async def test_teams_queue_rejection_leaves_no_endpoint_binding() -> None:
    ingress = _TeamsIngress()
    endpoints = TeamsEndpointRegistry(allowed_service_urls=frozenset({_SERVICE_URL}))
    queue = TeamsIngressQueue(  # type: ignore[arg-type]
        ingress=ingress,
        endpoints=endpoints,
        capacity=1,
    )
    await queue.accept(body=b"{}", authorization="Bearer token", received_at=_NOW)
    ingress.conversation_id = "rejected-conversation"
    with pytest.raises(TeamsIngressError, match="queue is full"):
        await queue.accept(body=b"{}", authorization="Bearer token", received_at=_NOW)
    assert endpoints.resolve("rejected-conversation") is None

    consumer = queue.receive()
    assert (await anext(consumer)).turn.channel_id == "conversation-example"
    await queue.close()
    with pytest.raises(StopAsyncIteration):
        await anext(consumer)


async def test_full_slack_queue_closes_without_waiting_and_drains() -> None:
    queue = SlackIngressQueue(  # type: ignore[arg-type]
        ingress=_SlackIngress(_turn(ChannelKind.SLACK)),
        capacity=1,
    )
    queue.accept(body=b"{}", headers={}, received_at=_NOW)

    await queue.close()
    consumer = queue.receive()
    assert (await anext(consumer)).turn.message_id == "message-conversation-example"
    with pytest.raises(StopAsyncIteration):
        await anext(consumer)


def test_teams_endpoint_registry_rejects_change_and_capacity_exhaustion() -> None:
    endpoints = TeamsEndpointRegistry(
        allowed_service_urls=frozenset({_SERVICE_URL, "https://other.example.com"}),
        maximum=1,
    )
    endpoints.bind(
        conversation_id="conversation-example",
        service_url=_SERVICE_URL,
    )
    with pytest.raises(TeamsIngressError) as changed:
        endpoints.bind(
            conversation_id="conversation-example",
            service_url="https://other.example.com",
        )
    assert changed.value.http_status == 409
    with pytest.raises(TeamsIngressError) as full:
        endpoints.bind(
            conversation_id="other-conversation",
            service_url="https://service.example.com",
        )
    assert full.value.http_status == 503
