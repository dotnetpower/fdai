"""Bind deterministic Kubernetes finding reducers as ontology functions."""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from fdai.core.ontology_platform import (
    OntologyFunctionKind,
    OntologyFunctionRegistry,
    OntologyFunctionType,
)
from fdai.shared.ontology.release import build_ontology_release

from .admission import mutating_webhook_resource_drift_findings
from .admission_conditions import admission_condition_findings
from .capacity import capacity_exceeds_ceiling_findings
from .configmap_mount import missing_configmap_mount_findings
from .coredns import global_service_nxdomain_findings
from .dependency import missing_service_dependency_findings
from .host_port import host_port_conflict_findings
from .hpa import hpa_missing_cpu_request_findings
from .image_drift import image_pull_controller_drift_findings
from .init_dependency import init_dependency_wait_findings
from .liveness import liveness_probe_failure_findings, readiness_probe_failure_findings
from .log_signals import bounded_log_signal_findings
from .owner_findings import custom_owner_degradation_findings
from .pod_security import pod_security_mismatch_findings
from .rollout import zero_availability_rollout_findings
from .rwo import rwo_anti_affinity_findings
from .scaled_zero import scaled_zero_backend_findings
from .socket_bind import socket_bind_conflict_findings
from .webhook_backend import missing_webhook_backend_findings
from .webhook_findings import admission_webhook_failure_findings
from .webhook_timeout import cumulative_webhook_timeout_findings

FindingReducer = Callable[..., Sequence[Mapping[str, Any]]]


@dataclass(frozen=True, slots=True)
class _ReducerBinding:
    mechanism_id: str
    reducer: FindingReducer

    @property
    def function_name(self) -> str:
        return f"diagnostic.{self.mechanism_id}"


_BINDINGS = (
    _ReducerBinding("kubernetes_capacity_reducer", capacity_exceeds_ceiling_findings),
    _ReducerBinding("kubernetes_missing_dependency_reducer", missing_service_dependency_findings),
    _ReducerBinding(
        "kubernetes_admission_resource_drift_reducer",
        mutating_webhook_resource_drift_findings,
    ),
    _ReducerBinding("kubernetes_direct_admission_condition_evidence", admission_condition_findings),
    _ReducerBinding(
        "kubernetes_custom_owner_degradation_relationship",
        custom_owner_degradation_findings,
    ),
    _ReducerBinding(
        "kubernetes_webhook_failure_source_candidate", admission_webhook_failure_findings
    ),
    _ReducerBinding(
        "kubernetes_cumulative_webhook_timeout_candidate",
        cumulative_webhook_timeout_findings,
    ),
    _ReducerBinding(
        "kubernetes_image_pull_controller_template_drift_candidate",
        image_pull_controller_drift_findings,
    ),
    _ReducerBinding("kubernetes_pod_host_port_conflict_candidate", host_port_conflict_findings),
    _ReducerBinding(
        "kubernetes_application_socket_bind_conflict_candidate", socket_bind_conflict_findings
    ),
    _ReducerBinding(
        "kubernetes_missing_webhook_backend_candidate", missing_webhook_backend_findings
    ),
    _ReducerBinding(
        "kubernetes_pod_security_restricted_mismatch_candidate",
        pod_security_mismatch_findings,
    ),
    _ReducerBinding("kubernetes_liveness_probe_failure_candidate", liveness_probe_failure_findings),
    _ReducerBinding(
        "kubernetes_readiness_probe_failure_candidate", readiness_probe_failure_findings
    ),
    _ReducerBinding("kubernetes_rwo_anti_affinity_conflict_candidate", rwo_anti_affinity_findings),
    _ReducerBinding(
        "kubernetes_init_container_missing_service_candidate", init_dependency_wait_findings
    ),
    _ReducerBinding(
        "kubernetes_missing_configmap_mount_candidate", missing_configmap_mount_findings
    ),
    _ReducerBinding(
        "kubernetes_zero_availability_rollout_candidate", zero_availability_rollout_findings
    ),
    _ReducerBinding(
        "kubernetes_coredns_global_nxdomain_candidate", global_service_nxdomain_findings
    ),
    _ReducerBinding(
        "kubernetes_service_backend_scaled_to_zero_candidate", scaled_zero_backend_findings
    ),
    _ReducerBinding(
        "kubernetes_hpa_cpu_utilization_missing_request_candidate",
        hpa_missing_cpu_request_findings,
    ),
    _ReducerBinding("kubernetes_bounded_application_log_signals", bounded_log_signal_findings),
)

_ARRAY_ARGUMENTS = frozenset(
    {
        "configmap_receipts",
        "configurations",
        "events",
        "nodes",
        "owners",
        "records",
        "resources",
        "service_receipts",
    }
)


def diagnostic_function_types() -> tuple[OntologyFunctionType, ...]:
    """Return exact read-only declarations for every bound finding reducer."""

    return tuple(_declaration(binding) for binding in _BINDINGS)


def build_diagnostic_function_registry() -> OntologyFunctionRegistry:
    """Build an exact-release registry containing all diagnostic reducers."""

    declarations = diagnostic_function_types()
    registry = OntologyFunctionRegistry(release=build_ontology_release(function_types=declarations))
    for binding, declaration in zip(_BINDINGS, declarations, strict=True):
        registry.register(declaration, _invoker(binding.reducer))
    return registry


def _declaration(binding: _ReducerBinding) -> OntologyFunctionType:
    source = inspect.getsource(binding.reducer).encode("utf-8")
    return OntologyFunctionType(
        name=binding.function_name,
        version="1.0.0",
        kind=OntologyFunctionKind.DERIVE,
        artifact_digest=f"sha256:{hashlib.sha256(source).hexdigest()}",
        publisher="FDAI",
        input_schema=_input_schema(binding.reducer),
        output_schema={
            "type": "array",
            "maxItems": 256,
            "items": {"type": "object"},
        },
        read_sets=["KubernetesEvidence"],
        purpose_bindings=["diagnostic-evaluation"],
        allowed_agents=["Heimdall"],
        timeout_seconds=30,
        cpu_millis=1000,
        memory_bytes=134_217_728,
        max_output_bytes=262_144,
        network_allowed=False,
        credentials_allowed=False,
    )


def _input_schema(reducer: FindingReducer) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter in inspect.signature(reducer).parameters.values():
        external_name = "window_seconds" if parameter.name == "window" else parameter.name
        properties[external_name] = _argument_schema(external_name)
        if parameter.default is inspect.Parameter.empty:
            required.append(external_name)
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


def _argument_schema(name: str) -> dict[str, Any]:
    if name in _ARRAY_ARGUMENTS:
        return {"type": "array", "maxItems": 4096, "items": {"type": "object"}}
    if name == "evidence_complete":
        return {"type": "boolean"}
    if name == "evidence_cutoff":
        return {"type": "string", "format": "date-time"}
    if name == "namespace":
        return {"type": "string", "minLength": 1, "maxLength": 253}
    if name == "window_seconds":
        return {"type": "integer", "minimum": 1, "maximum": 86_400}
    if name in {"minimum_occurrences", "max_pods", "max_containers_per_pod"}:
        return {"type": "integer", "minimum": 1, "maximum": 4096}
    raise ValueError(f"unsupported diagnostic reducer argument {name!r}")


def _invoker(reducer: FindingReducer) -> Callable[[Mapping[str, Any]], Any]:
    async def invoke(arguments: Mapping[str, Any]) -> list[dict[str, Any]]:
        converted = dict(arguments)
        if "evidence_cutoff" in converted:
            cutoff = datetime.fromisoformat(
                str(converted["evidence_cutoff"]).replace("Z", "+00:00")
            )
            if cutoff.tzinfo is None:
                raise ValueError("diagnostic evidence_cutoff MUST be timezone-aware")
            converted["evidence_cutoff"] = cutoff
        if "window_seconds" in converted:
            converted["window"] = timedelta(seconds=int(converted.pop("window_seconds")))
        result = reducer(**converted)
        return [dict(item) for item in result]

    return invoke


__all__ = ["build_diagnostic_function_registry", "diagnostic_function_types"]
