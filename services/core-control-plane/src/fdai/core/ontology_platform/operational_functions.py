"""Canonical source-derived FunctionTypes for operational competencies."""

from __future__ import annotations

from collections.abc import Sequence

from fdai.shared.contracts.models import OntologyFunctionType

from .catalog_queries import catalog_search_rules_function_type
from .contextual_resource_queries import contextual_resource_function_type
from .declaration_queries import ontology_declaration_function_type
from .evidence_health_queries import ontology_evidence_health_function_type
from .incident_queries import incident_evidence_function_type
from .inventory_impact_queries import inventory_impact_function_type
from .kubernetes_pod_diagnosis_queries import kubernetes_pod_diagnosis_function_type
from .kubernetes_pod_lifecycle_cohort_queries import (
    kubernetes_pod_lifecycle_cohort_function_type,
)
from .kubernetes_pod_recovery_queries import kubernetes_pod_recovery_function_type
from .kubernetes_rollout_queries import kubernetes_rollout_function_type
from .latency_recovery_evidence import latency_recovery_function_type
from .manifest_queries import ontology_manifest_function_type
from .mysql_pressure_evidence import (
    mysql_demand_bundle_function_type,
    mysql_pressure_function_type,
    mysql_saturation_bundle_function_type,
)
from .network_path import network_path_function_type
from .pod_telemetry import pod_telemetry_function_type
from .relationship_queries import ontology_relationships_function_type
from .release_diff_queries import ontology_release_diff_function_type
from .resource_activity_queries import resource_activity_function_type
from .resource_class_closure import resource_class_closure_function_type
from .resource_current_state_queries import resource_current_state_function_type
from .resource_error_activity_correlation_queries import (
    error_activity_correlation_function_type,
)
from .resource_event_queries import resource_event_function_type
from .resource_health_assessment_queries import target_health_assessment_function_type
from .resource_health_queries import resource_health_function_type
from .resource_ingress_queries import resource_ingress_function_type
from .resource_metric_queries import (
    resource_metric_function_type,
    resource_metric_series_function_type,
)
from .resource_state_queries import resource_state_function_type
from .service_health_queries import service_health_function_type
from .vm_process_evidence import vm_process_cpu_function_type


def operational_function_types(
    catalog_functions: Sequence[OntologyFunctionType],
) -> tuple[OntologyFunctionType, ...]:
    """Combine reviewed catalog functions with source-derived competency functions."""

    combined = tuple(catalog_functions) + (
        catalog_search_rules_function_type(),
        contextual_resource_function_type(),
        incident_evidence_function_type(),
        inventory_impact_function_type(),
        kubernetes_pod_diagnosis_function_type(),
        kubernetes_pod_lifecycle_cohort_function_type(),
        kubernetes_pod_recovery_function_type(),
        kubernetes_rollout_function_type(),
        latency_recovery_function_type(),
        ontology_declaration_function_type(),
        ontology_evidence_health_function_type(),
        ontology_manifest_function_type(),
        network_path_function_type(),
        mysql_demand_bundle_function_type(),
        mysql_pressure_function_type(),
        mysql_saturation_bundle_function_type(),
        ontology_relationships_function_type(),
        ontology_release_diff_function_type(),
        resource_class_closure_function_type(),
        pod_telemetry_function_type(),
        resource_activity_function_type(),
        resource_current_state_function_type(),
        resource_event_function_type(),
        resource_health_function_type(),
        resource_ingress_function_type(),
        resource_metric_function_type(),
        resource_metric_series_function_type(),
        resource_state_function_type(),
        service_health_function_type(),
        error_activity_correlation_function_type(),
        target_health_assessment_function_type(),
        vm_process_cpu_function_type(),
    )
    names = [item.name for item in combined]
    if len(names) != len(set(names)):
        raise ValueError("operational ontology FunctionType names MUST be unique")
    return tuple(sorted(combined, key=lambda item: item.name))


__all__ = ["operational_function_types"]
