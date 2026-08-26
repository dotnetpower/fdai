"""Issued exact-release Kubernetes rollout evidence query."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
    OntologyReleaseRef,
)
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    STATE_FACT_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactMetadata,
)

from .functions import ContextualOntologyFunction, FunctionInvocationContext
from .kubernetes_rollout_evidence import (
    DeploymentRolloutObservation,
    KubernetesRolloutEvidenceResult,
    KubernetesRolloutStatus,
    PodRolloutObservation,
    evaluate_kubernetes_rollout,
)
from .network_path import NetworkQueryReceiptVerifier
from .query_gateway import SecuredObjectSetQueryResult

KUBERNETES_ROLLOUT_FUNCTION_NAME = "query.kubernetes_rollout_evidence"
KUBERNETES_ROLLOUT_PURPOSE = "operations-review"
KUBERNETES_ROLLOUT_SYMPTOM_CONCEPT = "deployment.rollout.stall"


def _source_artifact_digest() -> str:
    source = Path(__file__).read_bytes()
    reducer = Path(__file__).with_name("kubernetes_rollout_evidence.py").read_bytes()
    return f"sha256:{hashlib.sha256(source + b'\0' + reducer).hexdigest()}"


def kubernetes_rollout_function_type() -> OntologyFunctionType:
    """Return the read-only deterministic Kubernetes rollout declaration."""

    return OntologyFunctionType(
        name=KUBERNETES_ROLLOUT_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=_source_artifact_digest(),
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "deployment_query_result",
                "controller_query_result",
                "pod_query_result",
            ],
            "properties": {
                "deployment_query_result": {"type": "object", "x-fdai-dependency-only": True},
                "controller_query_result": {"type": "object", "x-fdai-dependency-only": True},
                "pod_query_result": {"type": "object", "x-fdai-dependency-only": True},
                "cutoff": {"type": "string", "format": "date-time"},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "deployment_id",
                "status",
                "complete",
                "pod_count",
                "ready_pod_count",
                "restart_count",
                "waiting_reasons",
                "stall_signals",
                "evidence_gaps",
                "evidence_refs",
                "cause_claim_supported",
                "execution_authority",
            ],
            "properties": {
                "deployment_id": {"type": "string"},
                "status": {
                    "enum": [
                        "healthy",
                        "stalled",
                        "insufficient_evidence",
                        "conflicting_evidence",
                    ]
                },
                "complete": {"type": "boolean"},
                "desired_replicas": {"type": ["integer", "null"], "minimum": 0},
                "updated_replicas": {"type": ["integer", "null"], "minimum": 0},
                "ready_replicas": {"type": ["integer", "null"], "minimum": 0},
                "available_replicas": {"type": ["integer", "null"], "minimum": 0},
                "unavailable_replicas": {"type": ["integer", "null"], "minimum": 0},
                "pod_count": {"type": "integer", "minimum": 0},
                "ready_pod_count": {"type": "integer", "minimum": 0},
                "restart_count": {"type": "integer", "minimum": 0},
                "waiting_reasons": {"type": "array", "maxItems": 32},
                "stall_signals": {"type": "array", "maxItems": 64},
                "evidence_gaps": {"type": "array", "maxItems": 128},
                "evidence_refs": {"type": "array", "maxItems": 256},
                "cause_claim_supported": {"const": False},
                "execution_authority": {"const": False},
            },
        },
        read_sets=["Resource", "kubernetes_owned_by"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=[KUBERNETES_ROLLOUT_PURPOSE],
        timeout_seconds=5,
        cpu_millis=1000,
        memory_bytes=134_217_728,
        max_output_bytes=131_072,
        network_allowed=False,
        credentials_allowed=False,
    )


def kubernetes_rollout_function(
    ontology_release: OntologyRelease,
    *,
    receipt_verifier: NetworkQueryReceiptVerifier,
    verification_context: object,
) -> ContextualOntologyFunction:
    """Bind rollout assessment to one composition-issued secured graph receipt."""

    if verification_context is None:
        raise ValueError("Kubernetes rollout receipt verification context MUST be non-null")
    expected_release = ontology_release.ref()

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        deployment_result = SecuredObjectSetQueryResult.model_validate(
            arguments["deployment_query_result"]
        )
        controller_result = SecuredObjectSetQueryResult.model_validate(
            arguments["controller_query_result"]
        )
        pod_result = SecuredObjectSetQueryResult.model_validate(arguments["pod_query_result"])
        query_results = (deployment_result, controller_result, pod_result)
        expected_evidence_refs = tuple(
            sorted(result.receipt.projected_result_digest for result in query_results)
        )
        cutoff = (
            datetime.fromisoformat(str(arguments["cutoff"]).replace("Z", "+00:00"))
            if "cutoff" in arguments
            else deployment_result.receipt.observation_cutoff
        )
        if cutoff.tzinfo is None or any(
            cutoff != result.receipt.observation_cutoff for result in query_results
        ):
            raise ValueError("Kubernetes rollout cutoff MUST equal the secured query cutoff")
        for result in query_results:
            _authenticate_query_receipt(
                result,
                invocation_context=invocation_context,
                expected_release=expected_release,
                expected_evidence_refs=expected_evidence_refs,
                receipt_verifier=receipt_verifier,
                verification_context=verification_context,
            )
        return evaluate_kubernetes_rollout_chain(
            deployment_result=deployment_result,
            controller_result=controller_result,
            pod_result=pod_result,
            cutoff=cutoff,
        )

    return evaluate


def evaluate_kubernetes_rollout_chain(
    *,
    deployment_result: SecuredObjectSetQueryResult,
    controller_result: SecuredObjectSetQueryResult,
    pod_result: SecuredObjectSetQueryResult,
    cutoff: datetime,
) -> KubernetesRolloutEvidenceResult:
    """Assess an explicitly issued Deployment, controller, and Pod ownership chain."""

    deployment_objects = deployment_result.materialization.graph.objects
    if len(deployment_objects) != 1:
        raise ValueError("secured rollout target query MUST return one Deployment")
    deployment = deployment_objects[0]
    if _resource_type(deployment) != "kubernetes.deployment":
        raise ValueError("secured rollout target is not a Kubernetes Deployment")
    deployment_id = deployment.id

    controller_graph = controller_result.materialization.graph
    if controller_result.materialization.definition.root_ids != (deployment_id,):
        raise ValueError("secured rollout controller query has the wrong root")
    replica_set_ids = {
        record.id
        for record in controller_graph.objects
        if _resource_type(record) == "kubernetes.replica-set"
    }
    controller_links = tuple(
        link
        for link in controller_graph.links
        if link.link_type == "kubernetes_owned_by"
        and link.from_id in replica_set_ids
        and link.to_id == deployment_id
    )
    if not replica_set_ids or len(controller_links) != len(replica_set_ids):
        raise ValueError("secured rollout controller ownership path is incomplete")

    pod_graph = pod_result.materialization.graph
    if set(pod_result.materialization.definition.root_ids) != replica_set_ids:
        raise ValueError("secured rollout Pod query has the wrong controller roots")
    pod_objects = {record.id: record for record in pod_graph.objects}
    graph_pod_ids = {
        record.id for record in pod_graph.objects if _resource_type(record) == "kubernetes.pod"
    }
    pod_links = tuple(
        link
        for link in pod_graph.links
        if link.link_type == "kubernetes_owned_by"
        and link.from_id in graph_pod_ids
        and link.to_id in replica_set_ids
    )
    if len(pod_links) != len(graph_pod_ids):
        raise ValueError("secured rollout graph contains a Pod outside the target ownership path")

    ownership_gaps, ownership_refs = _ownership_evidence(
        (*controller_links, *pod_links),
        cutoff=cutoff,
    )
    query_results = (deployment_result, controller_result, pod_result)
    graph_complete = (
        all(
            result.receipt.complete and not result.materialization.graph.truncated
            for result in query_results
        )
        and not ownership_gaps
    )
    result = evaluate_kubernetes_rollout(
        deployment=_deployment_observation(deployment),
        pods=tuple(
            _pod_observation(pod_objects[pod_id], deployment_id=deployment_id)
            for pod_id in sorted(graph_pod_ids)
        ),
        cutoff=cutoff,
        graph_complete=graph_complete,
    )
    evidence_refs = tuple(sorted(set((*result.evidence_refs, *ownership_refs))))
    if not ownership_gaps:
        return result.model_copy(update={"evidence_refs": evidence_refs})
    return result.model_copy(
        update={
            "status": KubernetesRolloutStatus.INSUFFICIENT_EVIDENCE,
            "complete": False,
            "evidence_gaps": tuple(dict.fromkeys((*result.evidence_gaps, *ownership_gaps))),
            "evidence_refs": evidence_refs,
        }
    )


def evaluate_kubernetes_rollout_graph(
    secured: SecuredObjectSetQueryResult,
    *,
    deployment_id: str,
    cutoff: datetime,
) -> KubernetesRolloutEvidenceResult:
    """Assess one exact Deployment ownership graph without provider I/O."""

    if not deployment_id.strip():
        raise ValueError("deployment_id MUST be non-empty")
    if cutoff.tzinfo is None:
        raise ValueError("Kubernetes rollout cutoff MUST be timezone-aware")
    if secured.receipt.purpose != KUBERNETES_ROLLOUT_PURPOSE:
        raise ValueError("secured rollout graph has the wrong purpose")

    graph = secured.materialization.graph
    objects = {record.id: record for record in graph.objects}
    if len(objects) != len(graph.objects):
        raise ValueError("secured rollout graph object ids MUST be unique")
    deployment = objects.get(deployment_id)
    if deployment is None or _resource_type(deployment) != "kubernetes.deployment":
        raise ValueError("secured rollout graph does not contain the exact Deployment target")
    other_deployments = tuple(
        record.id
        for record in graph.objects
        if record.id != deployment_id and _resource_type(record) == "kubernetes.deployment"
    )
    if other_deployments:
        raise ValueError("secured rollout graph contains another Deployment target")

    ownership_links = tuple(link for link in graph.links if link.link_type == "kubernetes_owned_by")
    replica_set_ids = {
        link.from_id
        for link in ownership_links
        if link.to_id == deployment_id
        and _resource_type(objects.get(link.from_id)) == "kubernetes.replica-set"
    }
    pod_links = tuple(
        link
        for link in ownership_links
        if link.to_id in replica_set_ids
        and _resource_type(objects.get(link.from_id)) == "kubernetes.pod"
    )
    selected_pod_ids = {link.from_id for link in pod_links}
    graph_pod_ids = {
        record.id for record in graph.objects if _resource_type(record) == "kubernetes.pod"
    }
    if graph_pod_ids != selected_pod_ids:
        raise ValueError("secured rollout graph contains a Pod outside the target ownership path")

    relevant_links = tuple(
        link
        for link in ownership_links
        if (link.to_id == deployment_id and link.from_id in replica_set_ids)
        or (link.to_id in replica_set_ids and link.from_id in selected_pod_ids)
    )
    ownership_gaps, ownership_refs = _ownership_evidence(relevant_links, cutoff=cutoff)
    result = evaluate_kubernetes_rollout(
        deployment=_deployment_observation(deployment),
        pods=tuple(
            _pod_observation(objects[pod_id], deployment_id=deployment_id)
            for pod_id in sorted(selected_pod_ids)
        ),
        cutoff=cutoff,
        graph_complete=(
            secured.receipt.complete
            and not graph.truncated
            and not ownership_gaps
            and bool(replica_set_ids)
        ),
    )
    if not ownership_gaps:
        return result.model_copy(
            update={"evidence_refs": tuple(sorted(set((*result.evidence_refs, *ownership_refs))))}
        )
    return result.model_copy(
        update={
            "status": KubernetesRolloutStatus.INSUFFICIENT_EVIDENCE,
            "complete": False,
            "evidence_gaps": tuple(dict.fromkeys((*result.evidence_gaps, *ownership_gaps))),
            "evidence_refs": tuple(sorted(set((*result.evidence_refs, *ownership_refs)))),
        }
    )


def _deployment_observation(record: OntologyObjectRecord) -> DeploymentRolloutObservation:
    properties = _resource_properties(record)
    return DeploymentRolloutObservation(
        deployment_id=record.id,
        desired_replicas=_optional_int(properties, "desired_replicas"),
        updated_replicas=_optional_int(properties, "updated_replicas"),
        ready_replicas=_optional_int(properties, "ready_replicas"),
        available_replicas=_optional_int(properties, "available_replicas"),
        unavailable_replicas=_optional_int(properties, "unavailable_replicas"),
        progressing_status=_optional_text(properties, "progressing_status"),
        progressing_reason=_optional_text(properties, "progressing_reason"),
        metadata=_state_metadata(record),
    )


def _pod_observation(
    record: OntologyObjectRecord,
    *,
    deployment_id: str,
) -> PodRolloutObservation:
    properties = _resource_properties(record)
    ready = properties.get("ready")
    if ready is not None and not isinstance(ready, bool):
        raise ValueError("Pod ready evidence MUST be boolean or null")
    reasons = properties.get("container_waiting_reasons", ())
    if not isinstance(reasons, Sequence) or isinstance(reasons, (str, bytes)):
        raise ValueError("Pod waiting reasons MUST be a sequence")
    return PodRolloutObservation(
        pod_id=record.id,
        deployment_id=deployment_id,
        phase=_optional_text(properties, "phase"),
        ready=ready,
        container_count=_optional_int(properties, "container_count"),
        ready_container_count=_optional_int(properties, "ready_container_count"),
        restart_count=_optional_int(properties, "restart_count"),
        waiting_reasons=tuple(str(reason) for reason in reasons),
        metadata=_state_metadata(record),
    )


def _ownership_evidence(
    links: tuple[OntologyLinkRecord, ...],
    *,
    cutoff: datetime,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    gaps: list[str] = []
    references: set[str] = set()
    if not links:
        return ("rollout_ownership_path_missing",), ()
    for link in links:
        raw = link.properties.get(LINK_OBSERVATION_METADATA_PROPERTY)
        if not isinstance(raw, Mapping):
            gaps.append("rollout_ownership_evidence_missing")
            continue
        metadata = LinkObservationMetadata.from_mapping(raw)
        references.update(metadata.state_fact.evidence_refs)
        if metadata.verification_receipt_ref is not None:
            references.add(metadata.verification_receipt_ref)
        if not metadata.verified:
            gaps.append("rollout_ownership_evidence_unverified")
        gaps.extend(
            f"rollout_ownership_{reason}"
            for reason in _state_fact_gaps(metadata.state_fact, cutoff=cutoff)
        )
    return tuple(dict.fromkeys(gaps)), tuple(sorted(references))


def _state_fact_gaps(metadata: StateFactMetadata, *, cutoff: datetime) -> tuple[str, ...]:
    normalized_cutoff = cutoff.astimezone(UTC)
    evidence_cutoff = metadata.evidence_cutoff.astimezone(UTC)
    gaps: list[str] = []
    if evidence_cutoff > normalized_cutoff:
        gaps.append("evidence_after_cutoff")
    elif (normalized_cutoff - evidence_cutoff).total_seconds() > metadata.freshness_ceiling_seconds:
        gaps.append("evidence_stale")
    if metadata.completeness < 1.0:
        gaps.append("evidence_incomplete")
    if metadata.synthetic:
        gaps.append("evidence_synthetic")
    if metadata.conflicts:
        gaps.append("evidence_conflicting")
    return tuple(gaps)


def _resource_type(record: OntologyObjectRecord | None) -> str | None:
    if record is None or record.object_type != "Resource":
        return None
    value = record.properties.get("type")
    return value if isinstance(value, str) else None


def _resource_properties(record: OntologyObjectRecord) -> Mapping[str, Any]:
    value = record.properties.get("properties")
    if not isinstance(value, Mapping):
        raise ValueError("rollout Resource properties are unavailable")
    return value


def _state_metadata(record: OntologyObjectRecord) -> StateFactMetadata:
    raw = record.properties.get(STATE_FACT_METADATA_PROPERTY)
    nested = record.properties.get("properties")
    if raw is None and isinstance(nested, Mapping):
        raw = nested.get(STATE_FACT_METADATA_PROPERTY)
    if not isinstance(raw, Mapping):
        raise ValueError("rollout Resource state evidence is unavailable")
    return StateFactMetadata.from_mapping(raw)


def _optional_int(properties: Mapping[str, Any], key: str) -> int | None:
    value = properties.get(key)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise ValueError(f"{key} MUST be an integer or null")
    return value


def _optional_text(properties: Mapping[str, Any], key: str) -> str | None:
    value = properties.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{key} MUST be text or null")
    return value


def _authenticate_query_receipt(
    query_result: SecuredObjectSetQueryResult,
    *,
    invocation_context: FunctionInvocationContext,
    expected_release: OntologyReleaseRef,
    expected_evidence_refs: tuple[str, ...] | None = None,
    receipt_verifier: NetworkQueryReceiptVerifier,
    verification_context: object,
) -> None:
    receipt = query_result.receipt
    expected_digest = receipt.projected_result_digest
    expected_refs = expected_evidence_refs or (expected_digest,)
    if receipt.ontology_release != expected_release:
        raise ValueError("Kubernetes rollout query result has the wrong ontology release")
    if receipt.purpose != KUBERNETES_ROLLOUT_PURPOSE:
        raise ValueError("Kubernetes rollout query result has the wrong purpose")
    if (
        receipt.caller_role != invocation_context.caller_role
        or invocation_context.purposes != (KUBERNETES_ROLLOUT_PURPOSE,)
        or invocation_context.evidence_refs != expected_refs
    ):
        raise PermissionError("Kubernetes rollout query receipt does not match invocation context")
    if not receipt_verifier.verify(
        receipt=receipt,
        invocation_context=invocation_context,
        expected_release=expected_release,
        expected_purpose=KUBERNETES_ROLLOUT_PURPOSE,
        expected_result_digest=expected_digest,
        verification_context=verification_context,
    ):
        raise PermissionError("Kubernetes rollout query receipt verification failed")


__all__ = [
    "KUBERNETES_ROLLOUT_FUNCTION_NAME",
    "KUBERNETES_ROLLOUT_PURPOSE",
    "KUBERNETES_ROLLOUT_SYMPTOM_CONCEPT",
    "evaluate_kubernetes_rollout_chain",
    "evaluate_kubernetes_rollout_graph",
    "kubernetes_rollout_function",
    "kubernetes_rollout_function_type",
]
