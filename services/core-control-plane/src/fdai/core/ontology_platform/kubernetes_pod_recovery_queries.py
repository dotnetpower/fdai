"""Issued exact-release Kubernetes Pod restart and recovery evidence query."""

from __future__ import annotations

import hashlib
import math
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
from .kubernetes_lifecycle_observation import KubernetesLifecycleObservation
from .kubernetes_pod_recovery_evidence import (
    KubernetesPodRecoveryEvidenceResult,
    KubernetesPodRecoveryStatus,
    PodOwnerDeploymentObservation,
    PodRecoveryObservation,
    PodRestartHistoryObservation,
    evaluate_kubernetes_pod_recovery,
)
from .kubernetes_pod_replacement_evidence import (
    KubernetesPodReplacementEvidenceResult,
    PodLifecycleObservation,
    PodReplacementDeploymentObservation,
    evaluate_kubernetes_pod_replacement_from_lifecycle,
)
from .network_path import NetworkQueryReceiptVerifier
from .query_gateway import SecuredObjectSetQueryResult

KUBERNETES_POD_RECOVERY_FUNCTION_NAME = "query.kubernetes_pod_recovery_evidence"
KUBERNETES_POD_RECOVERY_PURPOSE = "operations-review"
KUBERNETES_POD_RESTART_SYMPTOM_CONCEPT = "pod.restart"
KUBERNETES_POD_RESTART_HISTORY_CONCEPT = "pod.restart.history"


def _source_artifact_digest() -> str:
    source = Path(__file__).read_bytes()
    reducer = Path(__file__).with_name("kubernetes_pod_recovery_evidence.py").read_bytes()
    return f"sha256:{hashlib.sha256(source + b'\0' + reducer).hexdigest()}"


def kubernetes_pod_recovery_function_type() -> OntologyFunctionType:
    """Return the read-only deterministic Pod recovery declaration."""

    return OntologyFunctionType(
        name=KUBERNETES_POD_RECOVERY_FUNCTION_NAME,
        version="1.2.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=_source_artifact_digest(),
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "pod_query_result",
                "controller_query_result",
                "deployment_query_result",
                "restart_history",
            ],
            "properties": {
                "pod_query_result": {
                    "type": "object",
                    "x-fdai-dependency-only": True,
                },
                "controller_query_result": {
                    "type": "object",
                    "x-fdai-dependency-only": True,
                },
                "deployment_query_result": {
                    "type": "object",
                    "x-fdai-dependency-only": True,
                },
                "restart_history": {
                    "type": "object",
                    "x-fdai-dependency-only": True,
                },
                "lifecycle_events": {
                    "type": "object",
                    "x-fdai-dependency-only": True,
                },
                "cutoff": {"type": "string", "format": "date-time"},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "pod_id",
                "status",
                "complete",
                "restart_observed",
                "recovery_verified",
                "restart_history_complete",
                "restart_observed_in_window",
                "restart_delta",
                "restart_window_start",
                "restart_window_end",
                "owner_deployment_id",
                "deployment_recovery_verified",
                "waiting_reasons",
                "evidence_gaps",
                "evidence_refs",
                "cause_claim_supported",
                "execution_authority",
            ],
            "properties": {
                "pod_id": {"type": "string"},
                "status": {
                    "enum": [
                        "restart_observed_recovered",
                        "restart_observed_not_recovered",
                        "insufficient_evidence",
                        "conflicting_evidence",
                    ]
                },
                "complete": {"type": "boolean"},
                "restart_observed": {"type": "boolean"},
                "recovery_verified": {"type": "boolean"},
                "phase": {"type": ["string", "null"]},
                "ready": {"type": ["boolean", "null"]},
                "container_count": {"type": ["integer", "null"], "minimum": 0},
                "ready_container_count": {"type": ["integer", "null"], "minimum": 0},
                "restart_count": {"type": ["integer", "null"], "minimum": 0},
                "restart_history_complete": {"type": "boolean"},
                "restart_observed_in_window": {"type": "boolean"},
                "restart_delta": {"type": ["integer", "null"], "minimum": 0},
                "restart_window_start": {"type": "string", "format": "date-time"},
                "restart_window_end": {"type": "string", "format": "date-time"},
                "owner_deployment_id": {"type": "string"},
                "desired_replicas": {"type": ["integer", "null"], "minimum": 0},
                "ready_replicas": {"type": ["integer", "null"], "minimum": 0},
                "available_replicas": {"type": ["integer", "null"], "minimum": 0},
                "unavailable_replicas": {"type": ["integer", "null"], "minimum": 0},
                "deployment_recovery_verified": {"type": "boolean"},
                "waiting_reasons": {"type": "array", "maxItems": 32},
                "evidence_gaps": {"type": "array", "maxItems": 64},
                "evidence_refs": {"type": "array", "maxItems": 128},
                "cause_claim_supported": {"const": False},
                "execution_authority": {"const": False},
            },
        },
        read_sets=["Resource", "kubernetes_owned_by"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=[KUBERNETES_POD_RECOVERY_PURPOSE],
        timeout_seconds=5,
        cpu_millis=1000,
        memory_bytes=134_217_728,
        max_output_bytes=131_072,
        network_allowed=False,
        credentials_allowed=False,
    )


def kubernetes_pod_recovery_function(
    ontology_release: OntologyRelease,
    *,
    receipt_verifier: NetworkQueryReceiptVerifier,
    verification_context: object,
) -> ContextualOntologyFunction:
    """Bind Pod recovery assessment to one composition-issued secured result."""

    if verification_context is None:
        raise ValueError("Kubernetes Pod recovery verification context MUST be non-null")
    expected_release = ontology_release.ref()

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        pod_result = SecuredObjectSetQueryResult.model_validate(arguments["pod_query_result"])
        controller_result = SecuredObjectSetQueryResult.model_validate(
            arguments["controller_query_result"]
        )
        deployment_result = SecuredObjectSetQueryResult.model_validate(
            arguments["deployment_query_result"]
        )
        query_results = (pod_result, controller_result, deployment_result)
        expected_evidence_refs = tuple(
            sorted(result.receipt.projected_result_digest for result in query_results)
        )
        for query_result in query_results:
            _authenticate_query_receipt(
                query_result,
                invocation_context=invocation_context,
                expected_release=expected_release,
                expected_evidence_refs=expected_evidence_refs,
                receipt_verifier=receipt_verifier,
                verification_context=verification_context,
            )
        cutoff = (
            datetime.fromisoformat(str(arguments["cutoff"]).replace("Z", "+00:00"))
            if "cutoff" in arguments
            else pod_result.receipt.observation_cutoff
        )
        if cutoff.tzinfo is None or any(
            cutoff != result.receipt.observation_cutoff for result in query_results
        ):
            raise ValueError("Kubernetes Pod recovery cutoff MUST equal the secured query cutoff")
        result = evaluate_kubernetes_pod_recovery_graph(
            pod_result,
            controller_result=controller_result,
            deployment_result=deployment_result,
            restart_history=arguments["restart_history"],
            cutoff=cutoff,
        )
        lifecycle_events = arguments.get("lifecycle_events")
        if isinstance(lifecycle_events, Mapping) and lifecycle_events.get("complete") is False:
            reason = lifecycle_events.get("truncation_reason")
            gap = (
                f"lifecycle_events_{reason}"
                if isinstance(reason, str) and reason
                else "lifecycle_events_incomplete"
            )
            result = result.model_copy(
                update={
                    "complete": False,
                    "recovery_verified": False,
                    "status": KubernetesPodRecoveryStatus.INSUFFICIENT_EVIDENCE,
                    "evidence_gaps": tuple(dict.fromkeys((*result.evidence_gaps, gap))),
                }
            )
        return result

    return evaluate


def evaluate_kubernetes_pod_recovery_graph(
    secured: SecuredObjectSetQueryResult,
    *,
    controller_result: SecuredObjectSetQueryResult,
    deployment_result: SecuredObjectSetQueryResult,
    restart_history: object,
    cutoff: datetime,
) -> KubernetesPodRecoveryEvidenceResult:
    """Assess one exact secured Pod without provider I/O."""

    if cutoff.tzinfo is None:
        raise ValueError("Kubernetes Pod recovery cutoff MUST be timezone-aware")
    if secured.receipt.purpose != KUBERNETES_POD_RECOVERY_PURPOSE:
        raise ValueError("secured Pod recovery graph has the wrong purpose")
    objects = secured.materialization.graph.objects
    if len(objects) != 1:
        raise ValueError("secured Pod recovery query MUST return one Pod")
    pod = objects[0]
    if _resource_type(pod) != "kubernetes.pod":
        raise ValueError("secured Pod recovery target is not a Kubernetes Pod")
    properties = _resource_properties(pod)
    history = _restart_history_observation(restart_history, pod_id=pod.id)
    owner_deployment, ownership_gaps, ownership_refs = _owner_deployment_observation(
        pod=pod,
        controller_result=controller_result,
        deployment_result=deployment_result,
        cutoff=cutoff,
    )
    ready = properties.get("ready")
    if ready is not None and not isinstance(ready, bool):
        raise ValueError("Pod ready evidence MUST be boolean or null")
    reasons = properties.get("container_waiting_reasons", ())
    if not isinstance(reasons, Sequence) or isinstance(reasons, (str, bytes)):
        raise ValueError("Pod waiting reasons MUST be a sequence")
    query_results = (secured, controller_result, deployment_result)
    result = evaluate_kubernetes_pod_recovery(
        pod=PodRecoveryObservation(
            pod_id=pod.id,
            phase=_optional_text(properties, "phase"),
            ready=ready,
            container_count=_optional_int(properties, "container_count"),
            ready_container_count=_optional_int(properties, "ready_container_count"),
            restart_count=_optional_int(properties, "restart_count"),
            waiting_reasons=tuple(str(reason) for reason in reasons),
            metadata=_state_metadata(pod),
        ),
        restart_history=history,
        owner_deployment=owner_deployment,
        cutoff=cutoff,
        graph_complete=all(
            result.receipt.complete and not result.materialization.graph.truncated
            for result in query_results
        ),
        ownership_complete=not ownership_gaps,
    )
    evidence_refs = tuple(sorted(set((*result.evidence_refs, *ownership_refs))))
    if not ownership_gaps:
        return result.model_copy(update={"evidence_refs": evidence_refs})

    return result.model_copy(
        update={
            "complete": False,
            "recovery_verified": False,
            "evidence_gaps": tuple(dict.fromkeys((*result.evidence_gaps, *ownership_gaps))),
            "evidence_refs": evidence_refs,
        }
    )


def evaluate_kubernetes_pod_replacement_graph(
    *,
    old_pod: PodLifecycleObservation,
    candidates: tuple[PodLifecycleObservation, ...],
    lifecycle_observations: tuple[KubernetesLifecycleObservation, ...],
    deployment: PodReplacementDeploymentObservation | None,
    correlation_window_start: datetime,
    cutoff: datetime,
) -> KubernetesPodReplacementEvidenceResult:
    """Run the exact-target replacement reducer over retained lifecycle evidence."""

    return evaluate_kubernetes_pod_replacement_from_lifecycle(
        old_pod=old_pod,
        candidates=candidates,
        lifecycle_observations=lifecycle_observations,
        deployment=deployment,
        correlation_window_start=correlation_window_start,
        cutoff=cutoff,
    )


def _owner_deployment_observation(
    *,
    pod: OntologyObjectRecord,
    controller_result: SecuredObjectSetQueryResult,
    deployment_result: SecuredObjectSetQueryResult,
    cutoff: datetime,
) -> tuple[PodOwnerDeploymentObservation, tuple[str, ...], tuple[str, ...]]:
    controller_graph = controller_result.materialization.graph
    if controller_result.materialization.definition.root_ids != (pod.id,):
        raise ValueError("secured Pod controller query has the wrong root")
    replica_sets = tuple(
        record
        for record in controller_graph.objects
        if _resource_type(record) == "kubernetes.replica-set"
    )
    if len(replica_sets) != 1:
        raise ValueError("secured Pod controller query MUST return one ReplicaSet")
    replica_set = replica_sets[0]
    pod_links = tuple(
        link
        for link in controller_graph.links
        if link.link_type == "kubernetes_owned_by"
        and link.from_id == pod.id
        and link.to_id == replica_set.id
    )
    if len(pod_links) != 1:
        raise ValueError("secured Pod controller ownership path is invalid")

    deployment_graph = deployment_result.materialization.graph
    if deployment_result.materialization.definition.root_ids != (replica_set.id,):
        raise ValueError("secured Pod Deployment query has the wrong controller root")
    deployments = tuple(
        record
        for record in deployment_graph.objects
        if _resource_type(record) == "kubernetes.deployment"
    )
    if len(deployments) != 1:
        raise ValueError("secured Pod Deployment query MUST return one Deployment")
    deployment = deployments[0]
    deployment_links = tuple(
        link
        for link in deployment_graph.links
        if link.link_type == "kubernetes_owned_by"
        and link.from_id == replica_set.id
        and link.to_id == deployment.id
    )
    if len(deployment_links) != 1:
        raise ValueError("secured Pod Deployment ownership path is invalid")
    gaps, references = _ownership_evidence((*pod_links, *deployment_links), cutoff=cutoff)
    deployment_properties = _resource_properties(deployment)
    return (
        PodOwnerDeploymentObservation(
            deployment_id=deployment.id,
            desired_replicas=_optional_int(deployment_properties, "desired_replicas"),
            ready_replicas=_optional_int(deployment_properties, "ready_replicas"),
            available_replicas=_optional_int(deployment_properties, "available_replicas"),
            unavailable_replicas=_optional_int(
                deployment_properties,
                "unavailable_replicas",
            ),
            metadata=_state_metadata(deployment),
        ),
        gaps,
        references,
    )


def _ownership_evidence(
    links: tuple[OntologyLinkRecord, ...],
    *,
    cutoff: datetime,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    gaps: list[str] = []
    references: set[str] = set()
    for link in links:
        raw = link.properties.get(LINK_OBSERVATION_METADATA_PROPERTY)
        if not isinstance(raw, Mapping):
            gaps.append("pod_ownership_evidence_missing")
            continue
        metadata = LinkObservationMetadata.from_mapping(raw)
        references.update(metadata.state_fact.evidence_refs)
        if metadata.verification_receipt_ref is not None:
            references.add(metadata.verification_receipt_ref)
        if not metadata.verified:
            gaps.append("pod_ownership_evidence_unverified")
        evidence_cutoff = metadata.state_fact.evidence_cutoff.astimezone(UTC)
        normalized_cutoff = cutoff.astimezone(UTC)
        if evidence_cutoff > normalized_cutoff:
            gaps.append("pod_ownership_evidence_after_cutoff")
        elif (
            normalized_cutoff - evidence_cutoff
        ).total_seconds() > metadata.state_fact.freshness_ceiling_seconds:
            gaps.append("pod_ownership_evidence_stale")
        if metadata.state_fact.completeness < 1.0:
            gaps.append("pod_ownership_evidence_incomplete")
        if metadata.state_fact.synthetic:
            gaps.append("pod_ownership_evidence_synthetic")
        if metadata.state_fact.conflicts:
            gaps.append("pod_ownership_evidence_conflicting")
    return tuple(dict.fromkeys(gaps)), tuple(sorted(references))


def _restart_history_observation(
    value: object,
    *,
    pod_id: str,
) -> PodRestartHistoryObservation:
    if not isinstance(value, Mapping):
        raise ValueError("Pod restart history metric window is invalid")
    if (
        value.get("concept_id") != KUBERNETES_POD_RESTART_HISTORY_CONCEPT
        or value.get("resource_id") != pod_id
        or value.get("unit") != "count"
    ):
        raise ValueError("Pod restart history metric identity is invalid")
    start = _timestamp(value.get("start"), "restart_history.start")
    end = _timestamp(value.get("end"), "restart_history.end")
    complete = value.get("complete")
    missing_reason = value.get("missing_reason")
    if not isinstance(complete, bool) or (
        missing_reason is not None and not isinstance(missing_reason, str)
    ):
        raise ValueError("Pod restart history completeness is invalid")
    raw_samples = value.get("samples")
    if not isinstance(raw_samples, Sequence) or isinstance(raw_samples, (str, bytes)):
        raise ValueError("Pod restart history samples are invalid")
    total = 0.0
    for sample in raw_samples:
        if not isinstance(sample, Mapping):
            raise ValueError("Pod restart history sample is invalid")
        sample_value = sample.get("value")
        if isinstance(sample_value, bool) or not isinstance(sample_value, int | float):
            raise ValueError("Pod restart history sample value is invalid")
        converted = float(sample_value)
        if not math.isfinite(converted) or converted < 0:
            raise ValueError("Pod restart history sample value is invalid")
        total += converted
    if not total.is_integer():
        raise ValueError("Pod restart history delta MUST be an integer count")
    raw_refs = value.get("evidence_refs")
    if (
        not isinstance(raw_refs, Sequence)
        or isinstance(raw_refs, (str, bytes))
        or any(not isinstance(item, str) or not item for item in raw_refs)
    ):
        raise ValueError("Pod restart history evidence references are invalid")
    return PodRestartHistoryObservation(
        pod_id=pod_id,
        start=start,
        end=end,
        restart_delta=int(total) if complete else None,
        complete=complete,
        missing_reason=missing_reason,
        evidence_refs=tuple(raw_refs),
    )


def _timestamp(value: object, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} MUST be an RFC 3339 timestamp") from exc
    else:
        raise ValueError(f"{field} MUST be an RFC 3339 timestamp")
    if parsed.tzinfo is None:
        raise ValueError(f"{field} MUST be timezone-aware")
    return parsed


def _authenticate_query_receipt(
    query_result: SecuredObjectSetQueryResult,
    *,
    invocation_context: FunctionInvocationContext,
    expected_release: OntologyReleaseRef,
    expected_evidence_refs: tuple[str, ...],
    receipt_verifier: NetworkQueryReceiptVerifier,
    verification_context: object,
) -> None:
    receipt = query_result.receipt
    expected_digest = receipt.projected_result_digest
    if receipt.ontology_release != expected_release:
        raise ValueError("Kubernetes Pod recovery result has the wrong ontology release")
    if receipt.purpose != KUBERNETES_POD_RECOVERY_PURPOSE:
        raise ValueError("Kubernetes Pod recovery result has the wrong purpose")
    if (
        receipt.caller_role != invocation_context.caller_role
        or invocation_context.purposes != (KUBERNETES_POD_RECOVERY_PURPOSE,)
        or invocation_context.evidence_refs != expected_evidence_refs
    ):
        raise PermissionError("Kubernetes Pod recovery receipt does not match invocation context")
    if not receipt_verifier.verify(
        receipt=receipt,
        invocation_context=invocation_context,
        expected_release=expected_release,
        expected_purpose=KUBERNETES_POD_RECOVERY_PURPOSE,
        expected_result_digest=expected_digest,
        verification_context=verification_context,
    ):
        raise PermissionError("Kubernetes Pod recovery receipt verification failed")


def _resource_type(record: OntologyObjectRecord) -> str | None:
    if record.object_type != "Resource":
        return None
    value = record.properties.get("type")
    return value if isinstance(value, str) else None


def _resource_properties(record: OntologyObjectRecord) -> Mapping[str, Any]:
    value = record.properties.get("properties")
    if not isinstance(value, Mapping):
        raise ValueError("Pod Resource properties are unavailable")
    return value


def _state_metadata(record: OntologyObjectRecord) -> StateFactMetadata:
    properties = _resource_properties(record)
    raw = properties.get(STATE_FACT_METADATA_PROPERTY)
    if not isinstance(raw, Mapping):
        raise ValueError("Pod Resource state evidence is unavailable")
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


__all__ = [
    "KUBERNETES_POD_RECOVERY_FUNCTION_NAME",
    "KUBERNETES_POD_RECOVERY_PURPOSE",
    "KUBERNETES_POD_RESTART_HISTORY_CONCEPT",
    "KUBERNETES_POD_RESTART_SYMPTOM_CONCEPT",
    "evaluate_kubernetes_pod_recovery_graph",
    "evaluate_kubernetes_pod_replacement_graph",
    "kubernetes_pod_recovery_function",
    "kubernetes_pod_recovery_function_type",
]
