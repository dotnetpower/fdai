from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.agents._framework.adapters import canonical_json_digest
from fdai.agents._framework.runtime_health import report_agent_kpis, safe_agent_health
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn, _payload_digest
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _Mapping(Mapping[str, Any]):
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


class _StepClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(milliseconds=10)
        return value


class _Collector:
    def __init__(self) -> None:
        self.samples: list[tuple[str, dict[str, float], dict[str, dict[str, str]]]] = []

    def report_declared(
        self,
        *,
        agent: str,
        values: dict[str, float],
        tags: dict[str, str],
        metric_tags: dict[str, dict[str, str]] | None = None,
    ) -> None:
        del tags
        self.samples.append((agent, values, metric_tags or {}))


def test_strict_digest_normalizes_mapping_and_rejects_repr_values() -> None:
    payload = {"b": (2, 3), "a": {"nested": True}}
    mapping_payload = _Mapping({"a": _Mapping({"nested": True}), "b": [2, 3]})

    expected = "e316a862bccdf441309a574a17f77fff777dab52cdcbe0d3e853e76a3053f009"
    assert canonical_json_digest(payload) == expected
    assert canonical_json_digest(mapping_payload) == expected
    assert _payload_digest(mapping_payload) == expected

    with pytest.raises(TypeError):
        canonical_json_digest({"bad": object()})
    with pytest.raises(ValueError):
        canonical_json_digest({"bad": math.nan})


@pytest.mark.asyncio
async def test_saga_records_digest_unavailable_for_non_json_overflow_payload() -> None:
    saga = Saga()

    await saga.record_rate_limit_overflow("Norns", "object.rule-candidate", {"bad": object()})

    assert saga.behavior_snapshot()["rate_limit_overflow:payload_digest_unavailable"] == 1
    entry = saga.audit_chain.entries[-1]
    assert entry.topic == "object.audit-entry"


@pytest.mark.asyncio
async def test_mimir_health_reports_process_local_and_promotion_denominators() -> None:
    mimir = Mimir()

    with pytest.raises(ValueError):
        mimir.promote("rule.example", source="manual")
    mimir.promote(
        "rule.example",
        source="manual",
        reviewed_change_ref="catalog-pr:1",
        updated_at="2026-01-01T00:00:00+00:00",
    )

    health = mimir.health()
    assert health["status"] == "degraded"
    assert health["persistence"]["governance_state"] == "process_local"
    assert health["kpis"]["promotion_pass_rate"] == {
        "value": 0.5,
        "evidence_state": "measured",
        "numerator": 1,
        "denominator": 2,
        "unit": "ratio",
    }
    introspection = await mimir.introspect("promotion readiness", {})
    assert introspection.facts["promotion_ready_candidates"] is None
    assert introspection.facts["promotion_ready_candidates_evidence_state"] == "not_recomputed"


def test_muninn_health_records_fetch_kpis_and_context_unavailable_fact() -> None:
    clock = _StepClock()
    muninn = Muninn(case_history_clock=clock)
    owner = "operator@example.com"
    muninn.put_context(
        "conversation_turns",
        "turn-1",
        {"principal_scope": "sha256:wrong", "body": "redacted"},
    )
    muninn.put_context("resource_state", "r1", {"state": "ok"})

    assert muninn.get_context("resource_state", "r1") == {"state": "ok"}
    assert muninn.get_context("resource_state", "missing") is None
    assert muninn.get_context("conversation_turns", "turn-1", requester_user_id=owner) is None

    health = muninn.health()
    assert health["status"] == "degraded"
    assert health["context_store"]["durability"] == "process_local"
    assert health["context_unavailable"]["latest"]["reason"] == "cross_user_refused"
    assert health["kpis"]["cache_hit_rate"]["denominator"] == 3
    assert health["kpis"]["context_fetch_p99_seconds"]["evidence_state"] == "measured"


@pytest.mark.asyncio
async def test_muninn_health_reports_seeded_outbox_backlog() -> None:
    store = InMemoryStateStore()
    await store.write_state(
        "pantheon/muninn/operational-outbox/test",
        {"kind": "muninn_publication_outbox", "state": "pending", "revision": 1},
    )
    muninn = Muninn(durable_state_store=store)

    health = muninn.health()

    assert health["publication_outbox"]["pending"] == 1


def test_norns_health_reports_learning_degradation_and_complete_denominators() -> None:
    norns = Norns()
    for outcome in ("published", "held", "invalidated", "disabled", "rate_limited"):
        norns._record_candidate_terminal({"candidate": outcome}, outcome)
    norns.observe_pattern_validation(valid=True)
    norns.observe_pattern_validation(valid=False)

    health = norns.health()

    assert health["status"] == "degraded"
    assert health["learning"]["durability"] == "process_local"
    assert health["kpis"]["rule_candidate_adoption_rate"]["denominator"] == 5
    assert health["kpis"]["rule_candidate_adoption_rate"]["value"] == 0.2
    assert health["kpis"]["pattern_validity_rate"]["value"] == 0.5
    assert health["kpis"]["false_pattern_rate"]["value"] == 0.5


@pytest.mark.asyncio
async def test_norns_forecast_behavior_keys_do_not_embed_raw_labels() -> None:
    norns = Norns()
    for label in ("customer-label-a", "customer-label-b"):
        await norns._observe_forecast_case(
            {
                "kind": "forecast_case_history",
                "case_id": f"case-{label}",
                "revision": "1",
                "manifest_digest": "0" * 64,
                "detector_id": "detector",
                "metric": "latency",
                "outcome_label": label,
                "case_ref": "case-history:1",
            }
        )

    behavior = norns.behavior_snapshot()
    assert behavior["forecast_case:invalid_label"] == 2
    assert "forecast_case:customer-label-a" not in behavior
    assert "forecast_case:customer-label-b" not in behavior


def test_runtime_health_reports_measured_agent_kpis() -> None:
    norns = Norns()
    norns._record_candidate_terminal({"candidate": "published"}, "published")
    norns._record_candidate_terminal({"candidate": "disabled"}, "disabled")
    collector = _Collector()

    report_agent_kpis(collector, {"Norns": safe_agent_health("Norns", norns)})

    assert collector.samples == [
        (
            "Norns",
            {"rule_candidate_adoption_rate": 0.5},
            {"rule_candidate_adoption_rate": {"denominator": "2"}},
        )
    ]
