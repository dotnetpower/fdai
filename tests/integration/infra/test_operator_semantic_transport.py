"""Operator semantic transport deployment mapping contracts."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_REQUEST_ENV = 'name  = "FDAI_SEMANTIC_TURN_REQUEST_TOPIC"'
_PROJECTION_ENV = 'name  = "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC"'


def test_legacy_operator_module_maps_existing_kafka_and_exact_semantic_topics() -> None:
    module = (_ROOT / "infra/modules/operator-api/container-app/main.tf").read_text(
        encoding="utf-8"
    )

    assert 'name  = "FDAI_KAFKA_BOOTSTRAP_SERVERS"' in module
    assert _REQUEST_ENV in module
    assert 'for_each = var.kafka_bootstrap_servers == "" ? [] : ["operator-core-request"]' in module
    assert _PROJECTION_ENV in module
    assert (
        'for_each = var.kafka_bootstrap_servers == "" ? [] : ["core-operator-projection"]' in module
    )


def test_independent_operator_module_maps_existing_kafka_and_exact_semantic_topics() -> None:
    module = (_ROOT / "infra/services/operator-service/modules/operator-service/main.tf").read_text(
        encoding="utf-8"
    )

    assert (
        '{ name = "FDAI_KAFKA_BOOTSTRAP_SERVERS", value = var.platform.kafka_bootstrap_servers }'
    ) in module
    assert (
        '{ name = "FDAI_SEMANTIC_TURN_REQUEST_TOPIC", value = "operator-core-request" }' in module
    )
    assert (
        '{ name = "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC", value = "core-operator-projection" }'
    ) in module
