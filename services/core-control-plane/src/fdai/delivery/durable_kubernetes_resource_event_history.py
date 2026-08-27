"""Durable Kubernetes lifecycle history adapted to Resource Event queries."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.core.ontology_platform.resource_event_queries import (
    KUBERNETES_EVENT_FAMILY,
    ResourceEventCollection,
    ResourceEventObservation,
)
from fdai.delivery.kubernetes_api_inventory import kubernetes_resource_id
from fdai.delivery.persistence.postgres_kubernetes_lifecycle import (
    PostgresKubernetesLifecycleStore,
)

_MAX_EVENTS = 256
_FRESHNESS_SECONDS = 120
_KIND_TO_TYPE = {
    "CronJob": "kubernetes.cron-job",
    "DaemonSet": "kubernetes.daemon-set",
    "Deployment": "kubernetes.deployment",
    "Job": "kubernetes.job",
    "Node": "kubernetes.node",
    "Pod": "kubernetes.pod",
    "ReplicaSet": "kubernetes.replica-set",
    "Service": "kubernetes.service",
    "StatefulSet": "kubernetes.stateful-set",
}


class DurableKubernetesResourceEventHistoryReader:
    """Read indexed retained lifecycle evidence with explicit coverage limits."""

    def __init__(
        self,
        *,
        store: PostgresKubernetesLifecycleStore,
        cluster_ref: str,
        now: Any = None,
    ) -> None:
        self._store = store
        self._cluster_ref = cluster_ref
        self._now = now or (lambda: datetime.now(UTC))

    async def read_history(
        self,
        *,
        resource_ids: tuple[str, ...],
        event_families: tuple[str, ...],
        lookback_seconds: int,
    ) -> ResourceEventCollection:
        return await self._read(
            resource_ids=resource_ids,
            resource_identity=None,
            event_families=event_families,
            lookback_seconds=lookback_seconds,
        )

    async def read_history_with_identity(
        self,
        *,
        resource_ids: tuple[str, ...],
        resource_identity: Mapping[str, Mapping[str, str]],
        event_families: tuple[str, ...],
        lookback_seconds: int,
    ) -> ResourceEventCollection:
        return await self._read(
            resource_ids=resource_ids,
            resource_identity=resource_identity,
            event_families=event_families,
            lookback_seconds=lookback_seconds,
        )

    async def _read(
        self,
        *,
        resource_ids: tuple[str, ...],
        resource_identity: Mapping[str, Mapping[str, str]] | None,
        event_families: tuple[str, ...],
        lookback_seconds: int,
    ) -> ResourceEventCollection:
        if event_families != (KUBERNETES_EVENT_FAMILY,):
            raise ValueError("Durable Kubernetes reader received an unsupported family")
        now = self._now()
        since = now - timedelta(seconds=lookback_seconds)
        object_uid = _exact_uid(
            resource_ids,
            resource_identity=resource_identity,
            cluster_ref=self._cluster_ref,
        )
        cluster_scope = resource_ids == (self._cluster_ref,)
        if not cluster_scope and object_uid is None:
            return _result(resource_ids, now, (), "source_scope_incomplete")
        cursor = await self._store.read_cursor(self._cluster_ref)
        if cursor is None:
            return _result(resource_ids, now, (), "durable_history_unavailable")
        retained = await self._store.read_observations(
            cluster_ref=self._cluster_ref,
            object_uid=object_uid,
            since=since,
            limit=_MAX_EVENTS + 1,
        )
        truncated = len(retained) > _MAX_EVENTS
        selected = retained[:_MAX_EVENTS]
        target_id = self._cluster_ref if cluster_scope else resource_ids[0]
        events = tuple(
            sorted(
                (
                    ResourceEventObservation(
                        resource_id=target_id,
                        event_family=KUBERNETES_EVENT_FAMILY,
                        event_kind=_machine_token(item.reason),
                        status=item.event_type.casefold(),
                        classification=f"kubernetes_{item.object_kind.casefold()}"[:64],
                        occurred_at=item.occurred_at,
                        evidence_ref=item.evidence_ref,
                    )
                    for item in selected
                ),
                key=lambda item: (item.occurred_at, item.evidence_ref),
            )
        )
        limitation = (
            "result_limit"
            if truncated
            else cursor.limitation
            if cursor.limitation is not None
            else "source_retention_incomplete"
            if max(cursor.coverage_started_at, cursor.retention_floor_at) > since
            else "source_retention_stale"
            if cursor.coverage_through_at < now - timedelta(seconds=_FRESHNESS_SECONDS)
            else None
        )
        return _result(resource_ids, now, events, limitation)


class MergedKubernetesResourceEventHistoryReader:
    """Merge current live rows with durable coverage under one 256-row bound."""

    def __init__(self, *, live: Any, durable: DurableKubernetesResourceEventHistoryReader) -> None:
        self._live = live
        self._durable = durable

    async def read_history(self, **kwargs: Any) -> ResourceEventCollection:
        return await self._merge(
            await self._live.read_history(**kwargs),
            await self._durable.read_history(**kwargs),
        )

    async def read_history_with_identity(self, **kwargs: Any) -> ResourceEventCollection:
        return await self._merge(
            await self._live.read_history_with_identity(**kwargs),
            await self._durable.read_history_with_identity(**kwargs),
        )

    async def _merge(
        self,
        live: ResourceEventCollection,
        durable: ResourceEventCollection,
    ) -> ResourceEventCollection:
        if live.resource_ids != durable.resource_ids:
            raise ValueError("Kubernetes event sources changed the secured scope")
        by_identity = {_event_identity(item): item for item in live.events}
        by_identity.update({_event_identity(item): item for item in durable.events})
        ordered = sorted(
            by_identity.values(), key=lambda item: (item.occurred_at, item.evidence_ref)
        )
        truncated = len(ordered) > _MAX_EVENTS
        events = tuple(ordered[-_MAX_EVENTS:])
        limitation = (
            "result_limit"
            if truncated
            else None
            if durable.complete
            else durable.limitation or live.limitation or "source_retention_incomplete"
        )
        return _result(
            live.resource_ids, max(live.observed_at, durable.observed_at), events, limitation
        )


def _exact_uid(
    resource_ids: tuple[str, ...],
    *,
    resource_identity: Mapping[str, Mapping[str, str]] | None,
    cluster_ref: str,
) -> str | None:
    if len(resource_ids) != 1 or resource_ids[0] == cluster_ref or resource_identity is None:
        return None
    identity = resource_identity.get(resource_ids[0])
    if identity is None or identity.get("cluster_ref") != cluster_ref:
        return None
    uid = identity.get("uid")
    if not isinstance(uid, str) or not uid:
        return None
    if not any(
        kubernetes_resource_id(
            cluster_ref=cluster_ref,
            resource_type=resource_type,
            uid=uid,
            namespace=namespace,
        )
        == resource_ids[0]
        for resource_type in _KIND_TO_TYPE.values()
        for namespace in (None, _namespace_from_id(resource_ids[0]))
    ):
        return None
    return uid


def _namespace_from_id(resource_id: str) -> str | None:
    parts = resource_id.rsplit("/", 2)
    if len(parts) != 3:
        return None
    return None if parts[1] == "_cluster" else parts[1]


def _event_identity(item: ResourceEventObservation) -> tuple[str, datetime, str, str, str]:
    identity_kind = (
        "failed" if item.event_kind in {"errimagepull", "imagepullbackoff"} else item.event_kind
    )
    return (
        item.resource_id,
        item.occurred_at,
        item.status,
        item.classification,
        identity_kind,
    )


def _machine_token(value: str) -> str:
    normalized = "_".join(value.casefold().replace("-", " ").split())
    return normalized[:128] or "unknown"


def _result(
    resource_ids: tuple[str, ...],
    observed_at: datetime,
    events: tuple[ResourceEventObservation, ...],
    limitation: str | None,
) -> ResourceEventCollection:
    material = "|".join(
        (*resource_ids, *(item.evidence_ref for item in events), limitation or "complete")
    )
    from fdai.core.ontology_platform.kubernetes_lifecycle import lifecycle_digest

    return ResourceEventCollection(
        resource_ids=resource_ids,
        events=events,
        observed_at=observed_at,
        complete=limitation is None,
        limitation=limitation,
        attempt_ref=f"kubernetes-durable-event:{lifecycle_digest(material).removeprefix('sha256:')}",
    )


__all__ = [
    "DurableKubernetesResourceEventHistoryReader",
    "MergedKubernetesResourceEventHistoryReader",
]
