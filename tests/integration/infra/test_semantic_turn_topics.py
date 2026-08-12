"""Static contracts for dedicated semantic-turn Kafka topic wiring."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_REQUEST_TOPIC = "operator.semantic-turn.requests"
_PROJECTION_TOPIC = "core.semantic-turn.projections"
_REQUEST_ENV = "FDAI_SEMANTIC_TURN_REQUEST_TOPIC"
_PROJECTION_ENV = "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC"
_PHYSICAL_ENV = "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC"
_PHYSICAL_TOPIC = "aw.pantheon.objects"


def test_root_terraform_multiplexes_semantic_topics_over_provisioned_scope() -> None:
    root = (_ROOT / "infra/main.tf").read_text(encoding="utf-8")

    assert f'semantic_turn_request_topic    = "{_REQUEST_TOPIC}"' in root
    assert f'semantic_turn_projection_topic = "{_PROJECTION_TOPIC}"' in root
    assert f'semantic_turn_physical_topic   = "{_PHYSICAL_TOPIC}"' in root
    event_topics = root.split("event_topics = [", 1)[1].split("]", 1)[0]
    assert _REQUEST_TOPIC not in event_topics
    assert _PROJECTION_TOPIC not in event_topics
    assert f'"{_PHYSICAL_TOPIC}"' in event_topics
    assert "module.event_bus.topic_ids[local.semantic_turn_physical_topic]" in root


def test_event_hubs_module_rejects_entity_budget_overflow_before_apply() -> None:
    module = (_ROOT / "infra/modules/event-bus/event-hubs-kafka/main.tf").read_text(
        encoding="utf-8"
    )

    assert "length(var.topics) * 2 + length(var.auxiliary_topics) <= 10" in module
    assert "including generated DLQs" in module


def test_core_and_operator_service_roots_export_exact_semantic_env_vars() -> None:
    modules = (
        _ROOT / "infra/services/core-control-plane/modules/core-control-plane/main.tf",
        _ROOT / "infra/services/operator-service/modules/operator-service/main.tf",
    )

    for module in modules:
        text = module.read_text(encoding="utf-8")
        assert _REQUEST_ENV in text
        assert _PROJECTION_ENV in text
        assert _PHYSICAL_ENV in text
        assert "var.event_topics.semantic_requests" in text
        assert "var.event_topics.semantic_projections" in text
        assert "var.event_topics.semantic_physical" in text


def test_independent_service_child_modules_type_semantic_topic_inputs() -> None:
    for relative in (
        "infra/services/core-control-plane/modules/core-control-plane/variables.tf",
        "infra/services/operator-service/modules/operator-service/variables.tf",
    ):
        text = (_ROOT / relative).read_text(encoding="utf-8")
        assert 'semantic_requests    = optional(string, "")' in text
        assert 'semantic_projections = optional(string, "")' in text
        assert 'semantic_physical    = optional(string, "aw.pantheon.objects")' in text


def test_legacy_container_modules_export_exact_semantic_env_vars() -> None:
    modules = (
        _ROOT / "infra/modules/compute/container-apps/main.tf",
        _ROOT / "infra/modules/operator-api/container-app/main.tf",
    )

    for module in modules:
        text = module.read_text(encoding="utf-8")
        assert _REQUEST_ENV in text
        assert _PROJECTION_ENV in text
        assert _PHYSICAL_ENV in text
