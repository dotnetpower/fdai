"""Static contracts for dedicated semantic-turn Kafka topic wiring."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_REQUEST_TOPIC = "operator.semantic-turn.requests"
_PROJECTION_TOPIC = "core.semantic-turn.projections"
_REQUEST_ENV = "FDAI_SEMANTIC_TURN_REQUEST_TOPIC"
_PROJECTION_ENV = "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC"


def test_root_terraform_provisions_dedicated_topics_and_scoped_rbac() -> None:
    root = (_ROOT / "infra/main.tf").read_text(encoding="utf-8")

    assert f'semantic_turn_request_topic    = "{_REQUEST_TOPIC}"' in root
    assert f'semantic_turn_projection_topic = "{_PROJECTION_TOPIC}"' in root
    assert "(local.semantic_turn_request_topic)" in root
    assert "(local.semantic_turn_projection_topic)" in root
    assert "module.event_bus.topic_ids[local.semantic_turn_request_topic]" in root
    assert "module.event_bus.topic_ids[local.semantic_turn_projection_topic]" in root


def test_core_and_operator_service_roots_export_exact_semantic_env_vars() -> None:
    modules = (
        _ROOT / "infra/services/core-control-plane/modules/core-control-plane/main.tf",
        _ROOT / "infra/services/operator-service/modules/operator-service/main.tf",
    )

    for module in modules:
        text = module.read_text(encoding="utf-8")
        assert _REQUEST_ENV in text
        assert _PROJECTION_ENV in text
        assert "var.event_topics.semantic_requests" in text
        assert "var.event_topics.semantic_projections" in text


def test_legacy_container_modules_export_exact_semantic_env_vars() -> None:
    modules = (
        _ROOT / "infra/modules/compute/container-apps/main.tf",
        _ROOT / "infra/modules/operator-api/container-app/main.tf",
    )

    for module in modules:
        text = module.read_text(encoding="utf-8")
        assert _REQUEST_ENV in text
        assert _PROJECTION_ENV in text
