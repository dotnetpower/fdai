"""Durable Kubernetes lifecycle evidence adapter tests."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.kubernetes_lifecycle_observation import (
    KUBERNETES_LIFECYCLE_KILLING,
    KubernetesLifecycleObservation,
)
from fdai.delivery.durable_kubernetes_resource_event_history import (
    DurableKubernetesResourceEventHistoryReader,
)
from fdai.delivery.kubernetes_lifecycle_collector import (
    KubernetesLifecycleCursorState,
    KubernetesLifecycleReadSnapshot,
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
    complete: bool = True
    limitation: str | None = None

    async def read_cursor(self, cluster_ref: str) -> str | None:
        assert cluster_ref == "cluster-a"
        return self.cursor

    async def read_cursor_state(self, cluster_ref: str) -> KubernetesLifecycleCursorState | None:
        assert cluster_ref == "cluster-a"
        return (
            None
            if self.cursor is None
            else KubernetesLifecycleCursorState(
                resource_version=self.cursor,
                updated_at=NOW,
                complete=self.complete,
                limitation=self.limitation,
            )
        )

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
        assert start < end and limit == 257
        return self.observations

    async def read_snapshot(
        self,
        *,
        cluster_ref: str,
        object_uids: tuple[str, ...],
        start: datetime,
        end: datetime,
        limit: int,
        namespace: str | None = None,
        owner_uid: str | None = None,
    ) -> KubernetesLifecycleReadSnapshot:
        assert cluster_ref == "cluster-a"
        assert object_uids == ("pod-uid-a",)
        assert start < end and limit == 257
        if namespace is not None:
            assert namespace == "default"
            assert owner_uid == "rs-uid-a"
        return KubernetesLifecycleReadSnapshot(
            state=await self.read_cursor_state(cluster_ref),
            observations=self.observations,
        )


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


async def test_durable_reader_never_relabels_sibling_uid_events() -> None:
    reader = DurableKubernetesResourceEventHistoryReader(
        store=_Store(
            observations=(
                _observation("pod-uid-a"),
                _observation("pod-uid-sibling"),
            )
        ),
        cluster_ref="cluster-a",
        now=lambda: NOW,
    )

    result = await reader.read_history_with_identity(
        resource_ids=("pod-a",),
        resource_identity={
            "pod-a": {
                "cluster_ref": "cluster-a",
                "uid": "pod-uid-a",
                "namespace": "default",
                "owner_uid": "rs-uid-a",
            }
        },
        event_families=("resource_event.kubernetes",),
        lookback_seconds=900,
    )

    assert tuple(item.object_uid for item in result.events) == ("pod-uid-a",)


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


async def test_stale_cursor_and_capped_rows_remain_incomplete() -> None:
    stale = DurableKubernetesResourceEventHistoryReader(
        store=_Store(),
        cluster_ref="cluster-a",
        now=lambda: NOW + timedelta(minutes=16),
        freshness_ceiling_seconds=900,
    )
    stale_result = await stale.read_history_with_identity(
        resource_ids=("pod-a",),
        resource_identity={"pod-a": {"cluster_ref": "cluster-a", "uid": "pod-uid-a"}},
        event_families=("resource_event.kubernetes",),
        lookback_seconds=900,
    )
    assert stale_result.complete is False
    assert stale_result.limitation == "lifecycle_cursor_stale"

    capped_store = _Store(
        observations=tuple(
            replace(
                _observation("pod-uid-a"),
                evidence_ref=f"kubernetes-lifecycle:{i:064x}",
            )
            for i in range(257)
        )
    )
    capped = DurableKubernetesResourceEventHistoryReader(
        store=capped_store,
        cluster_ref="cluster-a",
        now=lambda: NOW,
    )
    capped_result = await capped.read_history_with_identity(
        resource_ids=("pod-a",),
        resource_identity={"pod-a": {"cluster_ref": "cluster-a", "uid": "pod-uid-a"}},
        event_families=("resource_event.kubernetes",),
        lookback_seconds=900,
    )
    assert capped_result.complete is False
    assert capped_result.limitation == "result_limit"
    assert len(capped_result.events) == 256

    gap_state = DurableKubernetesResourceEventHistoryReader(
        store=_Store(complete=False, limitation="lifecycle_response_invalid"),
        cluster_ref="cluster-a",
        now=lambda: NOW,
    )
    gap_result = await gap_state.read_history_with_identity(
        resource_ids=("pod-a",),
        resource_identity={"pod-a": {"cluster_ref": "cluster-a", "uid": "pod-uid-a"}},
        event_families=("resource_event.kubernetes",),
        lookback_seconds=900,
    )
    assert gap_result.complete is False
    assert gap_result.limitation == "lifecycle_cursor_lifecycle_response_invalid"


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
