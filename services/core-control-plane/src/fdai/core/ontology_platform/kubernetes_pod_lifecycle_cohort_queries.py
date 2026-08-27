"""Controller-grounded durable Kubernetes Pod lifecycle cohort query."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
    OntologyReleaseRef,
)

from .functions import ContextualOntologyFunction, FunctionInvocationContext
from .kubernetes_pod_recovery_queries import (
    KUBERNETES_POD_RECOVERY_PURPOSE,
    _owner_deployment_observation,
    _resource_properties,
    _resource_type,
)
from .network_path import NetworkQueryReceiptVerifier
from .query_gateway import SecuredObjectSetQueryResult

KUBERNETES_POD_LIFECYCLE_COHORT_FUNCTION_NAME = "query.kubernetes_pod_lifecycle_cohort"


class KubernetesPodLifecycleCohortReader(Protocol):
    """Read a bounded historical Pod cohort from retained controller identity."""

    async def read_pod_lifecycle_cohort(
        self,
        *,
        current_pod_id: str,
        current_pod_uid: str,
        namespace: str,
        root_controller_uid: str,
        lookback_seconds: int,
        observed_at: datetime,
    ) -> Mapping[str, object]: ...


def kubernetes_pod_lifecycle_cohort_function_type() -> OntologyFunctionType:
    """Declare the read-only durable Pod lifecycle cohort query."""

    return OntologyFunctionType(
        name=KUBERNETES_POD_LIFECYCLE_COHORT_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "pod_query_result",
                "controller_query_result",
                "deployment_query_result",
                "lookback_seconds",
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
                "lookback_seconds": {
                    "type": "integer",
                    "minimum": 60,
                    "maximum": 86_400,
                },
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "complete",
                "truncation_reason",
                "current_pod_uid",
                "root_controller_uid",
                "window_start",
                "rows",
                "attempt_ref",
                "execution_authority",
            ],
            "properties": {
                "complete": {"type": "boolean"},
                "truncation_reason": {"type": ["string", "null"]},
                "current_pod_uid": {"type": "string"},
                "root_controller_uid": {"type": "string"},
                "window_start": {"type": "string", "format": "date-time"},
                "rows": {"type": "array", "maxItems": 256},
                "attempt_ref": {"type": "string"},
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


def kubernetes_pod_lifecycle_cohort_function(
    ontology_release: OntologyRelease,
    *,
    reader: KubernetesPodLifecycleCohortReader,
    receipt_verifier: NetworkQueryReceiptVerifier,
    verification_context: object,
) -> ContextualOntologyFunction:
    """Bind the cohort query to authenticated graph lineage and durable history."""

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
            sorted(item.receipt.projected_result_digest for item in query_results)
        )
        for result in query_results:
            _authenticate(
                result,
                invocation_context=invocation_context,
                expected_release=expected_release,
                expected_evidence_refs=expected_evidence_refs,
                receipt_verifier=receipt_verifier,
                verification_context=verification_context,
            )
        objects = pod_result.materialization.graph.objects
        if len(objects) != 1 or _resource_type(objects[0]) != "kubernetes.pod":
            raise ValueError("Pod lifecycle cohort query MUST resolve one Pod")
        pod = objects[0]
        pod_properties = _resource_properties(pod)
        current_pod_uid = _required_text(pod_properties, "uid")
        namespace = _required_text(pod_properties, "namespace")
        _owner, ownership_gaps, _refs = _owner_deployment_observation(
            pod=pod,
            controller_result=controller_result,
            deployment_result=deployment_result,
            cutoff=pod_result.receipt.observation_cutoff,
        )
        if ownership_gaps:
            raise ValueError("Pod lifecycle cohort ownership evidence is incomplete")
        deployments = tuple(
            item
            for item in deployment_result.materialization.graph.objects
            if _resource_type(item) == "kubernetes.deployment"
        )
        if len(deployments) != 1:
            raise ValueError("Pod lifecycle cohort query MUST resolve one Deployment")
        root_controller_uid = _required_text(
            _resource_properties(deployments[0]),
            "uid",
        )
        return await reader.read_pod_lifecycle_cohort(
            current_pod_id=pod.id,
            current_pod_uid=current_pod_uid,
            namespace=namespace,
            root_controller_uid=root_controller_uid,
            lookback_seconds=int(arguments["lookback_seconds"]),
            observed_at=pod_result.receipt.observation_cutoff,
        )

    return evaluate


def _authenticate(
    query_result: SecuredObjectSetQueryResult,
    *,
    invocation_context: FunctionInvocationContext,
    expected_release: OntologyReleaseRef,
    expected_evidence_refs: tuple[str, ...],
    receipt_verifier: NetworkQueryReceiptVerifier,
    verification_context: object,
) -> None:
    receipt = query_result.receipt
    if receipt.ontology_release != expected_release:
        raise ValueError("Kubernetes Pod lifecycle cohort has the wrong ontology release")
    if receipt.purpose != KUBERNETES_POD_RECOVERY_PURPOSE:
        raise ValueError("Kubernetes Pod lifecycle cohort has the wrong purpose")
    if (
        receipt.caller_role != invocation_context.caller_role
        or invocation_context.purposes != (KUBERNETES_POD_RECOVERY_PURPOSE,)
        or invocation_context.evidence_refs != expected_evidence_refs
    ):
        raise PermissionError("Kubernetes Pod lifecycle cohort receipt context is invalid")
    if not receipt_verifier.verify(
        receipt=receipt,
        invocation_context=invocation_context,
        expected_release=expected_release,
        expected_purpose=KUBERNETES_POD_RECOVERY_PURPOSE,
        expected_result_digest=receipt.projected_result_digest,
        verification_context=verification_context,
    ):
        raise PermissionError("Kubernetes Pod lifecycle cohort receipt verification failed")


def _required_text(properties: Mapping[str, Any], key: str) -> str:
    value = properties.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Kubernetes Pod lifecycle {key} is unavailable")
    return value.strip()


__all__ = [
    "KUBERNETES_POD_LIFECYCLE_COHORT_FUNCTION_NAME",
    "KubernetesPodLifecycleCohortReader",
    "kubernetes_pod_lifecycle_cohort_function",
    "kubernetes_pod_lifecycle_cohort_function_type",
]
