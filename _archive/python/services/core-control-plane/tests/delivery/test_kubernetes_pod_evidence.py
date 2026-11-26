"""Focused live-seam tests; all Kubernetes and database I/O is replaced locally."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from fdai.core.investigation.kubernetes_pod_status import KubernetesPodFailureAnalyzer
from fdai.core.ontology_platform.kubernetes_lifecycle import (
    KubernetesLifecycleCoverageSegment,
    KubernetesLifecycleCursor,
    KubernetesLifecycleObservation,
)
from fdai.delivery.kubernetes_api_inventory import (
    KubernetesApiInventoryConfig,
    KubernetesApiInventorySnapshot,
    KubernetesApiInventorySource,
    kubernetes_resource_id,
)
from fdai.delivery.kubernetes_api_status import (
    KubernetesApiFailureReason,
    KubernetesApiInventoryError,
)
from fdai.delivery.kubernetes_pod_evidence import LivePodLifecycleEvidenceSource
from fdai.delivery.kubernetes_pod_observations import PodEvidenceUnavailableError
from fdai.delivery.persistence.postgres_kubernetes_lifecycle import PostgresKubernetesLifecycleStore
from fdai.delivery.pod_evidence_binding import (
    build_pod_analyzer,
    build_pod_lifecycle_evidence_source,
)
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    load_provider_relationship_mapping_catalog,
)
from fdai.shared.providers.inventory import (
    PromotedInventoryGeneration,
    PromotedInventoryGenerationReader,
    ResourceRecord,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
BEFORE = NOW - timedelta(seconds=20)
CLUSTER = "/clusters/example"
NAMESPACE = "example"
CATALOG = load_provider_relationship_mapping_catalog(
    Path(__file__).resolve().parents[4]
    / "rule-catalog"
    / "vocabulary"
    / "provider-relationship-mappings"
)


def _record(kind: str, uid: str, time: datetime, **props: Any) -> ResourceRecord:
    resource_type = {
        "Pod": "kubernetes.pod",
        "ReplicaSet": "kubernetes.replica-set",
        "Deployment": "kubernetes.deployment",
        "Namespace": "kubernetes.namespace",
    }[kind]
    namespace = None if kind == "Namespace" else NAMESPACE
    return ResourceRecord(
        resource_id=kubernetes_resource_id(
            cluster_ref=CLUSTER, resource_type=resource_type, uid=uid, namespace=namespace
        ),
        type=resource_type,
        provider_ref=f"kubernetes-uid:{uid}",
        last_seen=time.isoformat(),
        props={
            "cluster_ref": CLUSTER,
            "namespace": NAMESPACE,
            "uid": uid,
            "name": uid,
            "kind": kind,
            "resource_version": str(int(time.timestamp())),
            **props,
        },
    )


def _pod(
    time: datetime, uid: str = "pod-old", owner: str = "replica-old", **props: Any
) -> ResourceRecord:
    return _record(
        "Pod",
        uid,
        time,
        controller_uid=owner,
        owner_uids=(owner,),
        created_at=(NOW - timedelta(minutes=5)).isoformat(),
        phase="Running",
        ready=True,
        container_count=1,
        ready_container_count=1,
        restart_count=0,
        labels={"pod-template-hash": owner},
        **props,
    )


def _records(
    pod: ResourceRecord, time: datetime, *, rollout: bool = False
) -> tuple[ResourceRecord, ...]:
    records = (
        _record("Namespace", "namespace-example", time),
        _record(
            "Deployment",
            "deployment-example",
            time,
            desired_replicas=1,
            ready_replicas=1,
            available_replicas=1,
            unavailable_replicas=0,
            updated_replicas=0 if rollout else 1,
        ),
        _record(
            "ReplicaSet",
            str(pod.props["controller_uid"]),
            time,
            owner_uids=("deployment-example",),
            controller_uid="deployment-example",
        ),
        pod,
    )
    return tuple(sorted(records, key=lambda record: record.resource_id))


def _store(
    *,
    events: tuple[KubernetesLifecycleObservation, ...] = (),
    limitation: str | None = None,
    segments: tuple[KubernetesLifecycleCoverageSegment, ...] = (),
) -> Any:
    return SimpleNamespace(
        read_cursor=AsyncMock(
            return_value=KubernetesLifecycleCursor(
                cluster_ref=CLUSTER,
                sequence=1,
                resume_token=None,
                coverage_started_at=NOW - timedelta(hours=1),
                coverage_through_at=NOW,
                retention_floor_at=NOW - timedelta(hours=1),
                limitation=limitation,
            )
        ),
        read_observations=AsyncMock(return_value=events),
        read_incomplete_coverage_segments=AsyncMock(return_value=segments),
    )


def _event(reason: str = "Killing", *, uid: str = "pod-old") -> KubernetesLifecycleObservation:
    return KubernetesLifecycleObservation(
        observation_id="observation-example",
        cluster_ref=CLUSTER,
        event_uid="event-example",
        object_uid=uid,
        object_kind="Pod",
        namespace=NAMESPACE,
        owner_uid=None,
        reason=reason,
        event_type="Normal",
        lifecycle_kind="terminating",
        action="added",
        occurred_at=NOW - timedelta(seconds=10),
        recorded_at=NOW - timedelta(seconds=9),
        source_revision="event-revision",
        occurrence_count=1,
        evidence_ref="event:example",
    )


def _source(
    *,
    old: ResourceRecord | None = None,
    current: ResourceRecord | None = None,
    store: Any = None,
    rollout: bool = False,
) -> tuple[LivePodLifecycleEvidenceSource, Any, Any]:
    old = old or _pod(BEFORE)
    current = current or _pod(NOW)
    baseline = PromotedInventoryGeneration(
        generation="inventory-example",
        resources=_records(old, BEFORE),
        complete=True,
        recorded_at=BEFORE,
    )
    inventory = SimpleNamespace(load_active_generation=AsyncMock(return_value=baseline))
    collector = SimpleNamespace(
        collect=AsyncMock(
            return_value=KubernetesApiInventorySnapshot(
                resources=_records(current, NOW, rollout=rollout),
                observed_at=NOW,
            )
        )
    )
    source = LivePodLifecycleEvidenceSource(
        inventory=cast(PromotedInventoryGenerationReader, inventory),
        collectors={CLUSTER: cast(KubernetesApiInventorySource, collector)},
        relationship_mapping_catalog=CATALOG,
        lifecycle_store=cast(PostgresKubernetesLifecycleStore | None, store),
        now=lambda: NOW,
    )
    return source, inventory, collector


async def test_live_same_uid_restart_reuses_verified_ownership_and_recovery() -> None:
    current = replace(_pod(NOW), props={**_pod(NOW).props, "restart_count": 1})
    source, _, collector = _source(current=current, store=_store())
    bundle = await source.observe_pod(resource_ref=current.resource_id, window_seconds=60)
    assert bundle.lifecycle is not None
    assert bundle.lifecycle.old_pod.pod_uid == "pod-old"
    assert bundle.lifecycle.ownership_complete
    assert bundle.lifecycle.candidates[0].owner_link.verified  # type: ignore[union-attr]
    assert bundle.lifecycle.restart_history.restart_delta == 1
    assert bundle.lifecycle.restart_history.start == BEFORE
    findings = await KubernetesPodFailureAnalyzer(source).analyze(
        resource_ref=current.resource_id, window_seconds=60
    )
    assert [finding.signal for finding in findings] == ["container_restart"]
    assert findings[0].assessment is not None
    assert findings[0].assessment.recovery_closed is True
    collector.collect.assert_awaited_once()  # one immutable cluster read per source/tick


async def test_healthy_pod_does_not_create_a_finding_or_recovery() -> None:
    source, _, collector = _source()
    findings = await KubernetesPodFailureAnalyzer(source).analyze(
        resource_ref=_pod(NOW).resource_id, window_seconds=60
    )
    assert findings == ()
    collector.collect.assert_awaited_once()


async def test_crash_loop_uses_current_exact_uid_status() -> None:
    current = _pod(NOW)
    current = replace(
        current,
        props={**current.props, "ready": False, "container_waiting_reasons": ("CrashLoopBackOff",)},
    )
    source, _, _ = _source(current=current)
    findings = await KubernetesPodFailureAnalyzer(source).analyze(
        resource_ref=current.resource_id, window_seconds=60
    )
    assert [finding.signal for finding in findings] == ["pod_crash_loop_back_off"]
    assert findings[0].resource_ref == current.resource_id
    assert findings[0].assessment is not None
    assert (
        "kubernetes_lifecycle_durable_history_unavailable" in findings[0].assessment.evidence_gaps
    )


@pytest.mark.parametrize(
    ("reason", "code", "signals"),
    [
        ("OOMKilled", 137, {"pod_oom_killed"}),
        ("Error", 137, {"pod_abnormal_termination"}),
        ("Completed", 0, set()),
        ("OOMKilled", 0, {"conflicting_evidence"}),
    ],
)
async def test_termination_uses_reason_not_exit_137(
    reason: str, code: int, signals: set[str]
) -> None:
    current = _pod(NOW)
    current = replace(
        current,
        props={
            **current.props,
            "container_terminations": (
                {
                    "container_name": "example",
                    "reason": reason,
                    "exit_code": code,
                    "observation_kind": "previous",
                    "finished_at": (NOW - timedelta(seconds=5)).isoformat(),
                },
            ),
        },
    )
    source, _, _ = _source(current=current, store=_store())
    findings = await KubernetesPodFailureAnalyzer(source).analyze(
        resource_ref=current.resource_id, window_seconds=60
    )
    assert {finding.signal for finding in findings} == signals


@pytest.mark.parametrize(
    ("phase", "signal"), [("Failed", "pod_failed"), ("Running", "pod_unready")]
)
async def test_failed_phase_and_unready_are_grounded_status(phase: str, signal: str) -> None:
    current = _pod(NOW)
    current = replace(current, props={**current.props, "phase": phase, "ready": False})
    source, _, _ = _source(current=current, store=_store())
    findings = await KubernetesPodFailureAnalyzer(source).analyze(
        resource_ref=current.resource_id, window_seconds=60
    )
    assert [finding.signal for finding in findings] == [signal]


async def test_rollout_unreadiness_is_not_an_unexplained_failure() -> None:
    current = _pod(NOW)
    current = replace(current, props={**current.props, "ready": False})
    source, _, _ = _source(current=current, rollout=True, store=_store())
    assert (
        await KubernetesPodFailureAnalyzer(source).analyze(
            resource_ref=current.resource_id, window_seconds=60
        )
        == ()
    )


async def test_rollout_replacement_is_not_a_failure() -> None:
    current = _pod(NOW, uid="pod-new", owner="replica-new")
    current = replace(
        current, props={**current.props, "created_at": (NOW - timedelta(seconds=5)).isoformat()}
    )
    source, _, _ = _source(current=current, store=_store(events=(_event(),)))
    findings = await KubernetesPodFailureAnalyzer(source).analyze(
        resource_ref=_pod(BEFORE).resource_id, window_seconds=60
    )
    assert findings == ()


async def test_replacement_does_not_fabricate_continuous_replica_history() -> None:
    current = _pod(NOW, uid="pod-new")
    current = replace(
        current, props={**current.props, "created_at": (NOW - timedelta(seconds=5)).isoformat()}
    )
    source, _, _ = _source(current=current, store=_store(events=(_event("OOMKilled"),)))
    evidence = await source.observe(resource_ref=_pod(BEFORE).resource_id, window_seconds=60)
    assert evidence is not None and evidence.deployment is not None
    assert evidence.deployment.replica_history_complete is False
    findings = await KubernetesPodFailureAnalyzer(source).analyze(
        resource_ref=_pod(BEFORE).resource_id, window_seconds=60
    )
    assert [finding.signal for finding in findings] == ["insufficient_evidence"]
    assert findings[0].assessment is not None and not findings[0].assessment.recovery_closed


@pytest.mark.parametrize("limitation", ["cursor_expired", "source_retention_stale", "result_limit"])
async def test_durable_history_gaps_survive_the_live_bundle(limitation: str) -> None:
    current = _pod(NOW, uid="pod-new")
    current = replace(
        current, props={**current.props, "created_at": (NOW - timedelta(seconds=5)).isoformat()}
    )
    source, _, _ = _source(current=current, store=_store(limitation=limitation))
    evidence = await source.observe(resource_ref=_pod(BEFORE).resource_id, window_seconds=60)
    assert evidence is not None
    assert evidence.termination is None
    assert evidence.termination_unavailable_reason == limitation


async def test_recovered_cursor_cannot_erase_an_earlier_coverage_gap() -> None:
    segment = KubernetesLifecycleCoverageSegment(
        cluster_ref=CLUSTER,
        started_at=NOW - timedelta(seconds=40),
        ended_at=NOW - timedelta(seconds=30),
        limitation="cursor_expired",
    )
    current = _pod(NOW, uid="pod-new")
    current = replace(
        current, props={**current.props, "created_at": (NOW - timedelta(seconds=5)).isoformat()}
    )
    source, _, _ = _source(current=current, store=_store(segments=(segment,)))
    evidence = await source.observe(resource_ref=_pod(BEFORE).resource_id, window_seconds=60)
    assert evidence is not None and evidence.termination_unavailable_reason == "cursor_expired"


async def test_foreign_history_cannot_support_a_pod_conclusion() -> None:
    source, _, _ = _source(store=_store(events=(_event(uid="foreign-pod"),)))
    with pytest.raises(PodEvidenceUnavailableError, match="pod_history_scope_conflict") as raised:
        await source.observe(resource_ref=_pod(BEFORE).resource_id, window_seconds=60)
    assert raised.value.status == "conflicting"


async def test_production_history_arm_scope_is_bridged_without_changing_finding_identity() -> None:
    arm_cluster = (
        "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example"
        "/providers/Microsoft.ContainerService/managedClusters/aks-example"
    )
    store = _store(events=(replace(_event(), cluster_ref=arm_cluster),))
    store.read_cursor.return_value = replace(
        store.read_cursor.return_value, cluster_ref=arm_cluster
    )
    current = _pod(NOW, uid="pod-new")
    current = replace(
        current, props={**current.props, "created_at": (NOW - timedelta(seconds=5)).isoformat()}
    )
    source, _, _ = _source(current=current, store=store)
    source._lifecycle_cluster_refs = {CLUSTER: arm_cluster}
    evidence = await source.observe(resource_ref=_pod(BEFORE).resource_id, window_seconds=60)
    assert evidence is not None and evidence.termination is not None
    assert evidence.resource_ref == _pod(BEFORE).resource_id
    assert evidence.termination.cluster_id == CLUSTER
    assert evidence.termination.evidence_refs == ("event:example",)
    store.read_cursor.assert_awaited_once_with(arm_cluster)
    assert all(
        call.kwargs["cluster_ref"] == arm_cluster
        for call in store.read_observations.await_args_list
    )


async def test_unavailable_inventory_never_dispatches_a_provider_read() -> None:
    source, inventory, collector = _source()
    inventory.load_active_generation.return_value = None
    with pytest.raises(PodEvidenceUnavailableError, match="inventory_generation_unavailable"):
        await source.observe(resource_ref=_pod(BEFORE).resource_id, window_seconds=60)
    collector.collect.assert_not_awaited()


async def test_partial_inventory_never_dispatches_a_provider_read() -> None:
    source, inventory, collector = _source()
    inventory.load_active_generation.return_value = replace(
        inventory.load_active_generation.return_value, complete=False
    )
    with pytest.raises(PodEvidenceUnavailableError) as raised:
        await source.observe(resource_ref=_pod(BEFORE).resource_id, window_seconds=60)
    assert raised.value.status == "partial"
    collector.collect.assert_not_awaited()


async def test_inventory_identity_mismatch_never_dispatches_a_provider_read() -> None:
    old = replace(_pod(BEFORE), provider_ref="kubernetes-uid:foreign")
    source, _, collector = _source(old=old)
    with pytest.raises(PodEvidenceUnavailableError, match="pod_identity_conflict"):
        await source.observe(resource_ref=old.resource_id, window_seconds=60)
    collector.collect.assert_not_awaited()


async def test_api_authorization_failure_is_sanitized_and_not_empty_success() -> None:
    source, _, collector = _source()
    collector.collect.side_effect = KubernetesApiInventoryError(
        "private endpoint and provider-controlled payload",
        reason=KubernetesApiFailureReason.AUTHORIZATION_FAILED,
    )
    with pytest.raises(PodEvidenceUnavailableError) as raised:
        await source.observe(resource_ref=_pod(BEFORE).resource_id, window_seconds=60)
    assert raised.value.reason == "kubernetes_authorization_failed"
    assert "private endpoint" not in str(raised.value)
    assert raised.value.__cause__ is None
    collector.collect.assert_awaited_once()


async def test_stale_status_is_explicit() -> None:
    source, _, collector = _source()
    snapshot = collector.collect.return_value
    collector.collect.return_value = replace(snapshot, observed_at=NOW - timedelta(hours=1))
    with pytest.raises(PodEvidenceUnavailableError) as raised:
        await source.observe(resource_ref=_pod(BEFORE).resource_id, window_seconds=60)
    # The source also has a later retained baseline: temporal conflict wins over
    # a stale older live snapshot rather than downgrading that conflict.
    assert raised.value.status == "conflicting"


async def test_old_current_snapshot_is_stale_not_healthy() -> None:
    source, _, _ = _source()
    source._now = lambda: NOW + timedelta(hours=1)
    with pytest.raises(PodEvidenceUnavailableError) as raised:
        await source.observe(resource_ref=_pod(BEFORE).resource_id, window_seconds=60)
    assert raised.value.status == "stale"


async def test_unbound_cluster_does_not_dispatch_an_api_read() -> None:
    source, _, collector = _source()
    source._collectors.clear()
    with pytest.raises(PodEvidenceUnavailableError, match="cluster_api_binding_unavailable"):
        await source.observe(resource_ref=_pod(BEFORE).resource_id, window_seconds=60)
    collector.collect.assert_not_awaited()


async def test_counter_regression_is_not_a_new_restart_or_recovery() -> None:
    old = _pod(BEFORE)
    old = replace(old, props={**old.props, "restart_count": 2})
    current = _pod(NOW)
    current = replace(current, props={**current.props, "restart_count": 1})
    source, _, _ = _source(old=old, current=current)
    with pytest.raises(
        PodEvidenceUnavailableError, match="pod_restart_counter_regressed"
    ) as raised:
        await source.observe(resource_ref=old.resource_id, window_seconds=60)
    assert raised.value.status == "conflicting"


async def test_same_uid_cannot_change_its_creation_identity() -> None:
    current = _pod(NOW)
    current = replace(
        current,
        props={**current.props, "created_at": (NOW - timedelta(minutes=3)).isoformat()},
    )
    source, _, _ = _source(current=current)
    with pytest.raises(PodEvidenceUnavailableError, match="pod_creation_identity_conflict"):
        await source.observe(resource_ref=current.resource_id, window_seconds=60)


async def test_read_deadline_cancels_without_retry() -> None:
    source, _, collector = _source()

    async def blocked() -> None:
        await asyncio.Event().wait()

    source._timeout = 0.01
    collector.collect.side_effect = blocked
    with pytest.raises(PodEvidenceUnavailableError, match="pod_read_deadline_exceeded"):
        await source.observe(resource_ref=_pod(BEFORE).resource_id, window_seconds=60)
    collector.collect.assert_awaited_once()


async def test_ambiguous_replacements_remain_explicitly_partial() -> None:
    current = _pod(NOW, uid="pod-new-a")
    current = replace(
        current, props={**current.props, "created_at": (NOW - timedelta(seconds=5)).isoformat()}
    )
    second = replace(
        _pod(NOW, uid="pod-new-b"),
        props={**current.props, "uid": "pod-new-b", "name": "pod-new-b"},
    )
    source, _, collector = _source(current=current, store=_store())
    snapshot = collector.collect.return_value
    collector.collect.return_value = replace(
        snapshot,
        resources=tuple(sorted((*snapshot.resources, second), key=lambda row: row.resource_id)),
    )
    findings = await KubernetesPodFailureAnalyzer(source).analyze(
        resource_ref=_pod(BEFORE).resource_id, window_seconds=60
    )
    assert [finding.signal for finding in findings] == ["insufficient_evidence"]
    assert findings[0].assessment is not None
    assert "ambiguous_replacement_candidates" in findings[0].assessment.evidence_gaps


async def test_cross_cluster_collector_response_is_rejected() -> None:
    source, _, collector = _source()
    snapshot = collector.collect.return_value
    rows = tuple(
        replace(row, props={**row.props, "cluster_ref": "/clusters/foreign"})
        for row in snapshot.resources
    )
    collector.collect.return_value = replace(snapshot, resources=rows)
    with pytest.raises(PodEvidenceUnavailableError, match="pod_identity_conflict"):
        await source.observe(resource_ref=_pod(BEFORE).resource_id, window_seconds=60)


async def test_no_current_pod_or_replacement_is_partial_not_healthy() -> None:
    source, _, collector = _source()
    snapshot = collector.collect.return_value
    collector.collect.return_value = replace(
        snapshot, resources=tuple(row for row in snapshot.resources if row.type != "kubernetes.pod")
    )
    with pytest.raises(PodEvidenceUnavailableError) as raised:
        await source.observe(resource_ref=_pod(BEFORE).resource_id, window_seconds=60)
    assert raised.value.status == "partial"


def test_existing_binding_uses_injected_live_source_without_changing_json_decoder() -> None:
    source, _, _ = _source()
    assert build_pod_lifecycle_evidence_source({}, live_source=source) is source
    assert build_pod_lifecycle_evidence_source({}) is None
    assert build_pod_analyzer({}) is None
    assert isinstance(build_pod_analyzer({}, live_source=source), KubernetesPodFailureAnalyzer)


async def test_live_adapter_consumes_real_collector_normalization_without_network() -> None:
    pod = _pod(NOW)
    uid = str(pod.props["uid"])

    def respond(request: httpx.Request) -> httpx.Response:
        items = []
        if request.url.path == "/api/v1/pods":
            items = [
                {
                    "metadata": {
                        "uid": uid,
                        "name": "example",
                        "namespace": NAMESPACE,
                        "resourceVersion": "current",
                        "creationTimestamp": (NOW - timedelta(minutes=5)).isoformat(),
                    },
                    "status": {
                        "phase": "Running",
                        "conditions": [{"type": "Ready", "status": "False"}],
                        "containerStatuses": [
                            {
                                "name": "example",
                                "ready": False,
                                "restartCount": 0,
                                "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                            }
                        ],
                    },
                }
            ]
        return httpx.Response(200, json={"items": items, "metadata": {}})

    source, _, _ = _source()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        source._collectors[CLUSTER] = KubernetesApiInventorySource(
            config=KubernetesApiInventoryConfig(
                api_server="https://kubernetes.example.com", cluster_ref=CLUSTER
            ),
            auth=SimpleNamespace(headers=AsyncMock(return_value={})),
            http_client=http,
        )
        source._now = lambda: datetime.now(UTC)
        findings = await KubernetesPodFailureAnalyzer(source).analyze(
            resource_ref=pod.resource_id, window_seconds=60
        )
    assert [finding.signal for finding in findings] == ["pod_crash_loop_back_off"]


async def test_concurrent_pods_share_snapshot_history_and_keep_target_identity() -> None:
    store = _store()
    source, inventory, collector = _source(store=store)
    old_second = _pod(BEFORE, uid="pod-second")
    current_second = _pod(NOW, uid="pod-second")
    current_second = replace(
        current_second, props={**current_second.props, "phase": "Failed", "ready": False}
    )
    generation = inventory.load_active_generation.return_value
    inventory.load_active_generation.return_value = replace(
        generation,
        resources=tuple(
            sorted((*generation.resources, old_second), key=lambda row: row.resource_id)
        ),
    )
    snapshot = collector.collect.return_value
    snapshot = replace(
        snapshot,
        resources=tuple(
            sorted((*snapshot.resources, current_second), key=lambda row: row.resource_id)
        ),
    )
    started, release = asyncio.Event(), asyncio.Event()

    async def collect() -> KubernetesApiInventorySnapshot:
        started.set()
        await release.wait()
        return snapshot

    collector.collect.side_effect = collect
    analyzer = KubernetesPodFailureAnalyzer(source)
    first = asyncio.create_task(
        analyzer.analyze(resource_ref=_pod(NOW).resource_id, window_seconds=60)
    )
    second = asyncio.create_task(
        analyzer.analyze(resource_ref=current_second.resource_id, window_seconds=60)
    )
    await started.wait()
    await asyncio.sleep(0)
    collector.collect.assert_awaited_once()
    release.set()
    healthy, fault = await asyncio.gather(first, second)
    assert healthy == ()
    assert [finding.signal for finding in fault] == ["pod_failed"]
    assert fault[0].resource_ref == current_second.resource_id
    inventory.load_active_generation.assert_awaited_once()
    collector.collect.assert_awaited_once()
    store.read_cursor.assert_awaited_once()
    store.read_incomplete_coverage_segments.assert_awaited_once()
    assert store.read_observations.await_count == 2
    assert {call.kwargs["object_uid"] for call in store.read_observations.await_args_list} == {
        "pod-old",
        "pod-second",
    }
    # Later consumers of the same tick do not recollect or observe a mutable
    # change made to the original collector's returned dictionaries.
    current_second.props["phase"] = "Running"
    again = await analyzer.analyze(resource_ref=current_second.resource_id, window_seconds=60)
    assert [finding.signal for finding in again] == ["pod_failed"]
    collector.collect.assert_awaited_once()
    await source.aclose()


async def test_concurrent_429_is_retained_as_explicit_failure_without_retry() -> None:
    source, inventory, collector = _source()
    collector.collect.side_effect = KubernetesApiInventoryError(
        "Kubernetes inventory returned HTTP 429",
        reason=KubernetesApiFailureReason.API_UNAVAILABLE,
    )
    outcomes = await asyncio.gather(
        source.observe_pod(resource_ref=_pod(NOW).resource_id, window_seconds=60),
        source.observe_pod(resource_ref=_pod(NOW).resource_id, window_seconds=60),
        return_exceptions=True,
    )
    assert all(isinstance(item, PodEvidenceUnavailableError) for item in outcomes)
    assert all(item.reason == "kubernetes_api_unavailable" for item in outcomes)
    with pytest.raises(PodEvidenceUnavailableError, match="kubernetes_api_unavailable"):
        await source.observe_pod(resource_ref=_pod(NOW).resource_id, window_seconds=60)
    collector.collect.assert_awaited_once()
    inventory.load_active_generation.assert_awaited_once()
    await source.aclose()
