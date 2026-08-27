"""Durable Kubernetes lifecycle evidence adapter tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.kubernetes_lifecycle_observation import (
    KUBERNETES_LIFECYCLE_KILLING,
    KubernetesLifecycleObservation,
)
from fdai.delivery.durable_kubernetes_resource_event_history import (
    DurableKubernetesResourceEventHistoryReader,
)

NOW = datetime(2026, 8, 27, 14, 0, tzinfo=UTC)


def _observation(uid: str = "pod-uid-a") -> KubernetesLifecycleObservation:
    return KubernetesLifecycleObservation(
        cluster_ref="cluster-a",
        namespace="default",
        object_uid=uid,
        owner_uid="rs-uid-a",
        reason="Killing",
        category=KUBERNETES_LIFECYCLE_KILLING,
        event_type="Warning",
        event_time=NOW - timedelta(minutes=1),
        recorded_time=NOW,
        source_revision="100",
        evidence_ref=f"kubernetes-lifecycle:{uid}",
    )


@dataclass
class _Store:
    cursor: str | None = "100"
    observations: tuple[KubernetesLifecycleObservation, ...] = (_observation(),)

    async def read_cursor(self, cluster_ref: str) -> str | None:
        assert cluster_ref == "cluster-a"
        return self.cursor

    async def read_observations(
        self,
        *,
        cluster_ref: str,
        object_uids: tuple[str, ...],
        start: datetime,
        end: datetime,
        limit: int,
    ) -> tuple[KubernetesLifecycleObservation, ...]:
        assert cluster_ref == "cluster-a"
        assert object_uids == ("pod-uid-a",)
        assert start < end and limit == 256
        return self.observations


async def test_durable_reader_maps_retained_uid_events_to_resource_events() -> None:
    reader = DurableKubernetesResourceEventHistoryReader(
        store=_Store(),
        cluster_ref="cluster-a",
        now=lambda: NOW,
    )

    result = await reader.read_history_with_identity(
        resource_ids=("cluster-a/kubernetes/pod/pod-a",),
        resource_identity={
            "cluster-a/kubernetes/pod/pod-a": {"cluster_ref": "cluster-a", "uid": "pod-uid-a"}
        },
        event_families=("resource_event.kubernetes",),
        lookback_seconds=900,
    )

    assert result.complete is True
    assert result.events[0].event_kind == "Killing"
    assert result.events[0].evidence_ref == "kubernetes-lifecycle:pod-uid-a"


async def test_missing_cursor_and_empty_rows_are_not_successful_absence() -> None:
    no_cursor = DurableKubernetesResourceEventHistoryReader(
        store=_Store(cursor=None),
        cluster_ref="cluster-a",
        now=lambda: NOW,
    )
    missing = await no_cursor.read_history_with_identity(
        resource_ids=("pod-a",),
        resource_identity={"pod-a": {"cluster_ref": "cluster-a", "uid": "pod-uid-a"}},
        event_families=("resource_event.kubernetes",),
        lookback_seconds=900,
    )
    assert missing.complete is False
    assert missing.limitation == "lifecycle_cursor_unavailable"

    empty = DurableKubernetesResourceEventHistoryReader(
        store=_Store(observations=()),
        cluster_ref="cluster-a",
        now=lambda: NOW,
    )
    result = await empty.read_history_with_identity(
        resource_ids=("pod-a",),
        resource_identity={"pod-a": {"cluster_ref": "cluster-a", "uid": "pod-uid-a"}},
        event_families=("resource_event.kubernetes",),
        lookback_seconds=900,
    )
    assert result.complete is False
    assert result.limitation == "no_lifecycle_events_observed"


async def test_reader_rejects_missing_or_foreign_uid_before_store_read() -> None:
    reader = DurableKubernetesResourceEventHistoryReader(
        store=_Store(),
        cluster_ref="cluster-a",
        now=lambda: NOW,
    )
    result = await reader.read_history_with_identity(
        resource_ids=("pod-a",),
        resource_identity={"pod-a": {"cluster_ref": "cluster-b", "uid": "pod-uid-a"}},
        event_families=("resource_event.kubernetes",),
        lookback_seconds=900,
    )
    assert result.complete is False
    assert result.limitation == "pod_uid_unavailable"
