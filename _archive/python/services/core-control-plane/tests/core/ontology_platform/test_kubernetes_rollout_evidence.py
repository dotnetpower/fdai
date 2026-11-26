"""Deterministic Kubernetes rollout evidence assessment tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.kubernetes_rollout_evidence import (
    DeploymentRolloutObservation,
    KubernetesRolloutStatus,
    PodRolloutObservation,
    evaluate_kubernetes_rollout,
)
from fdai.core.ontology_platform.kubernetes_rollout_queries import (
    KUBERNETES_ROLLOUT_FUNCTION_NAME,
    evaluate_kubernetes_rollout_graph,
    kubernetes_rollout_function_type,
)
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
)
from fdai.core.ontology_platform.query_gateway import (
    ObjectSetRedactionSummary,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryResult,
    _projected_result_digest,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    STATE_FACT_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

_CUTOFF = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
_DEPLOYMENT_ID = "cluster:example/kubernetes/deployment/example"


def _metadata(
    evidence_ref: str,
    *,
    completeness: float = 1.0,
    conflicts: tuple[str, ...] = (),
) -> StateFactMetadata:
    return StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="kubernetes-api-inventory",
        source_revision="generation-1",
        effective_at=_CUTOFF,
        recorded_at=_CUTOFF,
        evidence_cutoff=_CUTOFF,
        freshness_ceiling_seconds=300,
        completeness=completeness,
        synthetic=False,
        conflicts=conflicts,
        evidence_refs=(evidence_ref,),
    )


def _deployment(**updates: object) -> DeploymentRolloutObservation:
    values: dict[str, object] = {
        "deployment_id": _DEPLOYMENT_ID,
        "desired_replicas": 3,
        "updated_replicas": 1,
        "ready_replicas": 0,
        "available_replicas": 0,
        "unavailable_replicas": 3,
        "progressing_status": "False",
        "progressing_reason": "ProgressDeadlineExceeded",
        "metadata": _metadata("kubernetes:deployment:example"),
    }
    values.update(updates)
    return DeploymentRolloutObservation(**values)  # type: ignore[arg-type]


def _pod(**updates: object) -> PodRolloutObservation:
    values: dict[str, object] = {
        "pod_id": "cluster:example/kubernetes/pod/example-1",
        "deployment_id": _DEPLOYMENT_ID,
        "phase": "Pending",
        "ready": False,
        "container_count": 1,
        "ready_container_count": 0,
        "restart_count": 0,
        "waiting_reasons": ("ImagePullBackOff",),
        "metadata": _metadata("kubernetes:pod:example-1"),
    }
    values.update(updates)
    return PodRolloutObservation(**values)  # type: ignore[arg-type]


def test_complete_blocking_evidence_reports_stall_without_claiming_cause() -> None:
    result = evaluate_kubernetes_rollout(
        deployment=_deployment(),
        pods=(_pod(),),
        cutoff=_CUTOFF,
        graph_complete=True,
    )

    assert result.status is KubernetesRolloutStatus.STALLED
    assert result.complete is True
    assert result.stall_signals == (
        "deployment_progress_deadline_exceeded",
        "pod_waiting:ImagePullBackOff",
    )
    assert result.evidence_gaps == ()
    assert result.cause_claim_supported is False
    assert result.execution_authority is False


def test_consistent_ready_replicas_report_healthy_rollout_evidence() -> None:
    result = evaluate_kubernetes_rollout(
        deployment=_deployment(
            desired_replicas=1,
            updated_replicas=1,
            ready_replicas=1,
            available_replicas=1,
            unavailable_replicas=0,
            progressing_status="True",
            progressing_reason="NewReplicaSetAvailable",
        ),
        pods=(
            _pod(
                phase="Running",
                ready=True,
                ready_container_count=1,
                waiting_reasons=(),
            ),
        ),
        cutoff=_CUTOFF,
        graph_complete=True,
    )

    assert result.status is KubernetesRolloutStatus.HEALTHY
    assert result.complete is True
    assert result.stall_signals == ()
    assert result.evidence_gaps == ()
    assert result.cause_claim_supported is False


def test_stale_pod_evidence_keeps_rollout_insufficient() -> None:
    stale = replace(
        _metadata("kubernetes:pod:example-1"),
        effective_at=_CUTOFF - timedelta(minutes=10),
        evidence_cutoff=_CUTOFF - timedelta(minutes=10),
    )

    result = evaluate_kubernetes_rollout(
        deployment=_deployment(),
        pods=(_pod(metadata=stale),),
        cutoff=_CUTOFF,
        graph_complete=True,
    )

    assert result.status is KubernetesRolloutStatus.INSUFFICIENT_EVIDENCE
    assert result.complete is False
    assert "pod_state_evidence_stale" in result.evidence_gaps
    assert result.cause_claim_supported is False


def test_conflicting_replica_counts_fail_closed() -> None:
    result = evaluate_kubernetes_rollout(
        deployment=_deployment(ready_replicas=4),
        pods=(_pod(),),
        cutoff=_CUTOFF,
        graph_complete=True,
    )

    assert result.status is KubernetesRolloutStatus.CONFLICTING_EVIDENCE
    assert result.complete is False
    assert "ready_replicas_exceed_desired" in result.evidence_gaps
    assert result.cause_claim_supported is False


def test_cross_deployment_pod_is_rejected_before_assessment() -> None:
    with pytest.raises(ValueError, match="does not belong to the requested deployment"):
        evaluate_kubernetes_rollout(
            deployment=_deployment(),
            pods=(_pod(deployment_id="cluster:example/kubernetes/deployment/other"),),
            cutoff=_CUTOFF,
            graph_complete=True,
        )


def _resource(resource_id: str, resource_type: str, **properties: object) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=resource_id,
        object_type="Resource",
        properties={
            "id": resource_id,
            "type": resource_type,
            "properties": {
                **properties,
                STATE_FACT_METADATA_PROPERTY: _metadata(f"state:{resource_id}").to_mapping(),
            },
        },
    )


def _ownership(child_id: str, owner_id: str) -> OntologyLinkRecord:
    return OntologyLinkRecord(
        link_type="kubernetes_owned_by",
        from_id=child_id,
        to_id=owner_id,
        properties={
            LINK_OBSERVATION_METADATA_PROPERTY: LinkObservationMetadata(
                state_fact=_metadata(f"ownership:{child_id}:{owner_id}"),
                verification_method="deterministic-cross-check",
                verified=True,
                verifier_identity="inventory-relationship-verifier",
                verifier_revision="verifier-1",
                verification_receipt_ref=f"verification:{child_id}:{owner_id}",
            ).to_mapping()
        },
    )


def _secured_rollout_graph(
    *,
    extra_objects: tuple[OntologyObjectRecord, ...] = (),
) -> SecuredObjectSetQueryResult:
    replica_set_id = "cluster:example/kubernetes/replica-set/example"
    pod_id = "cluster:example/kubernetes/pod/example-1"
    objects = (
        _resource(
            _DEPLOYMENT_ID,
            "kubernetes.deployment",
            desired_replicas=3,
            updated_replicas=1,
            ready_replicas=0,
            available_replicas=0,
            unavailable_replicas=3,
            progressing_status="False",
            progressing_reason="ProgressDeadlineExceeded",
        ),
        _resource(replica_set_id, "kubernetes.replica-set"),
        _resource(
            pod_id,
            "kubernetes.pod",
            phase="Pending",
            ready=False,
            container_count=1,
            ready_container_count=0,
            restart_count=0,
            container_waiting_reasons=("ImagePullBackOff",),
        ),
        *extra_objects,
    )
    links = (
        _ownership(replica_set_id, _DEPLOYMENT_ID),
        _ownership(pod_id, replica_set_id),
    )
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=_CUTOFF,
        purpose="operations-review",
        limit=16,
    )
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(objects=objects, links=links, truncated=False),
        concrete_types=("Resource",),
        truncated=False,
    )
    receipt = SecuredObjectSetQueryReceipt(
        ontology_release=build_ontology_release().ref(),
        projected_result_digest=_projected_result_digest(materialization),
        purpose="operations-review",
        caller_role="reader",
        observation_cutoff=_CUTOFF,
        as_of_skew_seconds=0,
        returned_object_count=len(objects),
        returned_link_count=len(links),
        complete=True,
        truncated=False,
        redactions=ObjectSetRedactionSummary(
            objects_with_redactions=0,
            redacted_identity_count=0,
            access_scope_count=0,
            purpose_binding_count=0,
            undeclared_property_count=0,
            links_with_redactions=0,
            redacted_link_property_count=0,
            removed_link_count=0,
        ),
    )
    return SecuredObjectSetQueryResult(materialization=materialization, receipt=receipt)


def test_exact_issued_graph_shape_reports_rollout_stall_without_cause() -> None:
    result = evaluate_kubernetes_rollout_graph(
        _secured_rollout_graph(),
        deployment_id=_DEPLOYMENT_ID,
        cutoff=_CUTOFF,
    )

    assert result.status is KubernetesRolloutStatus.STALLED
    assert result.complete is True
    assert result.pod_count == 1
    assert result.cause_claim_supported is False
    assert result.execution_authority is False
    assert any(ref.startswith("verification:") for ref in result.evidence_refs)


def test_rollout_graph_rejects_pod_outside_exact_ownership_path() -> None:
    outside_pod = _resource(
        "cluster:example/kubernetes/pod/outside",
        "kubernetes.pod",
        phase="Running",
        ready=True,
    )

    with pytest.raises(ValueError, match="outside the target ownership path"):
        evaluate_kubernetes_rollout_graph(
            _secured_rollout_graph(extra_objects=(outside_pod,)),
            deployment_id=_DEPLOYMENT_ID,
            cutoff=_CUTOFF,
        )


def test_rollout_function_type_is_read_only_and_source_derived() -> None:
    declaration = kubernetes_rollout_function_type()

    assert declaration.name == KUBERNETES_ROLLOUT_FUNCTION_NAME
    assert declaration.network_allowed is False
    assert declaration.credentials_allowed is False
    assert declaration.purpose_bindings == ["operations-review"]
