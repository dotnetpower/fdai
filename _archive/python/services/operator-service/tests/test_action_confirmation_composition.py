"""Focused production composition test for confirmed operator actions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import fdai_operator_service.composition as composition_module
import pytest
from fdai_operator_service.composition import ProductionOperatorComposition
from fdai_operator_service.environment import (
    AUDIENCE_ENV,
    DATABASE_ROLE_ENV,
    DATABASE_URL_ENV,
    GROUP_ENV,
    KAFKA_BOOTSTRAP_SERVERS_ENV,
    OPERATOR_REQUEST_OPERATOR_SIGNING_SEED_ENV,
    OPERATOR_REQUEST_RECEIPT_PRODUCER_ID_ENV,
    SEMANTIC_PHYSICAL_TOPIC_ENV,
    SEMANTIC_PROJECTION_TOPIC_ENV,
    SEMANTIC_REQUEST_TOPIC_ENV,
    TENANT_ENV,
)

_BASE_ENV = {
    TENANT_ENV: "tenant",
    AUDIENCE_ENV: "audience",
    **{key: f"group-{index}" for index, key in enumerate(GROUP_ENV.values())},
    KAFKA_BOOTSTRAP_SERVERS_ENV: "localhost:9092",
    SEMANTIC_REQUEST_TOPIC_ENV: "operator.semantic-turn.requests",
    SEMANTIC_PROJECTION_TOPIC_ENV: "core.semantic-turn.projections",
    SEMANTIC_PHYSICAL_TOPIC_ENV: "fdai.pantheon.objects",
    "KAFKA_TOPIC_EVENTS": "fdai.events",
    "FDAI_EXECUTION_VENUE": "local",
    DATABASE_URL_ENV: "postgresql://example.invalid/fdai",
    DATABASE_ROLE_ENV: "fdai_operator",
    OPERATOR_REQUEST_OPERATOR_SIGNING_SEED_ENV: "A" * 43,
    OPERATOR_REQUEST_RECEIPT_PRODUCER_ID_ENV: "operator-service",
}


def _verify(_token: str) -> Mapping[str, object]:
    return {"oid": "operator", "roles": []}


def test_production_composition_binds_action_confirmation_to_core_event_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action_captured: list[tuple[object, object, str]] = []
    intervention_captured: list[tuple[object, object]] = []

    class _Bus:
        def __init__(self, *, config: Any, credential: Any) -> None:
            del config, credential

        async def start(self) -> None:
            return None

        async def aclose(self) -> None:
            return None

        async def probe_readiness(self) -> bool:
            return True

        def subscribe(self, topic: str, group_id: str) -> Any:
            del topic, group_id
            raise AssertionError("consumer is not started during composition")

        async def publish(
            self,
            topic: str,
            key: str,
            payload: Mapping[str, object],
        ) -> object:
            del topic, key, payload
            return object()

    class _Bridge:
        def __init__(
            self,
            *,
            store: object,
            publisher: object,
            topic: str,
            receipt_issuer: object | None = None,
        ) -> None:
            action_captured.append((store, publisher, topic))
            assert receipt_issuer is not None

        def workers_ready(self) -> bool:
            return True

        async def start(self) -> None:
            return None

        async def aclose(self) -> None:
            return None

    class _InterventionBridge:
        def __init__(self, *, store: object, publisher: object) -> None:
            intervention_captured.append((store, publisher))

        def workers_ready(self) -> bool:
            return True

        async def start(self) -> None:
            return None

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(composition_module, "OperatorSemanticKafkaBus", _Bus)
    monkeypatch.setattr(composition_module, "ActionConfirmationBridge", _Bridge)
    monkeypatch.setattr(
        composition_module,
        "IncidentInterventionBridge",
        _InterventionBridge,
    )

    runtime = ProductionOperatorComposition(
        verifier_factory=lambda _environment: _verify,
    ).build_runtime(_BASE_ENV)

    assert len(action_captured) == 1
    store, publisher, topic = action_captured[0]
    assert store is not None
    assert publisher is not None
    assert topic == "fdai.events"
    assert intervention_captured == [(store, publisher)]
    assert runtime.lifecycle is not None


async def test_production_composition_does_not_bind_action_confirmation_without_receipt_issuer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action_captured: list[tuple[object, object, str]] = []

    class _Bus:
        def __init__(self, *, config: Any, credential: Any) -> None:
            del config, credential

        async def start(self) -> None:
            return None

        async def aclose(self) -> None:
            return None

        async def probe_readiness(self) -> bool:
            return True

        def subscribe(self, topic: str, group_id: str) -> Any:
            del topic, group_id
            raise AssertionError("consumer is not started during composition")

        async def publish(
            self,
            topic: str,
            key: str,
            payload: Mapping[str, object],
        ) -> object:
            del topic, key, payload
            return object()

    class _Bridge:
        def __init__(
            self,
            *,
            store: object,
            publisher: object,
            topic: str,
            receipt_issuer: object | None = None,
        ) -> None:
            del receipt_issuer
            action_captured.append((store, publisher, topic))

    monkeypatch.setattr(composition_module, "OperatorSemanticKafkaBus", _Bus)
    monkeypatch.setattr(composition_module, "ActionConfirmationBridge", _Bridge)

    runtime = ProductionOperatorComposition(
        verifier_factory=lambda _environment: _verify,
    ).build_runtime(
        {
            key: value
            for key, value in _BASE_ENV.items()
            if key
            not in {
                OPERATOR_REQUEST_OPERATOR_SIGNING_SEED_ENV,
                OPERATOR_REQUEST_RECEIPT_PRODUCER_ID_ENV,
            }
        }
    )

    assert action_captured == []
    assert runtime.lifecycle is not None
    assert runtime.readiness_probe is not None
    assert await runtime.readiness_probe() is False
