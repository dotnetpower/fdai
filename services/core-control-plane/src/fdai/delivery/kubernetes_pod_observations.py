"""Adapt canonical inventory records to typed Pod reducer observations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Literal

from fdai.core.ontology_platform.kubernetes_pod_diagnosis_evidence import (
    ContainerTerminationEvidence,
)
from fdai.core.ontology_platform.kubernetes_pod_recovery_evidence import (
    PodOwnerDeploymentObservation,
    PodRecoveryObservation,
)
from fdai.core.ontology_platform.kubernetes_pod_replacement_evidence import (
    PodLifecycleObservation,
)
from fdai.delivery.inventory_relationship_verifier import verify_inventory_relationships
from fdai.delivery.kubernetes_api_inventory import kubernetes_resource_id
from fdai.delivery.kubernetes_relationships import project_kubernetes_relationships
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    ProviderRelationshipMappingCatalog,
)
from fdai.shared.providers.inventory import LinkRecord, ResourceRecord
from fdai.shared.providers.state_evidence import (
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
    state_fact_metadata_values,
)


class PodEvidenceUnavailableError(RuntimeError):
    """Sanitized evidence disposition; never a healthy/empty provider fallback."""

    def __init__(
        self,
        reason: str,
        *,
        status: Literal["unavailable", "partial", "stale", "conflicting"] = "unavailable",
    ) -> None:
        self.status = status
        self.reason = reason
        super().__init__(f"Kubernetes Pod evidence {status}: {reason}")


def text(props: Mapping[str, Any], key: str) -> str:
    value = props.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise PodEvidenceUnavailableError("pod_identity_incomplete", status="partial")
    return value


def count(props: Mapping[str, Any], key: str) -> int | None:
    value = props.get(key)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise PodEvidenceUnavailableError("pod_status_invalid", status="conflicting")
    return value


def timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise PodEvidenceUnavailableError("pod_observation_time_unavailable", status="partial")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PodEvidenceUnavailableError(
            "pod_observation_time_invalid", status="conflicting"
        ) from None
    if result.tzinfo is None:
        raise PodEvidenceUnavailableError("pod_observation_time_invalid", status="conflicting")
    return result


def validate_identity(record: ResourceRecord, *, cluster_ref: str) -> None:
    props = record.props
    uid = text(props, "uid")
    namespace = (
        None
        if record.type
        in {
            "kubernetes.namespace",
            "kubernetes.node",
            "kubernetes.persistent-volume",
            "kubernetes.storage-class",
        }
        else text(props, "namespace")
    )
    if (
        props.get("cluster_ref") != cluster_ref
        or record.provider_ref != f"kubernetes-uid:{uid}"
        or record.resource_id
        != kubernetes_resource_id(
            cluster_ref=cluster_ref, resource_type=record.type, uid=uid, namespace=namespace
        )
    ):
        raise PodEvidenceUnavailableError("pod_identity_conflict", status="conflicting")


def metadata(
    record: ResourceRecord, *, freshness_seconds: int, recorded_at: datetime
) -> StateFactMetadata:
    retained = record.props.get("state_fact_metadata")
    if retained is not None and not isinstance(retained, Mapping):
        raise PodEvidenceUnavailableError("pod_state_metadata_invalid", status="conflicting")
    if isinstance(retained, Mapping):
        try:
            facts = state_fact_metadata_values(retained)
        except ValueError:
            raise PodEvidenceUnavailableError(
                "pod_state_metadata_invalid", status="conflicting"
            ) from None
        # A property-keyed record may have independent source/time/conflict
        # facets. It cannot be collapsed into one all-properties healthy fact.
        if len(set(facts)) != 1:
            raise PodEvidenceUnavailableError("pod_state_facets_differ", status="partial")
        return facts[0]
    effective_at = timestamp(record.last_seen)
    if effective_at > recorded_at:
        raise PodEvidenceUnavailableError("pod_observation_after_cutoff", status="conflicting")
    revision = text(record.props, "resource_version")
    digest = hashlib.sha256(
        json.dumps(
            [record.resource_id, revision, effective_at.isoformat()],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="kubernetes-api-inventory",
        source_revision=revision,
        effective_at=effective_at,
        recorded_at=recorded_at,
        evidence_cutoff=effective_at,
        freshness_ceiling_seconds=freshness_seconds,
        completeness=1.0,
        synthetic=False,
        evidence_refs=(f"pod-inventory:sha256:{digest}",),
    )


@dataclass(frozen=True)
class PodObservationGraph:
    """Exact source records and the existing independently verified ownership links."""

    resources: Mapping[str, ResourceRecord]
    links: tuple[LinkRecord, ...]
    recorded_at: datetime
    freshness_seconds: int

    def lifecycle(self, record: ResourceRecord) -> PodLifecycleObservation:
        props = record.props
        owner, owner_link = self.owner(record)
        root, root_link = self.owner(owner) if owner is not None else (None, None)
        if owner is not None and owner.type in {
            "kubernetes.deployment",
            "kubernetes.stateful-set",
            "kubernetes.daemon-set",
        }:
            root, root_link = owner, owner_link
        fact = metadata(
            record, freshness_seconds=self.freshness_seconds, recorded_at=self.recorded_at
        )
        created_at = timestamp(props["created_at"]) if props.get("created_at") else None
        if created_at is not None and created_at > fact.effective_at:
            raise PodEvidenceUnavailableError("pod_creation_time_conflict", status="conflicting")
        labels = props.get("labels", {})
        revision = (
            labels.get("pod-template-hash") or labels.get("controller-revision-hash")
            if isinstance(labels, Mapping)
            else None
        )
        if revision is not None and not isinstance(revision, str):
            raise PodEvidenceUnavailableError("pod_revision_invalid", status="conflicting")
        return PodLifecycleObservation(
            pod_id=record.resource_id,
            pod_uid=text(props, "uid"),
            cluster_id=text(props, "cluster_ref"),
            namespace=text(props, "namespace"),
            owner_uid=text(owner.props, "uid") if owner is not None else None,
            root_controller_uid=text(root.props, "uid") if root is not None else None,
            root_controller_kind=text(root.props, "kind") if root is not None else None,
            owner_link=owner_link.observation_metadata if owner_link is not None else None,
            root_controller_link=root_link.observation_metadata if root_link is not None else None,
            created_at=created_at,
            phase=props.get("phase"),
            ready=_ready(props),
            container_count=count(props, "container_count"),
            ready_container_count=count(props, "ready_container_count"),
            restart_count=count(props, "restart_count"),
            waiting_reasons=waiting_reasons(props),
            workload_revision=revision,
            metadata=fact,
            evidence_refs=fact.evidence_refs,
        )

    def owner(self, record: ResourceRecord) -> tuple[ResourceRecord | None, LinkRecord | None]:
        uid = record.props.get("controller_uid")
        matches = [
            link
            for link in self.links
            if link.link_type == "kubernetes_owned_by"
            and link.from_id == record.resource_id
            and self.resources[link.to_id].props.get("uid") == uid
        ]
        if len(matches) > 1:
            raise PodEvidenceUnavailableError("pod_owner_ambiguous", status="conflicting")
        if not matches:
            return None, None
        link = matches[0]
        return self.resources[link.to_id], link

    def deployment(self, pod: PodLifecycleObservation) -> ResourceRecord | None:
        matches = [
            item
            for item in self.resources.values()
            if item.type == "kubernetes.deployment"
            and item.props.get("cluster_ref") == pod.cluster_id
            and item.props.get("namespace") == pod.namespace
            and item.props.get("uid") == pod.root_controller_uid
        ]
        if len(matches) > 1:
            raise PodEvidenceUnavailableError("pod_deployment_ambiguous", status="conflicting")
        return matches[0] if matches else None


def observation_graph(
    resources: Sequence[ResourceRecord],
    *,
    generation: str,
    recorded_at: datetime,
    freshness_seconds: int,
    catalog: ProviderRelationshipMappingCatalog,
) -> PodObservationGraph:
    projected = project_kubernetes_relationships(resources, catalog=catalog, complete=True)
    verified = verify_inventory_relationships(
        generation=generation,
        resources=resources,
        links=projected.links,
        complete=True,
        recorded_at=recorded_at,
        mapping_catalog=catalog,
        upstream_drops=projected.dropped,
    )
    return PodObservationGraph(
        MappingProxyType({record.resource_id: record for record in resources}),
        verified.links,
        recorded_at,
        freshness_seconds,
    )


def recovery(pod: PodLifecycleObservation) -> PodRecoveryObservation:
    return PodRecoveryObservation(
        pod_id=pod.pod_id,
        phase=pod.phase,
        ready=pod.ready,
        container_count=pod.container_count,
        ready_container_count=pod.ready_container_count,
        restart_count=pod.restart_count,
        waiting_reasons=pod.waiting_reasons,
        metadata=pod.metadata,
    )


def owner_deployment(
    record: ResourceRecord | None, *, fallback: PodLifecycleObservation, graph: PodObservationGraph
) -> PodOwnerDeploymentObservation:
    return PodOwnerDeploymentObservation(
        deployment_id=record.resource_id if record is not None else fallback.pod_id,
        desired_replicas=count(record.props, "desired_replicas") if record else None,
        ready_replicas=count(record.props, "ready_replicas") if record else None,
        available_replicas=count(record.props, "available_replicas") if record else None,
        unavailable_replicas=count(record.props, "unavailable_replicas") if record else None,
        metadata=(
            metadata(
                record, freshness_seconds=graph.freshness_seconds, recorded_at=graph.recorded_at
            )
            if record is not None
            else fallback.metadata
        ),
    )


def terminations(
    record: ResourceRecord, *, start: datetime, cutoff: datetime, refs: tuple[str, ...]
) -> tuple[ContainerTerminationEvidence, ...]:
    result: list[ContainerTerminationEvidence] = []
    for key in ("container_terminations", "init_container_terminations"):
        raw = record.props.get(key, ())
        if not isinstance(raw, (tuple, list)) or len(raw) > 256:
            raise PodEvidenceUnavailableError("pod_termination_invalid", status="conflicting")
        for item in raw:
            if not isinstance(item, Mapping):
                raise PodEvidenceUnavailableError("pod_termination_invalid", status="conflicting")
            finished_at = timestamp(item["finished_at"]) if item.get("finished_at") else None
            if finished_at is None or not start <= finished_at <= cutoff:
                continue
            exit_code = count(item, "exit_code")
            if exit_code is None:
                raise PodEvidenceUnavailableError(
                    "pod_termination_exit_unavailable", status="partial"
                )
            result.append(
                ContainerTerminationEvidence(
                    pod_uid=text(record.props, "uid"),
                    container_name=text(item, "container_name"),
                    reason=item.get("reason"),
                    exit_code=exit_code,
                    signal=count(item, "signal"),
                    finished_at=finished_at,
                    lifecycle_reasons=(),
                    evidence_refs=refs,
                )
            )
    return tuple(result)


def waiting_reasons(props: Mapping[str, Any]) -> tuple[str, ...]:
    reasons: set[str] = set()
    for key in ("container_waiting_reasons", "init_container_waiting_reasons"):
        raw = props.get(key, ())
        if (
            not isinstance(raw, (tuple, list))
            or len(raw) > 32
            or any(not isinstance(item, str) or not item for item in raw)
        ):
            raise PodEvidenceUnavailableError("pod_waiting_status_invalid", status="conflicting")
        reasons.update(raw)
    if len(reasons) > 32:
        raise PodEvidenceUnavailableError("pod_waiting_status_limit", status="partial")
    return tuple(sorted(reasons))


def _ready(props: Mapping[str, Any]) -> bool | None:
    value = props.get("ready")
    if value is not None and not isinstance(value, bool):
        raise PodEvidenceUnavailableError("pod_ready_status_invalid", status="conflicting")
    return value
