"""Read controller-grounded historical Pod lifecycle cohorts from PostgreSQL."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from fdai.delivery.kubernetes_lifecycle_collector import KubernetesLifecycleStore

_MAX_IDENTITIES = 32
_MAX_EVENTS = 256
_DEFAULT_FRESHNESS_SECONDS = 900


class DurableKubernetesPodLifecycleCohortReader:
    """Return old Pod UID events only through retained inventory controller lineage."""

    def __init__(
        self,
        *,
        store: KubernetesLifecycleStore,
        cluster_ref: str,
        freshness_ceiling_seconds: int = _DEFAULT_FRESHNESS_SECONDS,
    ) -> None:
        if not cluster_ref.strip():
            raise ValueError("durable Kubernetes Pod cohort cluster_ref MUST NOT be empty")
        if freshness_ceiling_seconds < 1:
            raise ValueError("durable Kubernetes Pod cohort freshness MUST be positive")
        self._store = store
        self._cluster_ref = cluster_ref
        self._freshness_ceiling_seconds = freshness_ceiling_seconds

    async def read_pod_lifecycle_cohort(
        self,
        *,
        current_pod_id: str,
        current_pod_uid: str,
        namespace: str,
        root_controller_uid: str,
        lookback_seconds: int,
        observed_at: datetime,
    ) -> Mapping[str, object]:
        """Read a bounded root-controller cohort without relabelling Resource events."""

        if not all(
            item.strip()
            for item in (
                current_pod_id,
                current_pod_uid,
                namespace,
                root_controller_uid,
            )
        ):
            raise ValueError("Kubernetes Pod lifecycle cohort identity MUST be non-empty")
        if not 60 <= lookback_seconds <= 86_400:
            raise ValueError("Kubernetes Pod lifecycle cohort lookback MUST be in [60, 86400]")
        if observed_at.tzinfo is None:
            raise ValueError("Kubernetes Pod lifecycle cohort cutoff MUST be timezone-aware")
        snapshot = await self._store.read_pod_lifecycle_cohort(
            cluster_ref=self._cluster_ref,
            namespace=namespace,
            root_controller_uid=root_controller_uid,
            start=observed_at - timedelta(seconds=lookback_seconds),
            end=observed_at,
            identity_limit=_MAX_IDENTITIES + 1,
            event_limit=_MAX_EVENTS + 1,
        )
        window_start = observed_at - timedelta(seconds=lookback_seconds)
        state = snapshot.state
        limitation: str | None = None
        if state is None:
            limitation = "lifecycle_cursor_unavailable"
        elif not state.complete or state.limitation is not None:
            limitation = (
                f"lifecycle_cursor_{state.limitation}"
                if state.limitation
                else "lifecycle_collection_incomplete"
            )
        else:
            age = observed_at.astimezone(UTC) - state.updated_at.astimezone(UTC)
            if age.total_seconds() < 0:
                limitation = "lifecycle_cursor_future"
            elif age.total_seconds() > self._freshness_ceiling_seconds:
                limitation = "lifecycle_cursor_stale"
            elif state.coverage_started_at is None:
                limitation = "lifecycle_coverage_unavailable"
            elif state.coverage_started_at > window_start:
                limitation = "lifecycle_lookback_not_covered"
        identities = snapshot.identities
        observations = snapshot.observations
        if limitation is None and len(identities) > _MAX_IDENTITIES:
            limitation = "identity_limit"
        if limitation is None and len(observations) > _MAX_EVENTS:
            limitation = "result_limit"
        bounded_identities = identities[:_MAX_IDENTITIES]
        identity_by_uid = {item.pod_uid: item for item in bounded_identities}
        current = identity_by_uid.get(current_pod_uid)
        if limitation is None and (
            current is None
            or current.pod_id != current_pod_id
            or current.root_controller_uid != root_controller_uid
        ):
            limitation = "current_pod_identity_unavailable"
        historical_uids = set(identity_by_uid).difference({current_pod_uid})
        if limitation is None and not historical_uids:
            limitation = "historical_pod_identity_unavailable"
        rows = []
        for observation in observations[:_MAX_EVENTS]:
            identity = identity_by_uid.get(observation.object_uid)
            if identity is None:
                continue
            rows.append(
                {
                    "row_id": observation.evidence_ref,
                    "values": {
                        "pod_id": identity.pod_id,
                        "pod_uid": identity.pod_uid,
                        "object_uid": identity.pod_uid,
                        "cluster_ref": identity.cluster_ref,
                        "namespace": identity.namespace,
                        "owner_uid": identity.controller_uid,
                        "root_controller_uid": identity.root_controller_uid,
                        "root_controller_kind": identity.root_controller_kind,
                        "identity_observed_at": identity.observed_at.isoformat(),
                        "identity_source_revision": identity.source_revision,
                        "identity_evidence_ref": identity.evidence_ref,
                        "reason": observation.reason,
                        "category": observation.category,
                        "event_type": observation.event_type,
                        "event_time": observation.event_time.isoformat(),
                        "recorded_time": observation.recorded_time.isoformat(),
                        "source_revision": observation.source_revision,
                        "evidence_ref": observation.evidence_ref,
                    },
                }
            )
        material = "|".join(
            (
                current_pod_uid,
                root_controller_uid,
                *(str(row["row_id"]) for row in rows),
            )
        )
        return {
            "complete": limitation is None,
            "truncation_reason": limitation,
            "current_pod_uid": current_pod_uid,
            "root_controller_uid": root_controller_uid,
            "window_start": window_start.isoformat(),
            "rows": rows,
            "attempt_ref": (
                "durable-kubernetes-pod-cohort:" + hashlib.sha256(material.encode()).hexdigest()
            ),
            "execution_authority": False,
        }


__all__ = ["DurableKubernetesPodLifecycleCohortReader"]
