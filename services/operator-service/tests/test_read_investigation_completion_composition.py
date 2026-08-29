"""Focused environment and composition tests for completion ingress."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import fdai_operator_service.composition as composition_module
import pytest
from fdai_operator_service.composition import ProductionOperatorComposition
from fdai_operator_service.environment import (
    AUDIENCE_ENV,
    BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP_ENV,
    BACKGROUND_TASK_PROJECTION_TOPIC_ENV,
    DATABASE_ROLE_ENV,
    DATABASE_URL_ENV,
    GROUP_ENV,
    KAFKA_BOOTSTRAP_SERVERS_ENV,
    READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP_ENV,
    READ_INVESTIGATION_COMPLETION_TOPIC_ENV,
    SEMANTIC_PHYSICAL_TOPIC_ENV,
    SEMANTIC_PROJECTION_TOPIC_ENV,
    SEMANTIC_REQUEST_TOPIC_ENV,
    TENANT_ENV,
    OperatorEnvironment,
    OperatorServiceConfigurationError,
)

_BASE_ENV = {
    TENANT_ENV: "tenant",
    AUDIENCE_ENV: "audience",
    **{key: f"group-{index}" for index, key in enumerate(GROUP_ENV.values())},
}
_KAFKA_ENV = {
    KAFKA_BOOTSTRAP_SERVERS_ENV: "localhost:9092",
    SEMANTIC_REQUEST_TOPIC_ENV: "operator.semantic-turn.requests",
    SEMANTIC_PROJECTION_TOPIC_ENV: "core.semantic-turn.projections",
    SEMANTIC_PHYSICAL_TOPIC_ENV: "fdai.pantheon.objects",
}


def _verify(_token: str) -> Mapping[str, object]:
    return {"oid": "operator", "roles": []}


def test_completion_environment_uses_canonical_kafka_defaults() -> None:
    environment = OperatorEnvironment.parse({**_BASE_ENV, **_KAFKA_ENV})

    assert environment.read_investigation_completion_topic == (
        "core.read-investigation.completions"
    )
    assert environment.read_investigation_completion_consumer_group_id == (
        "operator-read-investigation-completion-v1"
    )
    assert environment.background_task_projection_topic == "core.background-task.projections"
    assert environment.background_task_projection_consumer_group_id == (
        "operator-background-task-projection-v1"
    )


def test_completion_environment_preserves_explicit_topic_and_group() -> None:
    environment = OperatorEnvironment.parse(
        {
            **_BASE_ENV,
            **_KAFKA_ENV,
            READ_INVESTIGATION_COMPLETION_TOPIC_ENV: "core.read-investigation.completed-v1",
            READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP_ENV: "operator-completion-replica",
        }
    )

    assert environment.read_investigation_completion_topic == (
        "core.read-investigation.completed-v1"
    )
    assert environment.read_investigation_completion_consumer_group_id == (
        "operator-completion-replica"
    )


def test_completion_topic_must_be_distinct_from_semantic_topics() -> None:
    with pytest.raises(OperatorServiceConfigurationError, match="MUST be distinct"):
        OperatorEnvironment.parse(
            {
                **_BASE_ENV,
                **_KAFKA_ENV,
                READ_INVESTIGATION_COMPLETION_TOPIC_ENV: "core.semantic-turn.projections",
            }
        )


def test_background_task_projection_topic_must_be_distinct_from_other_topics() -> None:
    with pytest.raises(OperatorServiceConfigurationError, match="MUST be distinct"):
        OperatorEnvironment.parse(
            {
                **_BASE_ENV,
                **_KAFKA_ENV,
                BACKGROUND_TASK_PROJECTION_TOPIC_ENV: "core.read-investigation.completions",
            }
        )


@pytest.mark.parametrize(
    "environment_name",
    [
        READ_INVESTIGATION_COMPLETION_TOPIC_ENV,
        READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP_ENV,
        BACKGROUND_TASK_PROJECTION_TOPIC_ENV,
        BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP_ENV,
    ],
)
def test_explicit_completion_transport_requires_kafka(environment_name: str) -> None:
    with pytest.raises(OperatorServiceConfigurationError, match="requires"):
        OperatorEnvironment.parse(
            {
                **_BASE_ENV,
                environment_name: "completion-override",
            }
        )


def test_production_composition_passes_completion_topic_to_kafka_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Any] = []

    class _Bus:
        def __init__(self, *, config: Any, credential: Any) -> None:
            del credential
            captured.append(config)

        async def start(self) -> None:
            return None

        async def aclose(self) -> None:
            return None

        async def probe_readiness(self) -> bool:
            return True

        def subscribe(self, topic: str, group_id: str) -> Any:
            del topic, group_id
            raise AssertionError("consumer is not started during composition")

        async def publish(self, topic: str, key: str, payload: Any) -> object:
            del topic, key, payload
            return object()

    monkeypatch.setattr(composition_module, "OperatorSemanticKafkaBus", _Bus)
    ProductionOperatorComposition(
        verifier_factory=lambda _environment: _verify,
    ).build_runtime(
        {
            **_BASE_ENV,
            **_KAFKA_ENV,
            "FDAI_EXECUTION_VENUE": "local",
            DATABASE_URL_ENV: "postgresql://example.invalid/fdai",
            DATABASE_ROLE_ENV: "fdai_operator",
        }
    )

    assert len(captured) == 1
    assert captured[0].read_investigation_completion_topic == (
        "core.read-investigation.completions"
    )
    assert captured[0].background_task_projection_topic == ("core.background-task.projections")
