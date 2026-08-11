"""Operator semantic transport deployment mapping contracts."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_REQUEST_ENV = 'name  = "FDAI_SEMANTIC_TURN_REQUEST_TOPIC"'
_PROJECTION_ENV = 'name  = "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC"'


def test_legacy_operator_module_maps_configured_semantic_topics_once() -> None:
    module = (_ROOT / "infra/modules/operator-api/container-app/main.tf").read_text(
        encoding="utf-8"
    )

    assert 'name  = "FDAI_KAFKA_BOOTSTRAP_SERVERS"' in module
    assert _REQUEST_ENV in module
    assert _PROJECTION_ENV in module
    assert module.count(_REQUEST_ENV) == 1
    assert module.count(_PROJECTION_ENV) == 1
    assert "var.semantic_turn_request_topic" in module
    assert "var.semantic_turn_projection_topic" in module


def test_independent_operator_module_maps_configured_semantic_topics_once() -> None:
    module = (_ROOT / "infra/services/operator-service/modules/operator-service/main.tf").read_text(
        encoding="utf-8"
    )

    assert (
        '{ name = "FDAI_KAFKA_BOOTSTRAP_SERVERS", value = var.platform.kafka_bootstrap_servers }'
    ) in module
    assert module.count('name = "FDAI_SEMANTIC_TURN_REQUEST_TOPIC"') == 1
    assert module.count('name = "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC"') == 1
    assert "var.event_topics.semantic_requests" in module
    assert "var.event_topics.semantic_projections" in module
