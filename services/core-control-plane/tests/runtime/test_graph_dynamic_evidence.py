from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest
from fdai.composition import default_container
from fdai.core.assurance_twin import EffectModelStatus, GraphDynamicRuntimeCoordinator
from fdai.core.tiers.t1_lightweight import LearnedAction
from fdai.runtime.graph_dynamic_evidence import (
    GRAPH_DYNAMIC_CONFIG_ENV,
    bind_graph_dynamic_evidence_from_env,
)
from fdai.shared.config import AppConfig
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.testing import InMemoryStateStore

_NOW = datetime(2026, 8, 10, 1, tzinfo=UTC)
_TARGET = "workload-1"


def _app_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "schema_version": "1.0.0",
            "azure": {
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "region": "krc",
            },
            "kafka": {"bootstrap_servers": "example:9093", "topic_events": "events"},
            "postgres": {"host": "example.local", "database": "fdai"},
            "runtime": {"env": "dev"},
            "llm": {"mode": "local-fake"},
        }
    )


def _model(status: str) -> dict[str, object]:
    return {
        "model_id": f"scale-latency-{status}",
        "version": "1.0.0",
        "revision": 1,
        "status": status,
        "trigger_ref": "action-type:ops.scale-out@1.0.0",
        "source_type": "compute.workload",
        "link_path": ["depends_on"],
        "target_type": "data.database",
        "target_metric": "availability",
        "propagation_lag_seconds": 60,
        "gain": 0.0,
        "offset": 0.0,
        "interval_radius": 0.001,
        "evidence_grade": "quasi_experimental",
        "causal_evidence_receipt_digest": "a" * 64,
        "learned_through": "2026-08-09T00:00:00Z",
        "sample_count": 40,
        "mean_absolute_error": 0.0001,
        "applied_observation_digests": [],
        "artifact_digest": "f" * 64,
        "ontology_release_digest": "b" * 64,
        "property_semantics_digest": "c" * 64,
        "applicability_conditions": ["environment=non-production"],
    }


def _config() -> str:
    return json.dumps(
        {
            "actions": {
                "ops.scale-out": {
                    "action_type_ref": "action-type:ops.scale-out@1.0.0",
                    "metric": "replicas",
                    "effect_delta": 1.0,
                    "horizon_seconds": 900,
                    "divergence_threshold": 0.1,
                    "max_snapshot_age_seconds": 300,
                    "max_edges": 64,
                    "max_slices": 64,
                    "invariants": [
                        {
                            "invariant_id": "availability-floor",
                            "metric": "availability",
                            "operator": "greater_than_or_equal",
                            "threshold": 0.99,
                        },
                        {
                            "invariant_id": "cost-envelope",
                            "metric": "run_rate",
                            "operator": "less_than_or_equal",
                            "threshold": 100.0,
                            "target_ref": _TARGET,
                        },
                    ],
                }
            },
            "causal_receipt_digests": ["a" * 64],
            "models": [_model("active"), _model("challenger")],
        }
    )


async def _inventory_context(resource_ref: str) -> Mapping[str, object] | None:
    if resource_ref != _TARGET:
        return None
    observed_at = datetime.now(tz=UTC).isoformat()
    return {
        "resource_id": _TARGET,
        "resource_type": "compute.workload",
        "props": {
            "operational_context": {
                "graph_dynamic": {
                    "ontology_release_digest": "b" * 64,
                    "graph_revision": "graph-1",
                    "inventory_generation": "inventory-1",
                    "base_snapshot_id": "baseline-1",
                    "observed_at": observed_at,
                    "objects": [
                        {
                            "object_ref": _TARGET,
                            "object_type": "compute.workload",
                            "revision": "revision-1",
                            "metrics": {"replicas": 2.0, "run_rate": 80.0},
                            "evidence_refs": ["c" * 64],
                        },
                        {
                            "object_ref": "database-1",
                            "object_type": "data.database",
                            "revision": "revision-2",
                            "metrics": {"availability": 0.999},
                            "evidence_refs": ["d" * 64],
                        },
                    ],
                    "links": [
                        {
                            "source_ref": _TARGET,
                            "source_type": "compute.workload",
                            "link_type": "depends_on",
                            "target_ref": "database-1",
                            "target_type": "data.database",
                            "observed_at": observed_at,
                            "freshness_seconds": 300,
                            "observation_source": "inventory-reader",
                            "verifier_identity": "topology-verifier",
                            "evidence_refs": ["e" * 64],
                            "complete": True,
                            "verified": True,
                            "synthetic": False,
                            "conflicts": [],
                        }
                    ],
                    "source_watermarks": ["watermark-1"],
                    "complete": True,
                    "truncated": False,
                }
            }
        },
    }


def _event() -> Event:
    now = datetime.now(tz=UTC)
    return Event(
        schema_version="1.0.0",
        event_id="00000000-0000-0000-0000-000000000401",
        idempotency_key="graph-runtime-event",
        source="test",
        event_type="metric.latency.observed",
        resource_ref=_TARGET,
        detected_at=now,
        ingested_at=now,
        payload={},
        mode=Mode.SHADOW,
    )


def _action() -> LearnedAction:
    return LearnedAction(
        signature="scale-one",
        rule_id="latency.high",
        action_type="ops.scale-out",
        params={"replicas": 1},
        incident_id="incident-1",
        success_rate=0.9,
    )


async def test_graph_binding_is_unavailable_without_explicit_config() -> None:
    container = default_container(_app_config())

    bound = await bind_graph_dynamic_evidence_from_env(
        container,
        state_store=InMemoryStateStore(),
        environ={},
    )

    assert bound is container
    assert bound.graph_dynamic_simulation_request_provider is None


async def test_graph_binding_registers_verified_active_and_challenger_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "fdai.runtime.graph_dynamic_evidence._build_inventory_context_provider",
        lambda: _inventory_context,
    )
    bound = await bind_graph_dynamic_evidence_from_env(
        default_container(_app_config()),
        state_store=InMemoryStateStore(),
        environ={GRAPH_DYNAMIC_CONFIG_ENV: _config()},
    )

    assert bound.graph_effect_model_reader is not None
    active = await bound.graph_effect_model_reader.list_models(
        status=EffectModelStatus.ACTIVE,
        trigger_refs=("action-type:ops.scale-out@1.0.0",),
    )
    challenger = await bound.graph_effect_model_reader.list_models(
        status=EffectModelStatus.CHALLENGER,
        trigger_refs=("action-type:ops.scale-out@1.0.0",),
    )
    assert len(active) == len(challenger) == 1


async def test_graph_binding_produces_read_only_simulation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "fdai.runtime.graph_dynamic_evidence._build_inventory_context_provider",
        lambda: _inventory_context,
    )
    bound = await bind_graph_dynamic_evidence_from_env(
        default_container(_app_config()),
        state_store=InMemoryStateStore(),
        environ={GRAPH_DYNAMIC_CONFIG_ENV: _config()},
    )
    assert bound.graph_dynamic_simulation_request_provider is not None
    assert bound.graph_effect_model_reader is not None
    assert bound.graph_effect_model_causal_evidence_verifier is not None
    coordinator = GraphDynamicRuntimeCoordinator(
        request_provider=bound.graph_dynamic_simulation_request_provider,
        model_reader=bound.graph_effect_model_reader,
        causal_evidence_verifier=bound.graph_effect_model_causal_evidence_verifier,
    )

    result = await coordinator.simulate(event=_event(), action=_action())

    assert result.simulation is not None
    assert result.simulation.active_trajectory.intervention_refs == (
        result.simulation.active_trajectory.intervention_refs[0],
    )
    assert result.simulation.invariant_results[0].status.value == "passed"
    assert all(not item.independent_observer for item in result.simulation.active_trajectory.slices)


@pytest.mark.parametrize(
    "value",
    (
        "not-json",
        json.dumps({"actions": {}}),
        json.dumps({"actions": {}, "causal_receipt_digests": [], "models": []}),
    ),
)
async def test_graph_binding_rejects_partial_config(value: str) -> None:
    with pytest.raises(ValueError):
        await bind_graph_dynamic_evidence_from_env(
            default_container(_app_config()),
            state_store=InMemoryStateStore(),
            environ={GRAPH_DYNAMIC_CONFIG_ENV: value},
        )
