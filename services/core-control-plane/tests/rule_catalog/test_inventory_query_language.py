from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.schema.inventory_query_language import (
    InventoryQueryLanguageRegistryError,
    QueryTargetCardinality,
    inventory_query_language_digest,
    load_inventory_query_language_from_mapping,
    query_signal_matches,
    query_signal_span,
    query_target_cardinality,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
CATALOG = REPO_ROOT / "rule-catalog" / "vocabulary" / "inventory-query-language.yaml"


def test_shipped_inventory_query_language_loads() -> None:
    registry = load_inventory_query_language_from_mapping(
        yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    )
    assert registry.schema_version == "1.1.0"
    assert registry.default_scope == "subscription"
    assert registry.current_requires_fresh is True
    assert {"stopped", "paused", "failed", "degraded", "unavailable"} <= set(registry.states)
    assert registry.states["degraded"].evidence_authority == "subscription_health"
    assert registry.states["unavailable"].evidence_authority == "subscription_health"
    assert registry.states["inactive"].suppresses == ("running",)
    assert query_signal_matches(
        "Container App 요청이 갑자기 시간 초과돼.",
        registry,
        "symptom_request_timeout",
    )
    assert not query_signal_matches(
        "Container App 요청은 정상적으로 완료됐어.",
        registry,
        "symptom_request_timeout",
    )
    assert query_signal_matches(
        "주문 API Pod가 갑자기 재시작된 원인을 조사해줘.",
        registry,
        "symptom_pod_restart",
    )
    assert query_signal_matches(
        "이 VM의 CPU 급증 원인을 조사해줘.",
        registry,
        "symptom_cpu_spike",
    )
    assert query_signal_matches(
        "CPU 급증으로 영향을 받는 서비스를 조사해줘.",
        registry,
        "service_impact",
    )
    mysql_question = "DB 지연이 MySQL 포화인지 요청량 증가인지 반증 근거까지 포함해 판단해줘."
    assert query_signal_matches(mysql_question, registry, "symptom_database_latency")
    assert query_signal_matches(mysql_question, registry, "hypothesis_mysql_saturation")
    assert query_signal_matches(mysql_question, registry, "hypothesis_request_growth")
    latency_question = "지난 10분간 응답 지연이 네트워크 때문인지 애플리케이션 때문인지 비교해줘."
    assert query_signal_matches(latency_question, registry, "symptom_response_latency")
    assert query_signal_matches(latency_question, registry, "hypothesis_network_latency")
    assert query_signal_matches(latency_question, registry, "hypothesis_application_latency")
    assert query_signal_matches(
        "Container App에서 무엇이 변경됐어?",
        registry,
        "activity",
    )
    activation_utterance = "Container App이 activation failed 상태야."
    activation_start = activation_utterance.index("activation failed")
    assert query_signal_span(
        activation_utterance,
        registry,
        "symptom_activation_failure",
    ) == (
        activation_start,
        activation_start + len("activation failed"),
        "activation failed",
    )
    assert query_signal_span(
        "request timed out",
        registry,
        "symptom_request_timeout",
    ) == (0, len("request timed out"), "request timed out")
    unicode_prefix_utterance = "Straße request timeout"
    timeout_start = unicode_prefix_utterance.index("request timeout")
    assert query_signal_span(
        unicode_prefix_utterance,
        registry,
        "symptom_request_timeout",
    ) == (
        timeout_start,
        timeout_start + len("request timeout"),
        "request timeout",
    )
    assert (
        query_signal_span(
            "HTTP 500 이후 다시 HTTP 500 오류가 발생했어.",
            registry,
            "symptom_request_error",
        )
        is None
    )
    assert (
        query_target_cardinality(
            "내가 관리하는 Container App 상태를 보여줘",
            registry,
        )
        is QueryTargetCardinality.SINGULAR
    )
    assert (
        query_target_cardinality(
            "내 Container Apps 목록을 모두 보여줘",
            registry,
        )
        is QueryTargetCardinality.COLLECTION
    )
    assert (
        query_target_cardinality(
            "해당 Container Apps 목록을 보여줘",
            registry,
        )
        is QueryTargetCardinality.COLLECTION
    )
    assert (
        query_target_cardinality(
            "Show the small Container Apps",
            registry,
        )
        is QueryTargetCardinality.UNKNOWN
    )
    assert all(
        entry.description for entry in (*registry.states.values(), *registry.operations.values())
    )
    assert all(
        entry.examples for entry in (*registry.states.values(), *registry.operations.values())
    )


def test_inventory_query_language_digest_is_replay_stable() -> None:
    raw = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    registry = load_inventory_query_language_from_mapping(raw)
    reordered = {key: raw[key] for key in reversed(tuple(raw))}

    assert inventory_query_language_digest(registry).startswith("sha256:")
    assert inventory_query_language_digest(
        load_inventory_query_language_from_mapping(reordered)
    ) == inventory_query_language_digest(registry)


def test_inventory_query_language_rejects_unknown_fields() -> None:
    raw = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    raw["question_specific_override"] = True
    with pytest.raises(InventoryQueryLanguageRegistryError):
        load_inventory_query_language_from_mapping(raw)


def test_inventory_query_language_rejects_unknown_state_suppression() -> None:
    raw = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    raw["states"]["inactive"]["suppresses"] = ["not-a-state"]
    with pytest.raises(InventoryQueryLanguageRegistryError):
        load_inventory_query_language_from_mapping(raw)


@pytest.mark.parametrize(
    "values",
    ([], ["   "], [f"state-{index}" for index in range(17)]),
)
def test_inventory_query_language_rejects_unbounded_state_values(values: list[str]) -> None:
    raw = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    raw["states"]["running"]["values"] = values

    with pytest.raises(InventoryQueryLanguageRegistryError):
        load_inventory_query_language_from_mapping(raw)
