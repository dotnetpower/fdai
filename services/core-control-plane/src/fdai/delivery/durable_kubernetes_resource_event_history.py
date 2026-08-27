"""Read retained Kubernetes lifecycle observations as Resource event evidence."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.resource_event_queries import (
    KUBERNETES_EVENT_FAMILY,
    ResourceEventCollection,
    ResourceEventObservation,
)
from fdai.delivery.kubernetes_lifecycle_collector import KubernetesLifecycleStore

_MAX_EVENTS = 256


class DurableKubernetesResourceEventHistoryReader:
    """Expose durable lifecycle rows through the existing Resource event query seam.

    Durable rows are preferred only after a cursor proves that collection has started.
    A missing cursor or an empty retained result remains incomplete, so historical
    absence cannot be reported as a successful diagnosis.
    """

    def __init__(
        self,
        *,
        store: KubernetesLifecycleStore,
        cluster_ref: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not cluster_ref.strip():
            raise ValueError("durable Kubernetes event cluster_ref MUST NOT be empty")
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
        """Read retained rows for exact UID-backed Kubernetes Resources."""

        if event_families != (KUBERNETES_EVENT_FAMILY,):
            raise ValueError("durable Kubernetes reader received an unsupported event family")
        if resource_ids != tuple(sorted(set(resource_ids))) or not resource_ids:
            raise ValueError("durable Kubernetes resource_ids MUST be ordered and non-empty")
        if not 60 <= lookback_seconds <= 86_400:
            raise ValueError("durable Kubernetes lookback_seconds MUST be in [60, 86400]")
        return await self._read(
            resource_ids=resource_ids,
            resource_identity={},
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
        """Read using the immutable Pod UID from the secured query receipt."""

        if event_families != (KUBERNETES_EVENT_FAMILY,):
            raise ValueError("durable Kubernetes reader received an unsupported event family")
        return await self._read(
            resource_ids=resource_ids,
            resource_identity=resource_identity,
            lookback_seconds=lookback_seconds,
        )

    async def _read(
        self,
        *,
        resource_ids: tuple[str, ...],
        resource_identity: Mapping[str, Mapping[str, str]],
        lookback_seconds: int,
    ) -> ResourceEventCollection:
        if len(resource_ids) != 1:
            return _result(
                resource_ids,
                observed_at=self._now(),
                events=(),
                complete=False,
                limitation="target_resolution_not_exact",
            )
        identity = resource_identity.get(resource_ids[0], {})
        uid = identity.get("uid")
        cluster = identity.get("cluster_ref", self._cluster_ref)
        if not uid or cluster != self._cluster_ref:
            return _result(
                resource_ids,
                observed_at=self._now(),
                events=(),
                complete=False,
                limitation="pod_uid_unavailable",
            )
        cursor = await self._store.read_cursor(self._cluster_ref)
        observed_at = self._now()
        if cursor is None:
            return _result(
                resource_ids,
                observed_at=observed_at,
                events=(),
                complete=False,
                limitation="lifecycle_cursor_unavailable",
            )
        start = observed_at - timedelta(seconds=lookback_seconds)
        observations = await self._store.read_observations(
            cluster_ref=self._cluster_ref,
            object_uids=(uid,),
            start=start,
            end=observed_at,
            limit=_MAX_EVENTS,
        )
        events = tuple(
            ResourceEventObservation(
                resource_id=resource_ids[0],
                event_family=KUBERNETES_EVENT_FAMILY,
                event_kind=item.reason,
                status=item.event_type,
                classification=item.category,
                occurred_at=item.event_time,
                evidence_ref=item.evidence_ref,
            )
            for item in observations
        )
        return _result(
            resource_ids,
            observed_at=observed_at,
            events=events,
            complete=bool(events),
            limitation=None if events else "no_lifecycle_events_observed",
        )


def _result(
    resource_ids: tuple[str, ...],
    *,
    observed_at: datetime,
    events: tuple[ResourceEventObservation, ...],
    complete: bool,
    limitation: str | None,
) -> ResourceEventCollection:
    material = "|".join(
        (resource_ids[0] if resource_ids else "none", *(item.evidence_ref for item in events))
    )
    return ResourceEventCollection(
        resource_ids=resource_ids,
        events=events,
        observed_at=observed_at,
        complete=complete,
        limitation=limitation,
        attempt_ref=f"durable-kubernetes:{hashlib.sha256(material.encode()).hexdigest()}",
    )


__all__ = ["DurableKubernetesResourceEventHistoryReader"]
