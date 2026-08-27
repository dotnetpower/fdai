"""Durable Kubernetes Resource Event history tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.kubernetes_lifecycle import (
    KubernetesLifecycleCursor,
    KubernetesLifecycleObservation,
)
from fdai.delivery.durable_kubernetes_resource_event_history import (
    DurableKubernetesResourceEventHistoryReader,
    MergedKubernetesResourceEventHistoryReader,
)
from fdai.delivery.kubernetes_api_inventory import kubernetes_resource_id

NOW = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)
CLUSTER = "scope-example/resource-group/example/providers/containerservice/example"
UID = "pod-uid"
RESOURCE_ID = kubernetes_resource_id(
    cluster_ref=CLUSTER,
    resource_type="kubernetes.pod",
    uid=UID,
    namespace="default",
)


class _Store:
    def __init__(
        self,
        *,
        coverage_started_at: datetime,
        limitation: str | None = None,
        reason: str = "BackOff",
    ) -> None:
        self.cursor = KubernetesLifecycleCursor(
            cluster_ref=CLUSTER,
            sequence=2,
            resume_token="opaque-current",
            coverage_started_at=coverage_started_at,
            coverage_through_at=NOW,
            retention_floor_at=coverage_started_at,
            limitation=limitation,
        )
        self.object_uid: str | None = None
        self.reason = reason

    async def read_cursor(self, cluster_ref: str) -> KubernetesLifecycleCursor:
        assert cluster_ref == CLUSTER
        return self.cursor

    async def read_observations(
        self,
        *,
        cluster_ref: str,
        object_uid: str | None,
        since: datetime,
        limit: int,
    ) -> tuple[KubernetesLifecycleObservation, ...]:
        self.object_uid = object_uid
        return (
            KubernetesLifecycleObservation(
                observation_id=f"sha256:{'a' * 64}",
                cluster_ref=cluster_ref,
                event_uid="event-a",
                object_uid=UID,
                object_kind="Pod",
                namespace="default",
                owner_uid="replica-set-a",
                reason=self.reason,
                event_type="Warning",
                lifecycle_kind="backoff",
                action="modified",
                occurred_at=NOW - timedelta(minutes=5),
                recorded_at=NOW - timedelta(minutes=4),
                source_revision="opaque-10",
                occurrence_count=17,
                evidence_ref=f"kubernetes-lifecycle:{'a' * 64}",
            ),
        )


async def test_exact_uid_history_becomes_complete_only_after_window_coverage() -> None:
    store = _Store(coverage_started_at=NOW - timedelta(hours=2))
    reader = DurableKubernetesResourceEventHistoryReader(
        store=store,  # type: ignore[arg-type]
        cluster_ref=CLUSTER,
        now=lambda: NOW,
    )

    result = await reader.read_history_with_identity(
        resource_ids=(RESOURCE_ID,),
        resource_identity={RESOURCE_ID: {"cluster_ref": CLUSTER, "uid": UID}},
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert store.object_uid == UID
    assert result.complete is True
    assert result.limitation is None
    assert result.events[0].resource_id == RESOURCE_ID
    assert result.events[0].event_kind == "backoff"


async def test_recent_cursor_cannot_claim_historical_absence() -> None:
    store = _Store(coverage_started_at=NOW - timedelta(minutes=10))
    reader = DurableKubernetesResourceEventHistoryReader(
        store=store,  # type: ignore[arg-type]
        cluster_ref=CLUSTER,
        now=lambda: NOW,
    )

    result = await reader.read_history(
        resource_ids=(CLUSTER,),
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert result.complete is False
    assert result.limitation == "source_retention_incomplete"


async def test_merge_deduplicates_overlapping_live_and_durable_rows() -> None:
    durable_store = _Store(coverage_started_at=NOW - timedelta(hours=2))
    durable = DurableKubernetesResourceEventHistoryReader(
        store=durable_store,  # type: ignore[arg-type]
        cluster_ref=CLUSTER,
        now=lambda: NOW,
    )

    class _Live:
        async def read_history_with_identity(self, **kwargs):  # type: ignore[no-untyped-def]
            result = await durable.read_history_with_identity(**kwargs)
            event = result.events[0]
            return result.__class__(
                resource_ids=result.resource_ids,
                events=(replace(event, evidence_ref="live:other"),),
                observed_at=result.observed_at,
                complete=False,
                limitation="source_retention_unverified",
                attempt_ref="live:attempt",
            )

    merged = MergedKubernetesResourceEventHistoryReader(live=_Live(), durable=durable)
    result = await merged.read_history_with_identity(
        resource_ids=(RESOURCE_ID,),
        resource_identity={RESOURCE_ID: {"cluster_ref": CLUSTER, "uid": UID}},
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert len(result.events) == 1


async def test_merge_preserves_distinct_same_second_event_kinds() -> None:
    durable_store = _Store(coverage_started_at=NOW - timedelta(hours=2))
    durable = DurableKubernetesResourceEventHistoryReader(
        store=durable_store,  # type: ignore[arg-type]
        cluster_ref=CLUSTER,
        now=lambda: NOW,
    )
    base = (
        await durable.read_history_with_identity(
            resource_ids=(RESOURCE_ID,),
            resource_identity={RESOURCE_ID: {"cluster_ref": CLUSTER, "uid": UID}},
            event_families=("resource_event.kubernetes",),
            lookback_seconds=3600,
        )
    ).events[0]

    class _Live:
        async def read_history_with_identity(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return type(
                "Collection",
                (),
                {
                    "resource_ids": (RESOURCE_ID,),
                    "events": (
                        replace(base, event_kind="unhealthy", evidence_ref="live:unhealthy"),
                        replace(base, event_kind="killing", evidence_ref="live:killing"),
                    ),
                    "observed_at": NOW,
                    "complete": False,
                    "limitation": "source_retention_unverified",
                },
            )()

    result = await MergedKubernetesResourceEventHistoryReader(
        live=_Live(),
        durable=durable,
    ).read_history_with_identity(
        resource_ids=(RESOURCE_ID,),
        resource_identity={RESOURCE_ID: {"cluster_ref": CLUSTER, "uid": UID}},
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert {item.event_kind for item in result.events} == {"backoff", "killing", "unhealthy"}


async def test_merge_deduplicates_message_refined_image_pull_failure() -> None:
    durable_store = _Store(
        coverage_started_at=NOW - timedelta(hours=2),
        reason="Failed",
    )
    durable = DurableKubernetesResourceEventHistoryReader(
        store=durable_store,  # type: ignore[arg-type]
        cluster_ref=CLUSTER,
        now=lambda: NOW,
    )
    base = (
        await durable.read_history_with_identity(
            resource_ids=(RESOURCE_ID,),
            resource_identity={RESOURCE_ID: {"cluster_ref": CLUSTER, "uid": UID}},
            event_families=("resource_event.kubernetes",),
            lookback_seconds=3600,
        )
    ).events[0]

    class _Live:
        async def read_history_with_identity(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return type(
                "Collection",
                (),
                {
                    "resource_ids": (RESOURCE_ID,),
                    "events": (replace(base, event_kind="imagepullbackoff"),),
                    "observed_at": NOW,
                    "complete": False,
                    "limitation": "source_retention_unverified",
                },
            )()

    result = await MergedKubernetesResourceEventHistoryReader(
        live=_Live(),
        durable=durable,
    ).read_history_with_identity(
        resource_ids=(RESOURCE_ID,),
        resource_identity={RESOURCE_ID: {"cluster_ref": CLUSTER, "uid": UID}},
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert len(result.events) == 1
    assert result.events[0].event_kind == "imagepullbackoff"


async def test_merge_preserves_same_source_image_failure_sequence() -> None:
    durable_store = _Store(
        coverage_started_at=NOW - timedelta(hours=2),
        reason="Unrelated",
    )
    durable = DurableKubernetesResourceEventHistoryReader(
        store=durable_store,  # type: ignore[arg-type]
        cluster_ref=CLUSTER,
        now=lambda: NOW,
    )
    base = (
        await durable.read_history_with_identity(
            resource_ids=(RESOURCE_ID,),
            resource_identity={RESOURCE_ID: {"cluster_ref": CLUSTER, "uid": UID}},
            event_families=("resource_event.kubernetes",),
            lookback_seconds=3600,
        )
    ).events[0]

    class _Live:
        async def read_history_with_identity(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return type(
                "Collection",
                (),
                {
                    "resource_ids": (RESOURCE_ID,),
                    "events": tuple(
                        replace(base, event_kind=kind, evidence_ref=f"live:{kind}")
                        for kind in ("failed", "errimagepull", "imagepullbackoff")
                    ),
                    "observed_at": NOW,
                    "complete": False,
                    "limitation": "source_retention_unverified",
                },
            )()

    result = await MergedKubernetesResourceEventHistoryReader(
        live=_Live(),
        durable=durable,
    ).read_history_with_identity(
        resource_ids=(RESOURCE_ID,),
        resource_identity={RESOURCE_ID: {"cluster_ref": CLUSTER, "uid": UID}},
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert {"failed", "errimagepull", "imagepullbackoff"} <= {
        item.event_kind for item in result.events
    }
