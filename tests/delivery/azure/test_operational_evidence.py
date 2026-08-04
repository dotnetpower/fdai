from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.assurance_twin import SimulationBranch
from fdai.core.case_history import FailureFingerprint
from fdai.core.tiers.t1_lightweight import LearnedAction, OperationalCaseContext
from fdai.delivery.azure.operational_evidence import (
    AzureCachedOperationalSnapshotSource,
    AzureCurrentReuseVerifier,
    AzureDynamicPolicy,
    AzureDynamicSimulationRequestProvider,
    AzureOperationalSnapshot,
    AzureReuseSafetyChecks,
    AzureTemporalCausalEvidenceProvider,
    AzureTemporalPolicy,
)
from fdai.shared.contracts.models import Event
from fdai.shared.providers.metric import MetricPoint, StaticMetricProvider

_NOW = datetime(2026, 8, 1, 1, tzinfo=UTC)
_RESOURCE = (
    "/subscriptions/example/resourceGroups/example/providers/"
    "Microsoft.ContainerService/managedClusters/example"
)


def _clock() -> datetime:
    return _NOW + timedelta(seconds=1)


def _fingerprint() -> FailureFingerprint:
    return FailureFingerprint(
        resource_type="kubernetes.cluster",
        failure_mechanism="node-pressure",
        symptom_codes=("high-cpu",),
        topology_roles=("hosts",),
        ownership_shape=("platform-team",),
    )


def _event(*, event_type: str = "aks.node-pressure") -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "idempotency_key": "event-1",
            "source": "azure-monitor",
            "event_type": event_type,
            "resource_ref": _RESOURCE,
            "detected_at": (_NOW - timedelta(seconds=1)).isoformat(),
            "ingested_at": _NOW.isoformat(),
            "mode": "shadow",
            "payload": {"failure_fingerprint": _fingerprint().to_mapping()},
        }
    )


def _snapshot() -> AzureOperationalSnapshot:
    return AzureOperationalSnapshot(
        resource_ref=_RESOURCE,
        resource_type="kubernetes.cluster",
        topology_roles=("hosts",),
        ownership_shape=("platform-team",),
        graph_digest="a" * 64,
        owner_digest="b" * 64,
        observed_at=_NOW + timedelta(seconds=1),
        evidence_refs=("c" * 64,),
    )


class _Snapshots:
    async def get(self, resource_ref: str) -> AzureOperationalSnapshot | None:
        return _snapshot() if resource_ref == _RESOURCE else None


class _HistoricalSnapshots:
    async def get(self, resource_ref: str) -> AzureOperationalSnapshot | None:
        if resource_ref != _RESOURCE:
            return None
        snapshot = _snapshot()
        return AzureOperationalSnapshot(
            resource_ref=snapshot.resource_ref,
            resource_type=snapshot.resource_type,
            topology_roles=snapshot.topology_roles,
            ownership_shape=snapshot.ownership_shape,
            graph_digest=snapshot.graph_digest,
            owner_digest=snapshot.owner_digest,
            observed_at=_NOW,
            evidence_refs=snapshot.evidence_refs,
        )


async def test_cached_snapshot_source_requires_complete_operational_manifest() -> None:
    async def reader(resource_ref: str):  # type: ignore[no-untyped-def]
        return {
            "resource_id": resource_ref,
            "resource_type": "kubernetes.cluster",
            "props": {
                "operational_context": {
                    "topology_roles": ["hosts"],
                    "ownership_shape": ["platform-team"],
                    "graph_digest": "a" * 64,
                    "owner_digest": "b" * 64,
                    "observed_at": (_NOW + timedelta(seconds=1)).isoformat(),
                    "evidence_refs": ["c" * 64],
                }
            },
        }

    snapshot = await AzureCachedOperationalSnapshotSource(reader).get(_RESOURCE)

    assert snapshot == _snapshot()


async def test_cached_snapshot_source_rejects_partial_manifest() -> None:
    async def reader(resource_ref: str):  # type: ignore[no-untyped-def]
        return {
            "resource_id": resource_ref,
            "resource_type": "kubernetes.cluster",
            "props": {"operational_context": {"graph_digest": "a" * 64}},
        }

    with pytest.raises(ValueError, match="unexpected fields"):
        await AzureCachedOperationalSnapshotSource(reader).get(_RESOURCE)


class _Safety:
    async def evaluate(self, *, event, action, snapshot):  # type: ignore[no-untyped-def]
        return AzureReuseSafetyChecks(
            preconditions_passed=True,
            target_identity_verified=True,
            blast_radius_within_limit=True,
            policy_allowed=True,
            dry_run_passed=True,
            idempotency_available=True,
            rollback_resolved=True,
            evidence_refs=("d" * 64,),
        )


def _action() -> LearnedAction:
    return LearnedAction(
        signature="sig-1",
        rule_id="learned.operational.example",
        action_type="ops.scale-out",
        params={},
        incident_id="case-a",
        success_rate=0.99,
    )


def _context() -> OperationalCaseContext:
    return OperationalCaseContext(
        case_ref=f"case-history:case-a:1:{'e' * 64}",
        failure_fingerprint=_fingerprint().digest,
        resource_type="kubernetes.cluster",
        action_type="ops.scale-out",
        required_topology_role="hosts",
        graph_digest="a" * 64,
        owner_digest="b" * 64,
        evidence_cutoff=_NOW - timedelta(minutes=1),
    )


async def test_current_reuse_verifier_combines_snapshot_and_safety_evidence() -> None:
    verifier = AzureCurrentReuseVerifier(
        snapshots=_Snapshots(),
        safety=_Safety(),
        clock=_clock,
    )

    result = await verifier.verify(event=_event(), action=_action(), context=_context())

    assert result.failure_fingerprint == _fingerprint().digest
    assert result.resource_type == "kubernetes.cluster"
    assert result.topology_role == "hosts"
    assert result.evidence_refs == ("c" * 64, "d" * 64)
    assert result.policy_allowed is True
    assert result.dry_run_passed is True


async def test_current_reuse_accepts_recent_cache_before_event_ingestion() -> None:
    class _CachedSnapshots:
        async def get(self, resource_ref: str) -> AzureOperationalSnapshot | None:
            return replace(_snapshot(), observed_at=_NOW - timedelta(seconds=1))

    verifier = AzureCurrentReuseVerifier(
        snapshots=_CachedSnapshots(),
        safety=_Safety(),
        clock=lambda: _NOW,
    )

    result = await verifier.verify(event=_event(), action=_action(), context=_context())

    assert result.observed_at == _NOW - timedelta(seconds=1)


async def test_current_reuse_rejects_snapshot_stale_at_evaluation_time() -> None:
    class _StaleSnapshots:
        async def get(self, resource_ref: str) -> AzureOperationalSnapshot | None:
            return replace(_snapshot(), observed_at=_NOW - timedelta(minutes=6))

    verifier = AzureCurrentReuseVerifier(
        snapshots=_StaleSnapshots(),
        safety=_Safety(),
        clock=lambda: _NOW,
    )

    with pytest.raises(ValueError, match="stale or future-skewed"):
        await verifier.verify(event=_event(), action=_action(), context=_context())


def _metrics() -> StaticMetricProvider:
    points = []
    for index in range(12):
        at = _NOW - timedelta(minutes=12 - index)
        points.extend(
            (
                MetricPoint(
                    metric_name="node_cpu_percent",
                    at=at,
                    value=float(index),
                    labels={"resource_id": _RESOURCE.casefold()},
                ),
                MetricPoint(
                    metric_name="service_latency_ms",
                    at=at,
                    value=float(index * 2),
                    labels={"resource_id": _RESOURCE.casefold()},
                ),
            )
        )
    return StaticMetricProvider(points)


async def test_temporal_provider_builds_pre_cutoff_metric_evidence() -> None:
    provider = AzureTemporalCausalEvidenceProvider(
        snapshots=_HistoricalSnapshots(),
        metrics=_metrics(),
        policies={
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
    )

    evidence = await provider.collect(event=_event(), incident_id="incident-1")

    assert evidence is not None
    assert evidence.feature_cutoff == _NOW
    assert evidence.cause.metric == "node_cpu_percent"
    assert evidence.effect.metric == "service_latency_ms"
    assert evidence.graph_revision == "a" * 64
    assert all(sample.timestamp <= _NOW for sample in evidence.cause.samples)
    assert evidence.supporting_evidence_ids[0].startswith("evidence:")
    assert {item.object_type for item in evidence.endpoint_objects} == {
        "EvidenceArtifact",
        "Finding",
    }


async def test_temporal_evidence_replays_identically_after_adapter_restart() -> None:
    policy = AzureTemporalPolicy(
        cause_metric="node_cpu_percent",
        effect_metric="service_latency_ms",
        mechanism="node-pressure",
        required_topology_role="hosts",
        lookback=timedelta(minutes=20),
    )
    first_provider = AzureTemporalCausalEvidenceProvider(
        snapshots=_HistoricalSnapshots(),
        metrics=_metrics(),
        policies={"aks.node-pressure": policy},
    )
    second_provider = AzureTemporalCausalEvidenceProvider(
        snapshots=_HistoricalSnapshots(),
        metrics=_metrics(),
        policies={"aks.node-pressure": policy},
    )

    first = await first_provider.collect(event=_event(), incident_id="incident-1")
    second = await second_provider.collect(event=_event(), incident_id="incident-1")

    assert first == second


async def test_temporal_evidence_identity_binds_metric_policy_and_graph() -> None:
    base_policy = AzureTemporalPolicy(
        cause_metric="node_cpu_percent",
        effect_metric="service_latency_ms",
        mechanism="node-pressure",
        required_topology_role="hosts",
        lookback=timedelta(minutes=20),
    )
    changed_policy = AzureTemporalPolicy(
        cause_metric="node_cpu_percent",
        effect_metric="service_latency_ms",
        mechanism="network-pressure",
        required_topology_role="hosts",
        lookback=timedelta(minutes=20),
    )
    first = await AzureTemporalCausalEvidenceProvider(
        snapshots=_HistoricalSnapshots(),
        metrics=_metrics(),
        policies={"aks.node-pressure": base_policy},
    ).collect(event=_event(), incident_id="incident-1")
    changed = await AzureTemporalCausalEvidenceProvider(
        snapshots=_HistoricalSnapshots(),
        metrics=_metrics(),
        policies={"aks.node-pressure": changed_policy},
    ).collect(event=_event(), incident_id="incident-1")

    assert first is not None and changed is not None
    assert first.evidence_refs[-1] != changed.evidence_refs[-1]


async def test_temporal_provider_holds_without_configured_event_policy() -> None:
    provider = AzureTemporalCausalEvidenceProvider(
        snapshots=_HistoricalSnapshots(),
        metrics=_metrics(),
        policies={
            "other": AzureTemporalPolicy(
                cause_metric="node_cpu_percent",
                effect_metric="service_latency_ms",
                mechanism="node-pressure",
                required_topology_role="hosts",
                lookback=timedelta(minutes=20),
            )
        },
    )

    assert await provider.collect(event=_event(), incident_id="incident-1") is None


async def test_temporal_provider_holds_when_required_topology_role_changed() -> None:
    provider = AzureTemporalCausalEvidenceProvider(
        snapshots=_HistoricalSnapshots(),
        metrics=_metrics(),
        policies={
            "aks.node-pressure": AzureTemporalPolicy(
                cause_metric="node_cpu_percent",
                effect_metric="service_latency_ms",
                mechanism="node-pressure",
                required_topology_role="depends-on",
                lookback=timedelta(minutes=20),
            )
        },
    )

    assert await provider.collect(event=_event(), incident_id="incident-1") is None


async def test_temporal_provider_rejects_snapshot_after_feature_cutoff() -> None:
    provider = AzureTemporalCausalEvidenceProvider(
        snapshots=_Snapshots(),
        metrics=_metrics(),
        policies={
            "aks.node-pressure": AzureTemporalPolicy(
                cause_metric="node_cpu_percent",
                effect_metric="service_latency_ms",
                mechanism="node-pressure",
                required_topology_role="hosts",
                lookback=timedelta(minutes=20),
            )
        },
    )

    with pytest.raises(ValueError, match="feature cutoff"):
        await provider.collect(event=_event(), incident_id="incident-1")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
async def test_temporal_provider_rejects_non_finite_metric_values(value: float) -> None:
    points = tuple(
        MetricPoint(
            metric_name=metric,
            at=_NOW - timedelta(minutes=2 - index),
            value=value if metric == "node_cpu_percent" and index == 0 else float(index),
            labels={"resource_id": _RESOURCE.casefold()},
        )
        for index in range(2)
        for metric in ("node_cpu_percent", "service_latency_ms")
    )
    provider = AzureTemporalCausalEvidenceProvider(
        snapshots=_HistoricalSnapshots(),
        metrics=StaticMetricProvider(points),
        policies={
            "aks.node-pressure": AzureTemporalPolicy(
                cause_metric="node_cpu_percent",
                effect_metric="service_latency_ms",
                mechanism="node-pressure",
                required_topology_role="hosts",
                lookback=timedelta(minutes=20),
            )
        },
    )

    with pytest.raises(ValueError, match="non-finite"):
        await provider.collect(event=_event(), incident_id="incident-1")


class _Estimator:
    async def estimate(self, *, event, action, snapshot, metric):  # type: ignore[no-untyped-def]
        return (
            SimulationBranch("noop", "noop", 100.0, 5.0),
            SimulationBranch("scale", action.action_type, 80.0, 5.0),
        )


async def test_configured_dynamic_estimator_uses_observed_metric() -> None:
    from fdai.delivery.azure.operational_evidence import (
        AzureConfiguredBranchEffect,
        AzureConfiguredBranchEstimator,
    )

    estimator = AzureConfiguredBranchEstimator(
        {
            "ops.scale-out": AzureConfiguredBranchEffect(
                metric="service_latency_ms",
                delta=-20.0,
                interval_radius=5.0,
            )
        }
    )
    snapshot = replace(_snapshot(), metric_values={"service_latency_ms": 100.0})

    branches = await estimator.estimate(
        event=_event(),
        action=_action(),
        snapshot=snapshot,
        metric="service_latency_ms",
    )

    assert len(branches) == 1
    assert branches[0].raw_prediction == 80.0
    assert branches[0].raw_interval_radius == 5.0


async def test_configured_dynamic_estimator_requires_observed_metric() -> None:
    from fdai.delivery.azure.operational_evidence import (
        AzureConfiguredBranchEffect,
        AzureConfiguredBranchEstimator,
    )

    estimator = AzureConfiguredBranchEstimator(
        {
            "ops.scale-out": AzureConfiguredBranchEffect(
                metric="service_latency_ms",
                delta=-20.0,
                interval_radius=5.0,
            )
        }
    )

    with pytest.raises(ValueError, match="observed metric is unavailable"):
        await estimator.estimate(
            event=_event(),
            action=_action(),
            snapshot=_snapshot(),
            metric="service_latency_ms",
        )


async def test_dynamic_provider_builds_bounded_current_snapshot_request() -> None:
    provider = AzureDynamicSimulationRequestProvider(
        snapshots=_Snapshots(),
        estimator=_Estimator(),
        policies={
            "ops.scale-out": AzureDynamicPolicy(
                metric="service_latency_ms",
                divergence_threshold=5.0,
            )
        },
        clock=_clock,
    )

    request = await provider.build(event=_event(), action=_action())

    assert request is not None
    assert request.snapshot.snapshot_id == f"azure:{'a' * 64}"
    assert request.snapshot.metric == "service_latency_ms"
    assert tuple(branch.branch_id for branch in request.branches) == ("noop", "scale")


async def test_dynamic_provider_rejects_unbounded_estimator_output() -> None:
    class _UnboundedEstimator:
        async def estimate(self, *, event, action, snapshot, metric):  # type: ignore[no-untyped-def]
            return tuple(
                SimulationBranch(f"branch-{index}", action.action_type, 80.0, 5.0)
                for index in range(33)
            )

    provider = AzureDynamicSimulationRequestProvider(
        snapshots=_Snapshots(),
        estimator=_UnboundedEstimator(),
        policies={"ops.scale-out": AzureDynamicPolicy(metric="service_latency_ms")},
        clock=_clock,
    )

    with pytest.raises(ValueError, match="branches MUST be bounded"):
        await provider.build(event=_event(), action=_action())


async def test_dynamic_provider_rejects_wrong_or_stale_snapshot() -> None:
    class _WrongSnapshots:
        async def get(self, resource_ref: str) -> AzureOperationalSnapshot | None:
            return replace(_snapshot(), resource_ref=f"{resource_ref}/other")

    class _StaleSnapshots:
        async def get(self, resource_ref: str) -> AzureOperationalSnapshot | None:
            return replace(_snapshot(), observed_at=_NOW - timedelta(hours=1))

    for snapshots, reason in (
        (_WrongSnapshots(), "target changed"),
        (_StaleSnapshots(), "stale or future-skewed"),
    ):
        provider = AzureDynamicSimulationRequestProvider(
            snapshots=snapshots,
            estimator=_Estimator(),
            policies={"ops.scale-out": AzureDynamicPolicy(metric="service_latency_ms")},
            clock=_clock,
        )
        with pytest.raises(ValueError, match=reason):
            await provider.build(event=_event(), action=_action())


async def test_dynamic_provider_uses_evaluation_clock_not_event_time() -> None:
    provider = AzureDynamicSimulationRequestProvider(
        snapshots=_Snapshots(),
        estimator=_Estimator(),
        policies={"ops.scale-out": AzureDynamicPolicy(metric="service_latency_ms")},
        clock=lambda: _NOW + timedelta(hours=1),
    )

    with pytest.raises(ValueError, match="stale or future-skewed"):
        await provider.build(event=_event(), action=_action())


def test_temporal_policy_rejects_unbounded_lookback() -> None:
    with pytest.raises(ValueError, match="exceeds 31 days"):
        AzureTemporalPolicy(
            cause_metric="node_cpu_percent",
            effect_metric="service_latency_ms",
            mechanism="node-pressure",
            required_topology_role="hosts",
            lookback=timedelta(days=32),
        )
