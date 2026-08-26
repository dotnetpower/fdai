"""Assemble the complete logical topic registry for the Core runtime bus."""

from fdai_service_contracts.read_investigation import (
    READ_INVESTIGATION_COMPLETION_TOPIC,
    READ_INVESTIGATION_REQUEST_TOPIC,
)
from fdai_service_contracts.semantic_turn import (
    SEMANTIC_PROGRESS_TOPIC,
    SEMANTIC_PROJECTION_TOPIC,
    SEMANTIC_REQUEST_TOPIC,
)

from fdai.agents import OWNED_OBJECT_TOPICS
from fdai.core.readiness.coordinator import _TRANSITION_TOPIC
from fdai.delivery.agent_introspection_bus import AGENT_INTROSPECTION_TOPICS
from fdai.runtime.bootstrap_bindings import RECONCILIATION_TOPICS, RULE_GENERATION_TOPICS

RUNTIME_LOGICAL_TOPICS = (
    OWNED_OBJECT_TOPICS
    | AGENT_INTROSPECTION_TOPICS
    | frozenset(
        {
            _TRANSITION_TOPIC,
            SEMANTIC_REQUEST_TOPIC,
            SEMANTIC_PROJECTION_TOPIC,
            SEMANTIC_PROGRESS_TOPIC,
            READ_INVESTIGATION_REQUEST_TOPIC,
            READ_INVESTIGATION_COMPLETION_TOPIC,
        }
    )
    | RECONCILIATION_TOPICS
    | RULE_GENERATION_TOPICS
)
