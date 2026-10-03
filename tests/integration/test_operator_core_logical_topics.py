"""Every topic the Operator multiplexes onto the semantic Event Hub must be logical in Core."""

from __future__ import annotations

import asyncio
from dataclasses import fields

from fdai.delivery.event_bus_multiplex import MultiplexedEventBus
from fdai.runtime.bootstrap_topics import RUNTIME_LOGICAL_TOPICS
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai_operator_service.adapters.semantic_kafka import OperatorSemanticKafkaConfig
from fdai_service_contracts.framework_assessment import FRAMEWORK_ASSESSMENT_TOPIC
from fdai_service_contracts.observer_deployment import OBSERVER_PROPOSAL_TOPIC
from fdai_service_contracts.post_turn_review import POST_TURN_REVIEW_REQUEST_TOPIC
from fdai_service_contracts.wara_assessment import WARA_ASSESSMENT_TOPIC

# Event and HIL decision topics are provisioned physical Event Hubs, never multiplexed.
_DIRECT_FIELDS = frozenset({"event_topic", "hil_decision_topic", "physical_topic"})
# Dedicated Jobs publish these on their own multiplexed transport; Core never reads them.
_DEDICATED_JOB_TOPICS = frozenset(
    {WARA_ASSESSMENT_TOPIC, FRAMEWORK_ASSESSMENT_TOPIC, OBSERVER_PROPOSAL_TOPIC}
)
_PHYSICAL = "fdai.pantheon.objects"


def test_every_multiplexed_operator_topic_is_a_core_runtime_logical_topic() -> None:
    operator_topics = {
        field.default
        for field in fields(OperatorSemanticKafkaConfig)
        if field.name.endswith("_topic")
        and field.name not in _DIRECT_FIELDS
        and isinstance(field.default, str)
    }

    # A missing topic makes Core subscribe to a raw Event Hub that does not exist.
    assert operator_topics - _DEDICATED_JOB_TOPICS - RUNTIME_LOGICAL_TOPICS == set()


def test_core_receives_operator_post_turn_review_requests_from_the_physical_topic() -> None:
    transport = InMemoryEventBus()
    operator = MultiplexedEventBus(
        transport, frozenset({POST_TURN_REVIEW_REQUEST_TOPIC}), _PHYSICAL
    )
    core = MultiplexedEventBus(transport, RUNTIME_LOGICAL_TOPICS, _PHYSICAL)

    async def _exchange() -> list[str]:
        await operator.publish(POST_TURN_REVIEW_REQUEST_TOPIC, "request-1", {"value": 1})
        return [item.key async for item in core.subscribe(POST_TURN_REVIEW_REQUEST_TOPIC, "core")]

    assert asyncio.run(_exchange()) == ["request-1"]
