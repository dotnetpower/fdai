"""Project collected Kubernetes evaluation evidence into the ontology read model."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fdai_evaluation_sdk import EvaluationTask

from fdai.core.ontology_platform import FunctionInvocationReceipt, ontology_function_digest
from fdai.core.ontology_platform.diagnostic_results import (
    DiagnosticResultProjector,
    build_diagnostic_result_projection,
)
from fdai.delivery.kubernetes.ontology_functions import diagnostic_function_types
from fdai.delivery.kubernetes.ontology_projection import (
    KubernetesOntologyProjection,
    build_kubernetes_ontology_projection,
)
from fdai.shared.contracts.models import OntologyDeclarationKind
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyObjectRecord,
    canonical_json_mapping,
)

_REASON_MECHANISMS = {
    "admission_webhook_backend_service_missing_candidate": (
        "kubernetes_missing_webhook_backend_candidate"
    ),
    "admission_webhook_failure_configuration_candidate": (
        "kubernetes_webhook_failure_source_candidate"
    ),
    "application_socket_bind_conflict_candidate": (
        "kubernetes_application_socket_bind_conflict_candidate"
    ),
    "bounded_application_log_signal_candidate": "kubernetes_bounded_application_log_signals",
    "coredns_global_service_nxdomain_candidate": "kubernetes_coredns_global_nxdomain_candidate",
    "cumulative_admission_webhook_timeout_candidate": (
        "kubernetes_cumulative_webhook_timeout_candidate"
    ),
    "custom_owner_has_degraded_workload": "kubernetes_custom_owner_degradation_relationship",
    "deployment_zero_availability_rollout_candidate": (
        "kubernetes_zero_availability_rollout_candidate"
    ),
    "hpa_cpu_utilization_missing_request_candidate": (
        "kubernetes_hpa_cpu_utilization_missing_request_candidate"
    ),
    "pod_host_port_conflict_candidate": "kubernetes_pod_host_port_conflict_candidate",
    "pod_image_pull_controller_template_drift_candidate": (
        "kubernetes_image_pull_controller_template_drift_candidate"
    ),
    "pod_resource_drift_with_global_mutator_candidate": (
        "kubernetes_admission_resource_drift_reducer"
    ),
    "pod_resource_request_exceeds_node_capacity": "kubernetes_capacity_reducer",
    "pod_security_restricted_workload_mismatch_candidate": (
        "kubernetes_pod_security_restricted_mismatch_candidate"
    ),
    "service_backend_scaled_to_zero_candidate": (
        "kubernetes_service_backend_scaled_to_zero_candidate"
    ),
    "workload_endpoint_targets_missing_service": "kubernetes_missing_dependency_reducer",
    "workload_init_container_missing_service_candidate": (
        "kubernetes_init_container_missing_service_candidate"
    ),
    "workload_liveness_probe_failure_candidate": "kubernetes_liveness_probe_failure_candidate",
    "workload_missing_configmap_mount_candidate": "kubernetes_missing_configmap_mount_candidate",
    "workload_readiness_probe_failure_candidate": "kubernetes_readiness_probe_failure_candidate",
    "workload_rwo_claim_anti_affinity_conflict_candidate": (
        "kubernetes_rwo_anti_affinity_conflict_candidate"
    ),
}


@dataclass(frozen=True, slots=True)
class KubernetesOntologyEvidenceObserver:
    """Persist A0 topology and hold provenance before evaluation judgment."""

    store: OntologyInstanceStore
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    release: Any = field(
        default_factory=lambda: build_ontology_release(function_types=diagnostic_function_types())
    )

    async def observe(
        self,
        *,
        task: EvaluationTask,
        evidence: Mapping[str, Any],
    ) -> None:
        if task.target.kind != "kubernetes.namespace":
            return
        observed_at = self.clock()
        if observed_at.tzinfo is None:
            raise ValueError("Kubernetes ontology observer clock MUST be timezone-aware")
        cluster_name, cluster_ref = _cluster_scope(evidence)
        namespace_ref = f"{cluster_ref}/namespace/{task.target.value}"
        namespace_record = OntologyObjectRecord(
            id=namespace_ref,
            object_type="Resource",
            properties={
                "id": namespace_ref,
                "type": "kubernetes.namespace",
                "name": task.target.value,
                "properties": {
                    "cluster_ref": cluster_ref,
                    "namespace": task.target.value,
                },
            },
        )
        topology, topology_complete, topology_observed = self._topology(
            evidence,
            expected_namespace=task.target.value,
            cluster_ref=cluster_ref,
        )
        topology_objects = topology.objects
        if all(record.id != namespace_ref for record in topology_objects):
            topology_objects = (namespace_record, *topology_objects)
        await _project_current_topology(
            self.store,
            KubernetesOntologyProjection(
                objects=topology_objects,
                links=topology.links,
            ),
            namespace_ref=namespace_ref,
            replace_objects=topology_complete,
            refresh_links=topology_observed,
        )
        projector = DiagnosticResultProjector(store=self.store)
        for _capability_id, entry in sorted(evidence.items()):
            payload = _available_payload(entry)
            if payload is None:
                continue
            findings = _mappings(payload.get("findings"))
            by_mechanism: dict[str, list[Mapping[str, Any]]] = {}
            for finding in findings:
                mechanism_id = _mechanism_for_reason(finding.get("reason"))
                by_mechanism.setdefault(mechanism_id, []).append(finding)
            if not by_mechanism:
                continue
            receipts = _receipts_by_mechanism(payload)
            inputs = _inputs_by_mechanism(payload)
            for mechanism_id, mechanism_findings in sorted(by_mechanism.items()):
                try:
                    receipt = receipts[mechanism_id]
                except KeyError as exc:
                    raise ValueError(
                        "diagnostic findings require a matching ontology function receipt"
                    ) from exc
                expected_ref = self.release.type_ref(
                    OntologyDeclarationKind.FUNCTION,
                    f"diagnostic.{mechanism_id}",
                )
                if receipt.function_ref != expected_ref or receipt.caller_agent != "Heimdall":
                    raise ValueError(
                        "diagnostic receipt does not match the active function release"
                    )
                try:
                    function_arguments = inputs[mechanism_id]
                except KeyError as exc:
                    raise ValueError(
                        "diagnostic findings require matching ontology function inputs"
                    ) from exc
                if ontology_function_digest(function_arguments) != receipt.input_digest:
                    raise ValueError("diagnostic inputs do not match function receipt input")
                if ontology_function_digest(mechanism_findings) != receipt.output_digest:
                    raise ValueError("diagnostic findings do not match function receipt output")
                invocation_identity = ontology_function_digest(
                    {
                        "function_ref": receipt.function_ref.model_dump(mode="json"),
                        "input_digest": receipt.input_digest,
                        "output_digest": receipt.output_digest,
                        "caller_agent": receipt.caller_agent,
                    }
                ).removeprefix("sha256:")
                if receipt.invocation_id != f"logic-invocation:{invocation_identity}":
                    raise ValueError("diagnostic invocation identity is invalid")
                function_ref = receipt.function_ref
                projection = build_diagnostic_result_projection(
                    mechanism_id=mechanism_id,
                    findings=mechanism_findings,
                    evidence={
                        "evidence_complete": payload.get("evidence_complete") is True,
                        "function_arguments": function_arguments,
                    },
                    evidence_ref=receipt.invocation_id,
                    source_revision=function_ref.catalog_digest,
                    invocation_receipt=receipt.model_dump(mode="json"),
                    resource_ref=namespace_ref,
                    observed_at=receipt.completed_at,
                )
                await projector.project(projection)

    def _topology(
        self,
        evidence: Mapping[str, Any],
        *,
        expected_namespace: str,
        cluster_ref: str,
    ) -> tuple[KubernetesOntologyProjection, bool, bool]:
        payload = _available_payload(evidence.get("observe.kubernetes.inventory"))
        if payload is None:
            return KubernetesOntologyProjection(objects=(), links=()), False, False
        evidence_complete = payload.get("evidence_complete") is True
        resources = _mappings(payload.get("resources"))
        projection = build_kubernetes_ontology_projection(
            resources,
            evidence_complete=evidence_complete,
            expected_namespace=expected_namespace,
            cluster_ref=cluster_ref,
        )
        namespace_ref = f"{cluster_ref}/namespace/{expected_namespace}"
        projected_resource_count = sum(record.id != namespace_ref for record in projection.objects)
        topology_complete = evidence_complete and projected_resource_count == len(resources)
        if not topology_complete:
            projection = KubernetesOntologyProjection(objects=projection.objects, links=())
        return projection, topology_complete, True


async def _project_current_topology(
    store: OntologyInstanceStore,
    projection: KubernetesOntologyProjection,
    *,
    namespace_ref: str,
    replace_objects: bool,
    refresh_links: bool,
) -> None:
    missing: list[OntologyObjectRecord] = []
    for record in projection.objects:
        existing = await store.get_object(record.id)
        if existing is None:
            missing.append(record)
            continue
        normalized, _ = canonical_json_mapping(
            record.properties,
            path=f"{record.object_type}.properties",
        )
        if existing.object_type != record.object_type or existing.properties != normalized:
            raise ValueError("immutable Kubernetes ontology identity changed")
    previous_object_ids: tuple[str, ...] = ()
    previous_link_keys: tuple[tuple[str, str, str], ...] = ()
    if refresh_links:
        current = await store.query_objects(
            object_types=("Resource",),
            property_equals={"parent_id": namespace_ref},
            limit=1000,
        )
        if current.truncated:
            raise ValueError("existing Kubernetes namespace topology is truncated")
        projected_ids = {record.id for record in projection.objects}
        if replace_objects:
            previous_object_ids = tuple(
                record.id for record in current.objects if record.id not in projected_ids
            )
        topology_link_types = {
            "contains",
            "depends_on",
            "kubernetes_exposes_endpoints",
            "kubernetes_owned_by",
            "kubernetes_selects",
        }
        keys = {
            (record.from_id, record.link_type, record.to_id)
            for record in current.links
            if record.link_type in topology_link_types
        }
        keys.update((namespace_ref, "contains", record.id) for record in current.objects)
        previous_link_keys = tuple(sorted(keys))
    await store.replace_subgraph(
        objects=tuple(missing),
        links=projection.links,
        previous_object_ids=previous_object_ids,
        previous_link_keys=previous_link_keys,
    )


def _available_payload(value: object) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping) or value.get("status") != "available":
        return None
    payload = value.get("payload")
    return payload if isinstance(payload, Mapping) else None


def _cluster_scope(evidence: Mapping[str, Any]) -> tuple[str, str]:
    clusters = {
        cluster.strip()
        for entry in evidence.values()
        if (payload := _available_payload(entry)) is not None
        and isinstance((cluster := payload.get("cluster")), str)
        and cluster.strip()
    }
    available_count = sum(_available_payload(entry) is not None for entry in evidence.values())
    if len(clusters) != 1 or available_count == 0:
        raise ValueError("Kubernetes ontology evidence requires one exact cluster identity")
    cluster_name = next(iter(clusters))
    if any(
        payload.get("cluster") != cluster_name
        for entry in evidence.values()
        if (payload := _available_payload(entry)) is not None
    ):
        raise ValueError("Kubernetes ontology evidence crossed the target cluster")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", cluster_name) is None:
        raise ValueError("Kubernetes ontology cluster identity MUST be SHA-256")
    return cluster_name, f"kubernetes.cluster:{cluster_name.removeprefix('sha256:')}"


def _mechanism_for_reason(value: object) -> str:
    if isinstance(value, str) and value.startswith("kubernetes_condition_"):
        return "kubernetes_direct_admission_condition_evidence"
    if isinstance(value, str) and value in _REASON_MECHANISMS:
        return _REASON_MECHANISMS[value]
    raise ValueError("diagnostic finding reason has no ontology mechanism")


def _mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _receipts_by_mechanism(
    payload: Mapping[str, Any],
) -> dict[str, FunctionInvocationReceipt]:
    receipts: dict[str, FunctionInvocationReceipt] = {}
    for raw_receipt in _mappings(payload.get("function_receipts")):
        receipt = FunctionInvocationReceipt.model_validate(raw_receipt)
        function_name = receipt.function_ref.name
        if not function_name.startswith("diagnostic."):
            raise ValueError("diagnostic function receipt has an invalid function name")
        mechanism_id = function_name.removeprefix("diagnostic.")
        if mechanism_id in receipts:
            raise ValueError("duplicate diagnostic function receipt")
        receipts[mechanism_id] = receipt
    return receipts


def _inputs_by_mechanism(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    inputs: dict[str, Mapping[str, Any]] = {}
    for binding in _mappings(payload.get("function_inputs")):
        function_name = binding.get("function_name")
        arguments = binding.get("arguments")
        if (
            not isinstance(function_name, str)
            or not function_name.startswith("diagnostic.")
            or not isinstance(arguments, Mapping)
        ):
            raise ValueError("diagnostic function input binding is invalid")
        mechanism_id = function_name.removeprefix("diagnostic.")
        if mechanism_id in inputs:
            raise ValueError("duplicate diagnostic function input binding")
        normalized, _ = canonical_json_mapping(
            arguments,
            path=f"{function_name}.arguments",
        )
        inputs[mechanism_id] = normalized
    return inputs


__all__ = ["KubernetesOntologyEvidenceObserver"]
