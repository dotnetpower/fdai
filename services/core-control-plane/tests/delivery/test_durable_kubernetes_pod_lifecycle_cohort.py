"""Controller-grounded durable Kubernetes Pod lifecycle cohort tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.kubernetes_lifecycle_observation import (
    KubernetesLifecycleObservation,
    KubernetesPodLifecycleIdentity,
)
from fdai.delivery.durable_kubernetes_pod_lifecycle_cohort import (
    DurableKubernetesPodLifecycleCohortReader,
)
from fdai.delivery.kubernetes_lifecycle_collector import (
    KubernetesLifecycleCursorState,
    KubernetesPodLifecycleCohortSnapshot,
)

NOW = datetime(2026, 8, 28, tzinfo=UTC)


def _identity(
    pod_id: str,
    pod_uid: str,
    *,
    controller_uid: str = "replicaset-uid",
) -> KubernetesPodLifecycleIdentity:
    return KubernetesPodLifecycleIdentity(
        cluster_ref="cluster-a",
        namespace="default",
        pod_id=pod_id,
        pod_uid=pod_uid,
        controller_uid=controller_uid,
        root_controller_uid="deployment-uid",
        root_controller_kind="Deployment",
        observed_at=NOW - timedelta(minutes=10),
        source_revision="sha256:" + "a" * 64,
        evidence_ref="kubernetes-pod-lifecycle:" + pod_uid.removeprefix("pod-").ljust(64, "a"),
    )


def _event(pod_uid: str) -> KubernetesLifecycleObservation:
    return KubernetesLifecycleObservation(
        cluster_ref="cluster-a",
        namespace="default",
        object_uid=pod_uid,
        owner_uid="untrusted-related-uid",
        reason="Failed",
        category="failed",
        event_type="Warning",
        event_time=NOW - timedelta(minutes=5),
        recorded_time=NOW - timedelta(minutes=4),
        source_revision="100",
        evidence_ref="kubernetes-lifecycle:" + pod_uid.removeprefix("pod-").ljust(64, "b"),
    )


@dataclass
class _Store:
    snapshot: KubernetesPodLifecycleCohortSnapshot

    async def read_pod_lifecycle_cohort(self, **_kwargs: object):
        return self.snapshot


async def test_cohort_preserves_historical_uid_and_inventory_owner() -> None:
    old_identity = _identity("pod/orders-old", "pod-old")
    current_identity = _identity("pod/orders-new", "pod-new")
    reader = DurableKubernetesPodLifecycleCohortReader(
        store=_Store(
            KubernetesPodLifecycleCohortSnapshot(
                state=KubernetesLifecycleCursorState(
                    resource_version="100",
                    updated_at=NOW,
                    coverage_started_at=NOW - timedelta(hours=1),
                ),
                identities=(old_identity, current_identity),
                observations=(_event("pod-old"),),
            )
        ),
        cluster_ref="cluster-a",
    )

    result = await reader.read_pod_lifecycle_cohort(
        current_pod_id="pod/orders-new",
        current_pod_uid="pod-new",
        namespace="default",
        root_controller_uid="deployment-uid",
        lookback_seconds=1800,
        observed_at=NOW,
    )

    assert result["complete"] is True
    values = result["rows"][0]["values"]  # type: ignore[index]
    assert values["pod_id"] == "pod/orders-old"  # type: ignore[index]
    assert values["object_uid"] == "pod-old"  # type: ignore[index]
    assert values["owner_uid"] == "replicaset-uid"  # type: ignore[index]
    assert values["owner_uid"] != "untrusted-related-uid"  # type: ignore[index]


async def test_cohort_requires_retained_current_identity() -> None:
    reader = DurableKubernetesPodLifecycleCohortReader(
        store=_Store(
            KubernetesPodLifecycleCohortSnapshot(
                state=KubernetesLifecycleCursorState(
                    resource_version="100",
                    updated_at=NOW,
                    coverage_started_at=NOW - timedelta(hours=1),
                ),
                identities=(_identity("pod/orders-old", "pod-old"),),
                observations=(_event("pod-old"),),
            )
        ),
        cluster_ref="cluster-a",
    )

    result = await reader.read_pod_lifecycle_cohort(
        current_pod_id="pod/orders-new",
        current_pod_uid="pod-new",
        namespace="default",
        root_controller_uid="deployment-uid",
        lookback_seconds=1800,
        observed_at=NOW,
    )

    assert result["complete"] is False
    assert result["truncation_reason"] == "current_pod_identity_unavailable"


async def test_cohort_is_complete_for_same_uid_restart_without_historical_identity() -> None:
    """A same-UID restart never replaces the Pod, so no distinct historical UID exists.

    The retained cohort correctly holds only the current Pod's own identity in
    that case. That legitimate absence MUST NOT be treated as missing
    replacement evidence and MUST NOT hold the cohort incomplete.
    """

    current_identity = _identity("pod/orders-current", "pod-current")
    reader = DurableKubernetesPodLifecycleCohortReader(
        store=_Store(
            KubernetesPodLifecycleCohortSnapshot(
                state=KubernetesLifecycleCursorState(
                    resource_version="100",
                    updated_at=NOW,
                    coverage_started_at=NOW - timedelta(hours=1),
                ),
                identities=(current_identity,),
                observations=(_event("pod-current"),),
            )
        ),
        cluster_ref="cluster-a",
    )

    result = await reader.read_pod_lifecycle_cohort(
        current_pod_id="pod/orders-current",
        current_pod_uid="pod-current",
        namespace="default",
        root_controller_uid="deployment-uid",
        lookback_seconds=1800,
        observed_at=NOW,
    )

    assert result["complete"] is True
    assert result["truncation_reason"] is None
    values = result["rows"][0]["values"]  # type: ignore[index]
    assert values["object_uid"] == "pod-current"  # type: ignore[index]
