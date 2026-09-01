"""Recognize reviewed semantic facet families without granting query authority."""

from __future__ import annotations

_FACET_NEGATIONS = frozenset({"no", "non", "not", "without"})


def _facet_affirms_concept(facet: str, concept: str) -> bool:
    parts = tuple(part for part in facet.replace(".", "_").split("_") if part)
    if any(part in _FACET_NEGATIONS for part in parts):
        return False
    concept_parts = tuple(concept.split("_"))
    for index in range(len(parts) - len(concept_parts) + 1):
        if parts[index : index + len(concept_parts)] == concept_parts:
            return True
    return False


def _has_family(facets: set[str], family: tuple[str, ...]) -> bool:
    return any(_facet_affirms_concept(facet, concept) for facet in facets for concept in family)


def _has_families(facets: set[str], families: tuple[tuple[str, ...], ...]) -> bool:
    return all(_has_family(facets, family) for family in families)


def _facets_describe_configuration_drift_evidence(facets: set[str]) -> bool:
    has_drift = _has_family(
        facets,
        ("configuration_drift", "drift_check", "drift_finding", "drift_presence"),
    )
    support_facets = {
        facet for facet in facets if _has_family({facet}, ("support", "supports", "supporting"))
    }
    refutation_facets = {
        facet
        for facet in facets
        if _has_family({facet}, ("refute", "refutes", "refuting", "refutation"))
    }
    return bool(
        has_drift
        and support_facets
        and refutation_facets
        and support_facets.isdisjoint(refutation_facets)
    )


def _facets_describe_business_capability_mapping(facets: set[str]) -> bool:
    return _has_families(
        facets,
        (
            ("business_capability", "business_capabilities"),
            ("service_mapping", "service_mappings"),
            ("mapping_availability", "unavailable_mapping"),
        ),
    )


def _facets_describe_change_correlation(facets: set[str]) -> bool:
    allowed = {
        "approved_windows",
        "change",
        "change_records",
        "changes",
        "correlation",
        "incident",
        "service_paths",
        "targets",
        "target_resources",
        "without_causal_inference",
        "without_current_finding",
    }
    return bool(
        facets
        and facets <= allowed
        and {"approved_windows", "service_paths"} <= facets
        and {"targets", "target_resources"}.intersection(facets)
        and {"change", "change_records", "changes", "incident"}.intersection(facets)
        and {"without_causal_inference", "without_current_finding"}.intersection(facets)
    )


def _facets_describe_service_resource_path(facets: set[str]) -> bool:
    return _has_family(
        facets,
        ("service_to_resource", "service_resource_relation", "service_resource_relationship"),
    ) or _has_families(facets, (("service",), ("resource",), ("relationship",)))


def _facets_describe_service_relationship_evidence_gap(facets: set[str]) -> bool:
    has_evidence_gap = _has_family(
        facets,
        (
            "stale_relationship",
            "stale_relationships",
            "staleness",
            "incomplete_relationship",
            "incomplete_relationships",
            "incompleteness",
            "conflicting_relationship",
            "conflicting_relationships",
            "stale",
            "incomplete",
            "conflicting",
            "conflict",
        ),
    )
    return _facets_describe_service_resource_path(facets) and has_evidence_gap


def _facets_describe_service_relationship_assessment(facets: set[str]) -> bool:
    return _facets_describe_service_resource_path(facets) and _has_family(
        facets,
        ("health_conclusion", "status_conclusion", "support", "supporting_evidence"),
    )


def _facets_describe_service_current_health(facets: set[str]) -> bool:
    return _has_families(
        facets,
        (
            ("business_service", "business_services", "service"),
            ("workload", "workloads"),
            ("resource", "resources"),
            ("current_state",),
            ("unknown_state",),
        ),
    )


def _facets_describe_incident_triage(facets: set[str]) -> bool:
    return _has_families(
        facets,
        (
            ("verified_symptom", "verified_symptoms", "validated_symptom"),
            ("affected_scope", "impact_scope"),
            ("competing_hypotheses",),
            ("next_safe_diagnostic_step", "safest_next_diagnostic_step"),
        ),
    )


def _facets_describe_incident_metric_comparison(facets: set[str]) -> bool:
    return _has_family(facets, ("compare", "comparison")) and _has_family(facets, ("incident",))


def _facets_describe_network_path(facets: set[str]) -> bool:
    return _has_families(
        facets,
        (
            ("network_path", "request_path"),
            ("next_hop",),
            ("peering", "virtual_network_peering", "virtual_network_peering_relationship"),
        ),
    )


def _facets_describe_operating_objectives(facets: set[str]) -> bool:
    return _has_families(
        facets,
        (
            ("service", "service_objective", "service_objectives"),
            ("recovery_objective", "recovery_objectives"),
            (
                "breach",
                "breaches",
                "measured_breach",
                "measured_breaches",
                "measured_violation",
                "violation",
            ),
            ("evidence_gap", "missing_evidence"),
        ),
    )


def _facets_describe_historical_topology(facets: set[str]) -> bool:
    has_boundaries = _has_family(facets, ("before_after",)) or _has_families(
        facets, (("before",), ("after",))
    )
    time_family = (
        "cutoff",
        "requested_cutoff",
        "requested_time_reference",
        "requested_timeframe",
        "time_reference",
        "timeframe",
    )
    has_comparison_window = _has_family(facets, ("compare", "comparison")) and _has_family(
        facets, time_family
    )
    topology_family = (
        "preservation_topology",
        "preserve_topology",
        "retained_topology",
        "retention_topology",
    )
    required_families = (
        topology_family,
        time_family,
        ("relation_change", "relation_changes", "relationship_change", "relationship_changes"),
    )
    has_baseline_window = _has_family(
        facets, ("baseline_time_window", "baseline_timeframe")
    ) or _has_families(facets, (("baseline",), ("time_window",)))
    has_grounded_relationship_changes = _has_family(
        facets,
        ("evidence_backed_relationship_changes", "evidence_grounded_relationship_changes"),
    ) or _has_families(
        facets,
        (("evidence_backed", "evidence_grounded"), ("relationship_changes",)),
    )
    standard_form = (has_boundaries or has_comparison_window) and _has_families(
        facets, required_families
    )
    baseline_form = (
        _has_family(facets, ("compare", "comparison"))
        and has_baseline_window
        and _has_family(facets, topology_family)
        and has_grounded_relationship_changes
    )
    return standard_form or baseline_form


def _facets_describe_historical_relationship_change(facets: set[str]) -> bool:
    return _has_families(
        facets,
        (("before_cutoff",), ("after_cutoff",), ("relationship_changes",), ("evidence_backed",)),
    )


def _facets_describe_resource_activity(facets: set[str]) -> bool:
    detailed_types = _has_families(
        facets,
        (
            ("revision",),
            ("restart",),
            ("configuration", "configuration_activity"),
        ),
    )
    detailed_form = detailed_types and _has_family(
        facets,
        ("last_30_minutes", "past_30_minutes", "time_range", "time_window"),
    )
    abstract_form = _has_families(
        facets,
        (("resource_change_activity",), ("time_window",), ("resource_kind",), ("activity_types",)),
    )
    event_form = _has_families(
        facets,
        (("resource_event_history",), ("time_range", "time_window"), ("event_type",)),
    )
    return detailed_form or abstract_form or event_form


def _facets_describe_resource_activity_types(facets: set[str]) -> bool:
    return _has_families(
        facets,
        (("revision",), ("restart",), ("configuration", "configuration_activity")),
    )


def _facets_describe_ontology_release_health(facets: set[str]) -> bool:
    return _has_families(
        facets,
        (
            ("declaration_change", "declaration_changes"),
            ("evidence_freshness",),
            ("completeness",),
            ("conflict", "conflicts"),
            ("unavailable_source", "unavailable_sources"),
        ),
    )


def _facets_describe_resource_evidence_health(facets: set[str]) -> bool:
    required = _has_families(
        facets,
        (
            ("freshness",),
            ("completeness",),
            ("conflict", "conflicts"),
            ("revision", "revisions"),
            ("evidence",),
            ("authorized_scope",),
        ),
    )
    healthy_conclusion = "avoid_healthy_result_inference" in facets or _has_family(
        facets, ("healthy_result",)
    )
    return required and healthy_conclusion


def _facets_describe_private_connectivity(facets: set[str]) -> bool:
    relationship_form = _has_families(
        facets, (("attached_to",), ("routes_to",), ("workload_depends_on",))
    )
    dependency_form = _has_families(
        facets,
        (
            ("connected_to", "observed_routing_relationship"),
            ("aks_pod_workload", "workload"),
            ("postgresql_dependency",),
            ("storage_dependency",),
        ),
    )
    return relationship_form or dependency_form


def _facets_describe_recovery_plan(facets: set[str]) -> bool:
    detailed_form = _has_families(
        facets,
        (
            ("causal_hypothesis",),
            ("resource", "resources", "resource_target", "resource_targets", "target_resources"),
            ("evidence_required", "evidence_still_required", "required_evidence"),
            ("approval",),
        ),
    )
    combined_form = _has_families(
        facets,
        (
            ("causal_hypothesis",),
            ("resource", "resources"),
            ("evidence_required_before_approval",),
        ),
    )
    readiness_form = _has_families(
        facets, (("review",), ("approval_readiness",), ("additional_evidence_needed",))
    )
    return detailed_form or combined_form or readiness_form


def _facets_describe_resource_classification(facets: set[str]) -> bool:
    detailed_form = _has_families(
        facets,
        (
            ("resource_type_classification", "resource_type_classifications"),
            ("mapped_type", "mapped_types"),
            ("unmapped_native_type",),
            ("keep_unclassified",),
        ),
    )
    compact_form = _has_family(
        facets, ("resource_type_classification", "resource_type_classifications")
    ) and _has_family(
        facets,
        (
            "unclassified_native_type",
            "unclassified_native_types",
            "native_unmapped_types",
            "native_type_unclassified",
            "native_types_unclassified",
            "unmapped_native_type",
            "unmapped_native_types",
            "unmapped_native_type_unclassified",
        ),
    )
    expanded_form = _has_families(
        facets,
        (
            ("reviewed_resource_type_classification", "reviewed_resourcetype_classification"),
            ("mapping",),
            ("native_unclassified_state", "unmapped_native_types"),
            ("explicit_unclassified_retention", "explicit_unclassified_state"),
        ),
    )
    decomposed_form = _has_families(
        facets,
        (
            ("resource_type_classification", "resourcetype_classification"),
            ("mapping",),
            ("native_type", "native_types"),
            ("unclassified_state",),
            ("reviewed",),
        ),
    )
    return detailed_form or compact_form or expanded_form or decomposed_form


def _facets_describe_resource_relationships(facets: set[str]) -> bool:
    required = _has_families(
        facets,
        (
            ("containing_parent", "containment_parent"),
            ("managed_disk", "managed_disks"),
            ("attached_network_interface", "attached_network_interfaces"),
        ),
    )
    direction = "non_reversed_ownership_direction" in facets or _has_family(
        facets, ("preserve_ownership_direction", "stored_direction")
    )
    return required and direction


def _facets_describe_ontology_trace(facets: set[str]) -> bool:
    required = _has_families(facets, (("resource_type",), ("signal_type",), ("action_type",)))
    relationship = bool(
        {"explore", "relationships", "trace", "trace_relationships"}.intersection(facets)
    ) or _has_family(facets, ("controlled_action_type",))
    return required and relationship


def _facets_describe_service_agent_ownership(facets: set[str]) -> bool:
    no_execution_posture = bool(
        {
            "ownership_not_execution_permission",
            "ownership_without_execution_authority",
            "ownership_vs_execution_permission",
        }.intersection(facets)
    )
    return no_execution_posture and _has_families(
        facets,
        (
            ("business_service", "business_services", "reviewed_business_services"),
            ("workload", "workloads"),
            ("resource", "resources"),
            ("declared_owning_agent", "owning_agent"),
        ),
    )
