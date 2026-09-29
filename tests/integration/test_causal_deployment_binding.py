"""Deployment binding for the causal incident graph evidence path.

A deployment binds bounded temporal series with ``bind_azure_operational_evidence``. The runtime
then completes the path with Forseti's ``CausalHypothesis`` projection over the ontology store and
Thor's ActionRun receipt resolver. An independent ``ObservedOutcome`` of a verified intervention
closes the projected revision without granting execution authority.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fdai.composition import bind_azure_operational_evidence, default_container
from fdai.core.assurance_twin import EffectModelStatus, SimulationBranch
from fdai.core.rca import CausalHypothesisProjector, TemporalCausalityConfig
from fdai.core.rca.hypothesis import CausalActionMode, CausalClosure, causal_action_mode
from fdai.core.rca.runtime import CausalClosureObservation, CausalRuntimeOutcome
from fdai.delivery.azure.operational_evidence import (
    AzureDynamicPolicy,
    AzureOperationalSnapshot,
    AzureReuseSafetyChecks,
    AzureTemporalPolicy,
)
from fdai.delivery.persistence.state_store_causal_receipts import (
    StateStoreCausalInterventionReceiptVerifier,
)
from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.runtime.causal_bindings import build_causal_runtime_coordinator
from fdai.shared.config import AppConfig
from fdai.shared.contracts.models import CausalEvidenceGrade, Event
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.metric import MetricPoint, StaticMetricProvider
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore, InMemoryStateStore

_ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 8, 1, 1, tzinfo=UTC)
_RESOURCE = (
    "/subscriptions/example/resourceGroups/example/providers/"
    "Microsoft.ContainerService/managedClusters/example"
)
_RECEIPT = "e" * 64
_METHOD = "temporal-causality-v1"


def _config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "schema_version": "1.0.0",
            "azure": {
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "region": "krc",
            },
            "kafka": {"bootstrap_servers": "example:9093", "topic_events": "fdai.change.events"},
            "postgres": {"host": "example.local", "database": "fdai"},
            "runtime": {"env": "dev"},
            "llm": {"mode": "local-fake"},
        }
    )


class _Snapshots:
    async def get(self, resource_ref: str) -> AzureOperationalSnapshot | None:
        if resource_ref != _RESOURCE:
            return None
        return AzureOperationalSnapshot(
            resource_ref=_RESOURCE,
            resource_type="kubernetes.cluster",
            topology_roles=("hosts",),
            ownership_shape=("platform-team",),
            graph_digest="a" * 64,
            owner_digest="b" * 64,
            observed_at=_NOW,
            evidence_refs=("c" * 64,),
        )


class _Safety:
    async def evaluate(self, **_kwargs: Any) -> AzureReuseSafetyChecks:
        return AzureReuseSafetyChecks(True, True, True, True, True, True, True, ("d" * 64,))


class _Estimator:
    async def estimate(self, **_kwargs: Any) -> tuple[SimulationBranch, ...]:
        return (SimulationBranch("noop", "noop", 1.0, 0.1),)


class _Models:
    async def get(self, *, status: EffectModelStatus, action_type_id: str, metric: str) -> None:
        return None


class _EffectModelCausalEvidence:
    def verify(self, model: object) -> bool:
        return True


def _metrics() -> StaticMetricProvider:
    points: list[MetricPoint] = []
    for index in range(12):
        at = _NOW - timedelta(minutes=12 - index)
        labels = {"resource_id": _RESOURCE.casefold()}
        points.append(MetricPoint("node_cpu_percent", at, float(index), labels))
        points.append(MetricPoint("service_latency_ms", at, float(index * 2), labels))
    return StaticMetricProvider(points)


def _event() -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "idempotency_key": "event-1",
            "source": "azure-monitor",
            "event_type": "aks.node-pressure",
            "resource_ref": _RESOURCE,
            "detected_at": (_NOW - timedelta(seconds=1)).isoformat(),
            "ingested_at": _NOW.isoformat(),
            "mode": "shadow",
            "payload": {},
        }
    )


def _deployment_container() -> Any:
    container = replace(default_container(_config()), metric_provider=_metrics())
    return bind_azure_operational_evidence(
        container,
        snapshots=_Snapshots(),
        safety=_Safety(),
        temporal_policies={
            "aks.node-pressure": AzureTemporalPolicy(
                cause_metric="node_cpu_percent",
                effect_metric="service_latency_ms",
                mechanism="node-pressure",
                required_topology_role="hosts",
                lookback=timedelta(minutes=20),
                topological_reachability=0.9,
                mechanism_fit=0.8,
            )
        },
        temporal_config=TemporalCausalityConfig(lag_seconds=(0, 60), min_samples=4),
        branch_estimator=_Estimator(),
        dynamic_policies={"ops.scale-out": AzureDynamicPolicy(metric="latency_ms")},
        effect_models=_Models(),
        effect_model_causal_evidence=_EffectModelCausalEvidence(),
    )


def _ontology_store() -> InMemoryOntologyInstanceStore:
    registry = PackageResourceSchemaRegistry()
    vocabulary = _ROOT / "rule-catalog" / "vocabulary"
    object_types = load_object_type_catalog(vocabulary / "object-types", schema_registry=registry)
    link_types = load_link_type_catalog(
        vocabulary / "link-types",
        schema_registry=registry,
        object_types=object_types,
    )
    return InMemoryOntologyInstanceStore(object_types=object_types, link_types=link_types)


def _outcome(observed_at: datetime) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id="outcome-1",
        object_type="ObservedOutcome",
        properties={
            "id": "outcome-1",
            "action_run_id": "run-1",
            "verification": "verified",
            "recovery_status": "recovered",
            "observed_values": {"service_latency_ms": 4.0},
            "telemetry_complete": True,
            "scorable": True,
            "observed_at": observed_at.isoformat(),
        },
    )


async def _analyzed(store: InMemoryOntologyInstanceStore, audit: InMemoryStateStore) -> Any:
    coordinator = build_causal_runtime_coordinator(
        container=_deployment_container(),
        ontology_instance_store=store,
        audit_store=audit,
        method_version=_METHOD,
    )
    assert coordinator is not None
    result = await coordinator.analyze(event=_event(), incident_id="incident-1")
    assert result.outcome is CausalRuntimeOutcome.ANALYZED
    assert result.hypothesis is not None
    return coordinator, result.hypothesis


def _closure(hypothesis: Any, **changes: Any) -> CausalClosureObservation:
    observed_at = _NOW + timedelta(minutes=30)
    values: dict[str, Any] = {
        "hypothesis": hypothesis,
        "finding_id": f"finding:{_event().event_id}",
        "outcome_ref": "outcome-1",
        "observed_at": observed_at,
        "expected_direction_matched": True,
        "telemetry_complete": True,
        "within_window": True,
        "affected_scope_safe": True,
        "intervention_approved": True,
        "independent_observer": True,
        "intervention_receipt_digest": _RECEIPT,
        "intervention_executed_at": _NOW + timedelta(minutes=5),
        "intervention_target_ref": hypothesis.cause_ref,
        "predicted_effect_ref": hypothesis.effect_ref,
        "prohibited_effects_absent": True,
        "intervention_action_ref": "run-1",
        "endpoint_objects": (_outcome(observed_at),),
    }
    values.update(changes)
    return CausalClosureObservation(**values)


async def _seed_verified_run(audit: InMemoryStateStore, hypothesis_id: str) -> None:
    await audit.write_state(
        "thor:run|run-1",
        {
            "correlation_id": "run-1",
            "state": "succeeded",
            "shadow_mode": False,
            "resource_id": _RESOURCE,
            "params": {"causal_hypothesis_ref": hypothesis_id},
            "execution_closure_ref": _RECEIPT,
            "effect_verified_at": (_NOW + timedelta(minutes=10)).isoformat(),
        },
    )


async def test_deployment_binding_projects_revision_through_forseti_projection() -> None:
    store, audit = _ontology_store(), InMemoryStateStore()

    _, hypothesis = await _analyzed(store, audit)

    projected = await store.get_object(hypothesis.hypothesis_id)
    assert projected is not None
    assert projected.object_type == "CausalHypothesis"
    assert hypothesis.closure is None


async def test_verified_intervention_confirms_through_independent_outcome() -> None:
    store, audit = _ontology_store(), InMemoryStateStore()
    coordinator, hypothesis = await _analyzed(store, audit)
    await _seed_verified_run(audit, hypothesis.hypothesis_id)

    closed = await coordinator.close(_closure(hypothesis))

    assert closed.closure is CausalClosure.CONFIRMED
    assert await store.get_object(closed.hypothesis_id) is not None
    assert await store.get_object("outcome-1") is not None
    assert closed.evidence_grade is CausalEvidenceGrade.INTERVENTIONAL
    assert (
        causal_action_mode(closed, decision_evidence=None, evaluated_at=_NOW + timedelta(hours=1))
        is CausalActionMode.SHADOW
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"expected_direction_matched": False}, CausalClosure.REFUTED),
        ({"affected_scope_safe": False}, CausalClosure.UNSAFE),
        ({"telemetry_complete": False}, CausalClosure.INCONCLUSIVE),
        ({"intervention_action_ref": "run-unknown"}, CausalClosure.INCONCLUSIVE),
        ({"intervention_receipt_digest": "f" * 64}, CausalClosure.INCONCLUSIVE),
    ],
)
async def test_unverified_or_adverse_outcomes_never_confirm(
    changes: dict[str, Any], expected: CausalClosure
) -> None:
    store, audit = _ontology_store(), InMemoryStateStore()
    coordinator, hypothesis = await _analyzed(store, audit)
    await _seed_verified_run(audit, hypothesis.hypothesis_id)

    closed = await coordinator.close(_closure(hypothesis, **changes))

    assert closed.closure is expected
    assert (
        causal_action_mode(closed, decision_evidence=None, evaluated_at=_NOW + timedelta(hours=1))
        is CausalActionMode.SHADOW
    )


def test_runtime_binds_forseti_projection_and_receipt_resolver_when_absent() -> None:
    store, audit = _ontology_store(), InMemoryStateStore()

    coordinator = build_causal_runtime_coordinator(
        container=_deployment_container(),
        ontology_instance_store=store,
        audit_store=audit,
        method_version=_METHOD,
    )

    assert coordinator is not None
    assert isinstance(coordinator._projector, CausalHypothesisProjector)
    assert isinstance(
        coordinator._intervention_receipt_verifier,
        StateStoreCausalInterventionReceiptVerifier,
    )


def test_runtime_refuses_temporal_series_without_a_projection_store() -> None:
    with pytest.raises(RuntimeError, match="Forseti-owned projection"):
        build_causal_runtime_coordinator(
            container=_deployment_container(),
            ontology_instance_store=None,
            audit_store=InMemoryStateStore(),
            method_version=_METHOD,
        )


def test_runtime_leaves_the_causal_path_unbound_without_temporal_series() -> None:
    assert (
        build_causal_runtime_coordinator(
            container=default_container(_config()),
            ontology_instance_store=_ontology_store(),
            audit_store=InMemoryStateStore(),
            method_version=_METHOD,
        )
        is None
    )
