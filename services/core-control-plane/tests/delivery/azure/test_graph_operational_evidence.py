from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.assurance_twin import (
    DynamicInvariant,
    InvariantOperator,
)
from fdai.core.tiers.t1_lightweight import LearnedAction
from fdai.delivery.azure.graph_operational_evidence import (
    AzureCachedGraphOperationalSnapshotSource,
    AzureGraphDynamicPolicy,
    AzureGraphDynamicSimulationRequestProvider,
)
from fdai.shared.contracts.models import Event, Mode

_NOW = datetime(2026, 8, 10, 1, tzinfo=UTC)
_TARGET = "resource-workload-1"
_DEPENDENCY = "resource-database-1"


def _context(*, complete: bool = True, verified: bool = True, synthetic: bool = False):
    return {
        "resource_id": _TARGET,
        "resource_type": "compute.workload",
        "props": {
            "operational_context": {
                "graph_dynamic": {
                    "ontology_release_digest": "a" * 64,
                    "graph_revision": "graph-42",
                    "inventory_generation": "inventory-17",
                    "base_snapshot_id": "snapshot-9",
                    "observed_at": _NOW.isoformat(),
                    "objects": [
                        {
                            "object_ref": _TARGET,
                            "object_type": "compute.workload",
                            "revision": "workload-revision-8",
                            "metrics": {
                                "replicas": 2.0,
                                "p95_latency_ms": 220.0,
                                "error_rate": 0.01,
                                "availability": 0.999,
                                "run_rate": 80.0,
                            },
                            "evidence_refs": ["b" * 64],
                        },
                        {
                            "object_ref": _DEPENDENCY,
                            "object_type": "data.database",
                            "revision": "database-revision-3",
                            "metrics": {"availability": 0.9999},
                            "evidence_refs": ["c" * 64],
                        },
                    ],
                    "links": [
                        {
                            "source_ref": _TARGET,
                            "source_type": "compute.workload",
                            "link_type": "depends_on",
                            "target_ref": _DEPENDENCY,
                            "target_type": "data.database",
                            "observed_at": _NOW.isoformat(),
                            "freshness_seconds": 300,
                            "observation_source": "inventory-reader",
                            "verifier_identity": "topology-verifier",
                            "evidence_refs": ["d" * 64],
                            "complete": complete,
                            "verified": verified,
                            "synthetic": synthetic,
                            "conflicts": [],
                        }
                    ],
                    "source_watermarks": ["inventory-watermark-17"],
                    "complete": complete,
                    "truncated": not complete,
                }
            }
        },
    }


async def _reader(resource_ref: str):  # type: ignore[no-untyped-def]
    return _context() if resource_ref == _TARGET else None


def _event() -> Event:
    return Event(
        schema_version="1.0.0",
        event_id="00000000-0000-0000-0000-000000000301",
        idempotency_key="graph-dynamic-event",
        source="test",
        event_type="metric.latency.observed",
        resource_ref=_TARGET,
        detected_at=_NOW,
        ingested_at=_NOW,
        payload={},
        mode=Mode.SHADOW,
    )


def _action() -> LearnedAction:
    return LearnedAction(
        signature="experiment-scale-one-replica",
        rule_id="compute.latency.high",
        action_type="ops.scale-out",
        params={"replicas": 1},
        incident_id="incident-1",
        success_rate=0.9,
    )


def _policy() -> AzureGraphDynamicPolicy:
    return AzureGraphDynamicPolicy(
        action_type_ref="action-type:ops.scale-out@1.0.0",
        metric="replicas",
        effect_delta=1.0,
        horizon=timedelta(minutes=15),
        invariants=(
            DynamicInvariant(
                invariant_id="availability-floor",
                metric="availability",
                operator=InvariantOperator.GREATER_THAN_OR_EQUAL,
                threshold=0.99,
            ),
            DynamicInvariant(
                invariant_id="cost-envelope",
                metric="run_rate",
                operator=InvariantOperator.LESS_THAN_OR_EQUAL,
                threshold=100.0,
                target_ref=_TARGET,
            ),
        ),
        divergence_threshold=0.1,
        max_snapshot_age=timedelta(minutes=5),
        max_edges=64,
        max_slices=64,
    )


async def test_graph_provider_binds_exact_baseline_target_and_no_action_identity() -> None:
    source = AzureCachedGraphOperationalSnapshotSource(_reader)
    provider = AzureGraphDynamicSimulationRequestProvider(
        snapshots=source,
        policies={"ops.scale-out": _policy()},
        clock=lambda: _NOW + timedelta(seconds=1),
    )

    request = await provider.build(event=_event(), action=_action())

    assert request is not None
    assert request.baseline.ontology_release == "a" * 64
    assert request.baseline.graph_revision == "graph-42"
    assert request.baseline.inventory_generation == "inventory-17"
    assert request.baseline.base_snapshot_id == "snapshot-9"
    assert request.baseline.intervention_refs == ()
    assert request.baseline.complete is True
    assert request.topology[0].link_type == "depends_on"
    assert request.interventions[0].trigger_ref == "action-type:ops.scale-out@1.0.0"
    assert "workload-revision-8" in request.interventions[0].intervention_id
    assert "experiment-scale-one-replica" in request.interventions[0].intervention_id
    assert request.invariants == _policy().invariants


async def test_graph_provider_holds_untrusted_or_incomplete_topology() -> None:
    async def reader(resource_ref: str):  # type: ignore[no-untyped-def]
        assert resource_ref == _TARGET
        return _context(complete=False, verified=False, synthetic=True)

    provider = AzureGraphDynamicSimulationRequestProvider(
        snapshots=AzureCachedGraphOperationalSnapshotSource(reader),
        policies={"ops.scale-out": _policy()},
        clock=lambda: _NOW + timedelta(seconds=1),
    )

    assert await provider.build(event=_event(), action=_action()) is None


async def test_graph_provider_holds_stale_topology_without_partial_request() -> None:
    stale = _context()
    graph = stale["props"]["operational_context"]["graph_dynamic"]
    graph["links"][0]["observed_at"] = (_NOW - timedelta(minutes=6)).isoformat()

    async def reader(resource_ref: str):  # type: ignore[no-untyped-def]
        assert resource_ref == _TARGET
        return stale

    provider = AzureGraphDynamicSimulationRequestProvider(
        snapshots=AzureCachedGraphOperationalSnapshotSource(reader),
        policies={"ops.scale-out": _policy()},
        clock=lambda: _NOW + timedelta(seconds=1),
    )

    assert await provider.build(event=_event(), action=_action()) is None


async def test_graph_provider_is_explicitly_unavailable_without_action_policy() -> None:
    provider = AzureGraphDynamicSimulationRequestProvider(
        snapshots=AzureCachedGraphOperationalSnapshotSource(_reader),
        policies={"other.action": _policy()},
        clock=lambda: _NOW,
    )

    assert await provider.build(event=_event(), action=_action()) is None
