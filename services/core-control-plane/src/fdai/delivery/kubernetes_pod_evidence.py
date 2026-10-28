"""Bounded live Pod evidence over promoted inventory, API status and retained Events.

Collectors are explicitly bound by exact cluster identity. This adapter does no
discovery, credential selection, retry, ontology writes or Kubernetes mutations.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import cast

from fdai.core.investigation.kubernetes_pod import PodLifecycleEvidence
from fdai.core.investigation.kubernetes_pod_status import (
    PodFailureEvidence,
    PodStatusEvidence,
)
from fdai.core.ontology_platform.kubernetes_pod_recovery_evidence import (
    PodRestartHistoryObservation,
)
from fdai.core.ontology_platform.kubernetes_pod_replacement_evidence import (
    DeploymentReplicaObservation,
    PodLifecycleObservation,
    PodReplacementDeploymentObservation,
    PodTerminationObservation,
    PodTerminationUnavailableReason,
)
from fdai.core.ontology_platform.resource_event_queries import KUBERNETES_EVENT_FAMILY
from fdai.delivery.durable_kubernetes_resource_event_history import (
    DurableKubernetesResourceEventHistoryReader,
)
from fdai.delivery.kubernetes_api_inventory import (
    KubernetesApiInventorySource,
    kubernetes_resource_id,
)
from fdai.delivery.kubernetes_api_status import KubernetesApiInventoryError
from fdai.delivery.kubernetes_pod_observations import (
    PodEvidenceUnavailableError,
    PodObservationGraph,
    count,
    metadata,
    observation_graph,
    owner_deployment,
    recovery,
    terminations,
    text,
    validate_identity,
)
from fdai.delivery.persistence.postgres_kubernetes_lifecycle import PostgresKubernetesLifecycleStore
from fdai.delivery.pod_tick_cache import (
    PodTickCache,
    PodTickHistoryStore,
    collect_snapshot,
    read_inventory,
)
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    ProviderRelationshipMappingCatalog,
)
from fdai.shared.providers.inventory import (
    PromotedInventoryGenerationReader,
    PromotedInventoryGenerationUnavailableError,
)


class LivePodLifecycleEvidenceSource:
    """Observe one exact inventory Pod using existing read-only production collectors.

    Construct one instance per tick. Its first inventory generation and each
    complete cluster snapshot are immutable and shared, including failed reads.
    One analyzer invocation has one total deadline. Missing bindings and failed
    reads raise a sanitized, evidence-qualified error rather than returning an
    empty healthy result. Durable-history gaps remain in the typed bundle.
    """

    def __init__(
        self,
        *,
        inventory: PromotedInventoryGenerationReader,
        collectors: Mapping[str, KubernetesApiInventorySource],
        relationship_mapping_catalog: ProviderRelationshipMappingCatalog,
        lifecycle_store: PostgresKubernetesLifecycleStore | None = None,
        lifecycle_cluster_refs: Mapping[str, str] | None = None,
        freshness_seconds: int = 300,
        max_resources: int = 20_000,
        timeout_seconds: float = 60,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if freshness_seconds < 1 or max_resources < 1 or not math.isfinite(timeout_seconds):
            raise ValueError("Pod evidence bounds MUST be positive and finite")
        if timeout_seconds <= 0 or len(collectors) > 32:
            raise ValueError("Pod evidence source bounds exceeded")
        self._inventory = inventory
        self._collectors = dict(collectors)
        self._catalog = relationship_mapping_catalog
        self._store = lifecycle_store
        self._lifecycle_cluster_refs = dict(lifecycle_cluster_refs or {})
        self._freshness = freshness_seconds
        self._max_resources = max_resources
        self._timeout = timeout_seconds
        self._now = now or (lambda: datetime.now(UTC))
        self._tick = PodTickCache(timeout_seconds=timeout_seconds)
        self._history = (
            PodTickHistoryStore(lifecycle_store, self._tick) if lifecycle_store else None
        )

    async def aclose(self) -> None:
        """Cancel bounded shared reads before the owning HTTP clients are closed."""

        await self._tick.aclose()

    async def observe(
        self, *, resource_ref: str, window_seconds: float
    ) -> PodLifecycleEvidence | None:
        return (
            await self.observe_pod(resource_ref=resource_ref, window_seconds=window_seconds)
        ).lifecycle

    async def observe_status(
        self, *, resource_ref: str, window_seconds: float
    ) -> PodStatusEvidence | None:
        return (
            await self.observe_pod(resource_ref=resource_ref, window_seconds=window_seconds)
        ).status

    async def observe_pod(self, *, resource_ref: str, window_seconds: float) -> PodFailureEvidence:
        if not math.isfinite(window_seconds) or not 0 < window_seconds <= 86_400:
            raise ValueError("Pod evidence window MUST be in (0, 86400] seconds")
        try:
            async with asyncio.timeout(self._timeout):
                return await self._observe(resource_ref=resource_ref, window_seconds=window_seconds)
        except PodEvidenceUnavailableError:
            raise
        except TimeoutError:
            raise PodEvidenceUnavailableError("pod_read_deadline_exceeded") from None
        except KubernetesApiInventoryError as exc:
            raise PodEvidenceUnavailableError(exc.reason.value) from None
        except PromotedInventoryGenerationUnavailableError:
            raise PodEvidenceUnavailableError("inventory_generation_unavailable") from None
        except Exception:  # noqa: BLE001 - prevent provider/DB payloads crossing the analyzer boundary
            raise PodEvidenceUnavailableError("pod_source_read_failed") from None

    async def _observe(self, *, resource_ref: str, window_seconds: float) -> PodFailureEvidence:
        baseline = await self._tick.read(
            ("inventory",),
            lambda: read_inventory(self._inventory, max_resources=self._max_resources),
        )
        if baseline is None or baseline.recorded_at is None:
            raise PodEvidenceUnavailableError("inventory_generation_unavailable")
        baseline_recorded_at = baseline.recorded_at
        if not baseline.complete:
            raise PodEvidenceUnavailableError("inventory_generation_incomplete", status="partial")
        selected = [item for item in baseline.resources if item.resource_id == resource_ref]
        if len(selected) != 1 or selected[0].type != "kubernetes.pod":
            raise PodEvidenceUnavailableError(
                "inventory_pod_identity_unavailable", status="partial"
            )
        old_record = selected[0]
        cluster = text(old_record.props, "cluster_ref")
        validate_identity(old_record, cluster_ref=cluster)
        collector = self._collectors.get(cluster)
        if collector is None:
            raise PodEvidenceUnavailableError("cluster_api_binding_unavailable")
        snapshot = await self._tick.read(
            ("cluster", baseline.generation, cluster), lambda: collect_snapshot(collector)
        )
        now = self._now()
        cutoff = snapshot.observed_at
        if now.tzinfo is None or cutoff > now or baseline.recorded_at > cutoff:
            raise PodEvidenceUnavailableError("pod_source_time_conflict", status="conflicting")
        if (now - cutoff).total_seconds() > self._freshness:
            raise PodEvidenceUnavailableError("pod_status_stale", status="stale")
        if len(snapshot.resources) > self._max_resources:
            raise PodEvidenceUnavailableError("pod_resource_limit", status="partial")
        for item in snapshot.resources:
            validate_identity(item, cluster_ref=cluster)
        start = cutoff - timedelta(seconds=window_seconds)
        historical = self._tick.once(
            ("historical-graph", baseline.generation),
            lambda: observation_graph(
                baseline.resources,
                generation=baseline.generation,
                recorded_at=baseline_recorded_at,
                freshness_seconds=self._freshness,
                catalog=self._catalog,
            ),
        )
        current = self._tick.once(
            ("current-graph", baseline.generation, cluster, cutoff),
            lambda: observation_graph(
                snapshot.resources,
                generation=f"pod-live:{cutoff.isoformat()}",
                recorded_at=cutoff,
                freshness_seconds=self._freshness,
                catalog=self._catalog,
            ),
        )
        old = historical.lifecycle(old_record)
        same = current.resources.get(resource_ref)
        same_pod = current.lifecycle(same) if same is not None else None
        if (
            same_pod is not None
            and same_pod.created_at is not None
            and old.created_at is not None
            and same_pod.created_at != old.created_at
        ):
            raise PodEvidenceUnavailableError(
                "pod_creation_identity_conflict", status="conflicting"
            )
        if (
            same_pod is not None
            and old.restart_count is not None
            and same_pod.restart_count is not None
            and same_pod.restart_count < old.restart_count
        ):
            raise PodEvidenceUnavailableError("pod_restart_counter_regressed", status="conflicting")
        if (
            same_pod is not None
            and same_pod.restart_count != old.restart_count
            and same_pod.metadata.effective_at <= old.metadata.effective_at
        ):
            raise PodEvidenceUnavailableError("pod_restart_time_conflict", status="conflicting")
        candidates = (
            (same_pod,)
            if same_pod is not None
            else tuple(
                current.lifecycle(item)
                for item in snapshot.resources
                if item.type == "kubernetes.pod"
                and item.props.get("namespace") == old.namespace
                and item.props.get("cluster_ref") == old.cluster_id
            )
        )
        candidates = tuple(
            pod
            for pod in candidates
            if pod.pod_uid == old.pod_uid
            or (
                old.root_controller_uid is not None
                and pod.root_controller_uid == old.root_controller_uid
                and pod.created_at is not None
                and start <= pod.created_at <= cutoff
            )
        )
        if len(candidates) > 32:
            raise PodEvidenceUnavailableError("pod_candidate_limit", status="partial")
        termination, history_gap = await self._termination(old, start=start, cutoff=cutoff)
        status = (
            PodStatusEvidence(
                resource_ref=resource_ref,
                pod_uid=old.pod_uid,
                pod=recovery(same_pod),
                terminations=terminations(
                    same,
                    start=start,
                    cutoff=cutoff,
                    refs=same_pod.evidence_refs,
                ),
                start=start,
                cutoff=cutoff,
                evidence_gaps=(f"kubernetes_lifecycle_{history_gap}",) if history_gap else (),
                rollout_observed=_rollout_observed(current, same_pod),
            )
            if same_pod is not None and same is not None
            else None
        )
        if same_pod is not None and same_pod.restart_count == old.restart_count:
            return PodFailureEvidence(lifecycle=None, status=status)
        if not candidates:
            raise PodEvidenceUnavailableError("pod_replacement_unobserved", status="partial")
        chosen = candidates[0]
        # Ambiguous cohorts remain in the reducer's candidate set. Selecting a
        # recovery carrier does not certify it as the unique replacement.
        deployment = current.deployment(chosen)
        delta = (
            chosen.restart_count - old.restart_count
            if chosen.pod_uid == old.pod_uid
            and chosen.restart_count is not None
            and old.restart_count is not None
            and chosen.restart_count >= old.restart_count
            and old.metadata.effective_at < chosen.metadata.effective_at
            and start <= old.metadata.effective_at
            and chosen.container_count == old.container_count
            else None
        )
        lifecycle = PodLifecycleEvidence(
            resource_ref=resource_ref,
            old_pod=old,
            candidates=candidates,
            termination=termination,
            termination_unavailable_reason=history_gap if termination is None else None,
            deployment=_deployment_history(historical, current, old, chosen),
            recovery_pod=recovery(chosen),
            restart_history=PodRestartHistoryObservation(
                pod_id=chosen.pod_id,
                start=max(start, old.metadata.effective_at)
                if chosen.pod_uid == old.pod_uid
                else start,
                end=cutoff,
                restart_delta=delta,
                complete=delta is not None,
                missing_reason=None if delta is not None else "pod_counter_window_unavailable",
                evidence_refs=tuple(sorted(set((*old.evidence_refs, *chosen.evidence_refs)))),
            ),
            owner_deployment=owner_deployment(deployment, fallback=chosen, graph=current),
            correlation_window_start=start,
            cutoff=cutoff,
            graph_complete=True,
            ownership_complete=bool(
                old.owner_link
                and old.root_controller_link
                and chosen.owner_link
                and chosen.root_controller_link
                and deployment is not None
            ),
        )
        return PodFailureEvidence(lifecycle=lifecycle, status=status)

    async def _termination(
        self, old: PodLifecycleObservation, *, start: datetime, cutoff: datetime
    ) -> tuple[PodTerminationObservation | None, PodTerminationUnavailableReason | None]:
        if self._history is None:
            return None, "durable_history_unavailable"
        history_cluster = self._lifecycle_cluster_refs.get(old.cluster_id, old.cluster_id)
        history_resource = kubernetes_resource_id(
            cluster_ref=history_cluster,
            resource_type="kubernetes.pod",
            uid=old.pod_uid,
            namespace=old.namespace,
        )
        reader = DurableKubernetesResourceEventHistoryReader(
            store=self._history.as_reader_store(), cluster_ref=history_cluster, now=lambda: cutoff
        )
        try:
            coverage = await reader.read_history_with_identity(
                resource_ids=(history_resource,),
                resource_identity={
                    history_resource: {"cluster_ref": history_cluster, "uid": old.pod_uid}
                },
                event_families=(KUBERNETES_EVENT_FAMILY,),
                lookback_seconds=math.ceil((cutoff - start).total_seconds()),
            )
            if not coverage.complete:
                return None, cast(PodTerminationUnavailableReason, coverage.limitation)
            rows = await self._history.read_observations(
                cluster_ref=history_cluster, object_uid=old.pod_uid, since=start, limit=257
            )
        except Exception:  # noqa: BLE001 - unavailable history cannot certify replacement
            return None, "durable_history_unavailable"
        if len(rows) > 256:
            return None, "result_limit"
        if any(
            row.cluster_ref != history_cluster
            or row.object_uid != old.pod_uid
            or row.namespace != old.namespace
            or row.object_kind != "Pod"
            for row in rows
        ):
            raise PodEvidenceUnavailableError("pod_history_scope_conflict", status="conflicting")
        stops = [
            row
            for row in rows
            if start <= row.occurred_at <= row.recorded_at <= cutoff
            and row.reason in {"Killing", "OOMKilled"}
        ]
        if not stops:
            return None, None
        latest_time = max(row.occurred_at for row in stops)
        latest = [row for row in stops if row.occurred_at == latest_time]
        if len({(row.reason, row.event_type) for row in latest}) > 1:
            raise PodEvidenceUnavailableError("pod_termination_conflict", status="conflicting")
        selected = latest[-1]
        return PodTerminationObservation(
            pod_uid=old.pod_uid,
            cluster_id=old.cluster_id,
            namespace=old.namespace,
            event_type=selected.event_type,
            reason=selected.reason,
            exit_code=None,
            signal=None,
            finished_at=None,
            event_time=selected.occurred_at,
            recorded_at=selected.recorded_at,
            source_identity="kubernetes-api-events",
            source_revision=selected.source_revision,
            evidence_refs=tuple(sorted({row.evidence_ref for row in latest})),
        ), None


def _deployment_history(
    historical: PodObservationGraph,
    current: PodObservationGraph,
    old: PodLifecycleObservation,
    chosen: PodLifecycleObservation,
) -> PodReplacementDeploymentObservation | None:
    before, after = historical.deployment(old), current.deployment(chosen)
    if after is None:
        return None
    after_fact = metadata(
        after, freshness_seconds=current.freshness_seconds, recorded_at=current.recorded_at
    )
    samples: dict[datetime, int] = {}
    for record, graph in ((before, historical), (after, current)):
        if record is not None and (desired := count(record.props, "desired_replicas")) is not None:
            fact = metadata(
                record, freshness_seconds=graph.freshness_seconds, recorded_at=graph.recorded_at
            )
            if fact.effective_at in samples and samples[fact.effective_at] != desired:
                raise PodEvidenceUnavailableError("pod_replica_conflict", status="conflicting")
            samples[fact.effective_at] = desired
    if not samples:
        return None
    history = tuple(DeploymentReplicaObservation(time, samples[time]) for time in sorted(samples))
    return PodReplacementDeploymentObservation(
        deployment_id=after.resource_id,
        deployment_uid=text(after.props, "uid"),
        cluster_id=chosen.cluster_id,
        namespace=chosen.namespace,
        desired_replicas_before=history[0].desired_replicas,
        desired_replicas_after=history[-1].desired_replicas,
        desired_replica_history=history,
        # Two inventory snapshots cannot rule out intervening scale changes.
        replica_history_complete=False,
        ready_replicas=count(after.props, "ready_replicas"),
        available_replicas=count(after.props, "available_replicas"),
        unavailable_replicas=count(after.props, "unavailable_replicas"),
        metadata=after_fact,
        evidence_refs=after_fact.evidence_refs,
    )


def _rollout_observed(graph: PodObservationGraph, pod: PodLifecycleObservation) -> bool:
    deployment = graph.deployment(pod)
    if deployment is None:
        return False
    desired = count(deployment.props, "desired_replicas")
    updated = count(deployment.props, "updated_replicas")
    return desired == 0 or (desired is not None and updated is not None and updated < desired)
