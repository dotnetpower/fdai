"""Derive canonical semantic claims from verified typed function outputs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fdai.core.ontology_platform.query_values import QueryTable


@dataclass(frozen=True, slots=True)
class SemanticAssuranceClaims:
    """Canonical fact and limitation kinds entailed by one verified output."""

    fact_kinds: tuple[str, ...] = ()
    limitation_kinds: tuple[str, ...] = ()

    @property
    def claim_kinds(self) -> tuple[str, ...]:
        """Return the complete ordered claim set backed by this output."""

        return tuple(sorted(set(self.fact_kinds) | set(self.limitation_kinds)))


ClaimProjector = Callable[[object], SemanticAssuranceClaims]


def project_function_claims(
    function_name: str,
    value: object,
) -> SemanticAssuranceClaims:
    """Project claims only through the registry for the verified FunctionType."""

    projector = _FUNCTION_CLAIM_REGISTRY.get(function_name)
    return projector(value) if projector is not None else SemanticAssuranceClaims()


def _project_resource_current_state(value: object) -> SemanticAssuranceClaims:
    rows, complete = _table_rows(value)
    if rows is None or len(rows) != 1:
        return SemanticAssuranceClaims(
            limitation_kinds=("missing_resource_state_is_unknown",) if complete is False else (),
        )
    row = rows[0]
    if row.get("execution_authority") is not False:
        return SemanticAssuranceClaims()
    facts: set[str] = set()
    if _nonempty_text(row.get("name")):
        facts.add("resource.identity")
    if _nonempty_text(row.get("provisioning_status")):
        facts.add("resource.provisioning_state")
    if _nonempty_text(row.get("running_status")):
        facts.add("resource.runtime_state")
    if _nonempty_text(row.get("source_observed_at")):
        facts.add("evidence.observed_at")
    limitations = ("missing_resource_state_is_unknown",) if complete is False else ()
    return SemanticAssuranceClaims(
        fact_kinds=tuple(sorted(facts)),
        limitation_kinds=limitations,
    )


def _project_resource_health(value: object) -> SemanticAssuranceClaims:
    rows, complete = _table_rows(value)
    if rows is None:
        return SemanticAssuranceClaims(
            limitation_kinds=("resource_health_output_invalid",),
        )
    facts = {"resource_health.coverage"}
    limitations: set[str] = set()
    allowed_coverage = {
        "observed",
        "state_absent",
        "no_record",
        "not_modeled",
        "modeling_unknown",
        "scope_unreadable",
        "target_unresolved",
        "duplicate_record",
        "response_invalid",
        "response_truncated",
    }
    allowed_availability = {
        "available",
        "unavailable",
        "degraded",
        "unknown",
        "state_absent",
    }
    for row in rows:
        if row.get("execution_authority") is not False:
            return SemanticAssuranceClaims(
                limitation_kinds=("resource_health_output_invalid",),
            )
        if row.get("evidence_family") != "resource_health":
            continue
        coverage = row.get("coverage_state")
        availability = row.get("availability_state")
        if coverage not in allowed_coverage:
            return SemanticAssuranceClaims(
                limitation_kinds=("resource_health_output_invalid",),
            )
        if _nonempty_text(row.get("name")):
            facts.add("resource.identity")
        if coverage == "observed":
            if availability not in allowed_availability - {"state_absent"}:
                return SemanticAssuranceClaims(
                    limitation_kinds=("resource_health_output_invalid",),
                )
            facts.add("resource_health.availability_state")
            if availability == "unknown":
                limitations.add("resource_health.unknown_is_not_healthy")
            if _nonempty_text(row.get("provider_observed_at")):
                facts.add("evidence.observed_at")
            continue
        limitations.add(f"resource_health.{coverage}")
    if complete is not True:
        limitations.add("incomplete_evidence_cannot_prove_health")
    return SemanticAssuranceClaims(
        fact_kinds=tuple(sorted(facts)),
        limitation_kinds=tuple(sorted(limitations)),
    )


def _project_ontology_relationships(value: object) -> SemanticAssuranceClaims:
    if not isinstance(value, Mapping):
        return SemanticAssuranceClaims()
    relationships = value.get("relationships")
    complete = value.get("complete")
    if (
        value.get("authority") != "ontology_release"
        or value.get("execution_authority") is not False
        or not isinstance(complete, bool)
        or not isinstance(relationships, list)
    ):
        return SemanticAssuranceClaims()
    facts: set[str] = set()
    for relationship in relationships:
        if not isinstance(relationship, Mapping):
            return SemanticAssuranceClaims()
        link_type = relationship.get("link_type")
        if not all(
            _nonempty_text(item)
            for item in (
                link_type,
                relationship.get("from_type"),
                relationship.get("to_type"),
            )
        ):
            return SemanticAssuranceClaims()
        facts.update(("relationship.direction", "relationship.path"))
        if link_type in {"routes_via_route", "connected_via_private_link"}:
            facts.add("relationship.route")
        if link_type == "contains":
            facts.add("relationship.containment")
        if link_type == "attached_to":
            facts.add("relationship.attachment")
        if link_type == "workload_depends_on":
            facts.add("dependency.direction")
    return SemanticAssuranceClaims(
        fact_kinds=tuple(sorted(facts)),
        limitation_kinds=("truncated_path_must_be_explicit",) if not complete else (),
    )


def _project_ontology_evidence_health(value: object) -> SemanticAssuranceClaims:
    rows, table_complete = _table_rows(value)
    if rows is None or len(rows) != 1:
        return SemanticAssuranceClaims()
    row = rows[0]
    if (
        row.get("execution_authority") is not False
        or row.get("mutation_authority") is not False
        or not isinstance(row.get("complete"), bool)
        or row.get("availability") not in {"available", "unavailable"}
        or row.get("freshness_state") not in {"current", "stale", "unknown", "unavailable"}
    ):
        return SemanticAssuranceClaims()
    facts = {"evidence.completeness", "evidence.freshness"}
    conflicts = row.get("conflicts")
    if isinstance(conflicts, list) and all(isinstance(item, str) for item in conflicts):
        facts.add("evidence.conflicts")
    source = row.get("source")
    if isinstance(source, Mapping):
        if _nonempty_text(source.get("generation")):
            facts.add("evidence.source_revision")
        if _nonempty_text(source.get("observed_at")):
            facts.add("evidence.observed_at")
    complete = table_complete is True and row.get("complete") is True
    return SemanticAssuranceClaims(
        fact_kinds=tuple(sorted(facts)),
        limitation_kinds=("incomplete_evidence_cannot_prove_health",) if not complete else (),
    )


def _project_incident_evidence(value: object) -> SemanticAssuranceClaims:
    if not isinstance(value, Mapping):
        return SemanticAssuranceClaims()
    correlated = value.get("correlated_evidence")
    gaps = value.get("evidence_gaps")
    citations = value.get("grounded_citations")
    if (
        value.get("authority") != "audit_projection"
        or value.get("execution_authority") is not False
        or not _nonempty_text(value.get("incident_id"))
        or not isinstance(correlated, list)
        or not isinstance(gaps, list)
        or not isinstance(citations, list)
        or not isinstance(value.get("truncated"), bool)
        or not isinstance(value.get("cause_claim_supported"), bool)
    ):
        return SemanticAssuranceClaims()
    facts = {"evidence.completeness", "incident.identity"}
    if isinstance(value.get("incident_profile"), Mapping):
        facts.add("incident.profile")
    if correlated:
        if any(
            isinstance(item, Mapping) and _nonempty_text(item.get("action_kind"))
            for item in correlated
        ):
            facts.add("activity.operation")
        if any(
            isinstance(item, Mapping) and _nonempty_text(item.get("recorded_at"))
            for item in correlated
        ):
            facts.add("activity.recorded_at")
        facts.update(("incident.activity", "incident.evidence"))
    impact_evidence = value.get("impact_evidence")
    if isinstance(impact_evidence, list) and impact_evidence:
        facts.add("incident.impact")
    if (
        value.get("cause_claim_supported") is True
        and isinstance(value.get("root_cause"), Mapping)
        and citations
    ):
        facts.update(("evidence.support", "incident.cause"))
    limitations = {
        "missing_historical_evidence_must_be_explicit",
        "recorded_cause_requires_citations",
    }
    if gaps:
        limitations.add("missing_evidence_must_be_explicit")
    if value.get("truncated") is True:
        limitations.add("retained_history_bounds_must_be_explicit")
    return SemanticAssuranceClaims(
        fact_kinds=tuple(sorted(facts)),
        limitation_kinds=tuple(sorted(limitations)),
    )


def _project_ontology_declaration(value: object) -> SemanticAssuranceClaims:
    rows, _ = _table_rows(value)
    if rows is None or len(rows) != 1:
        return SemanticAssuranceClaims()
    row = rows[0]
    if (
        row.get("execution_authority") is not False
        or row.get("mutation_authority") is not False
        or row.get("section") != "detail"
        or row.get("declaration_kind") != "action"
        or not _nonempty_text(row.get("declaration_name"))
    ):
        return SemanticAssuranceClaims()
    declaration = row.get("declaration")
    if not isinstance(declaration, Mapping):
        return SemanticAssuranceClaims()
    facts = {"action_type.identity"}
    safeguard_fields = (
        "rollback_contract",
        "promotion_gate",
        "preconditions",
        "stop_conditions",
        "blast_radius",
    )
    if all(field in declaration for field in safeguard_fields):
        facts.add("action_type.safeguards")
    if isinstance(declaration.get("argument_schema"), Mapping) and isinstance(
        declaration.get("preconditions"),
        list,
    ):
        facts.add("action_type.constraints")
    if isinstance(declaration.get("ceiling_by_tier"), Mapping):
        facts.add("action_type.authority_ceiling")
    return SemanticAssuranceClaims(fact_kinds=tuple(sorted(facts)))


def _table_rows(value: object) -> tuple[list[Mapping[str, Any]] | None, bool | None]:
    if isinstance(value, QueryTable):
        return [row.values for row in value.rows], value.complete
    if not isinstance(value, Mapping):
        return None, None
    complete = value.get("complete")
    if not isinstance(complete, bool):
        return None, None
    raw_rows = value.get("rows")
    if not isinstance(raw_rows, list):
        return None, complete
    rows: list[Mapping[str, Any]] = []
    for item in raw_rows:
        if not isinstance(item, Mapping):
            return None, complete
        row_values = item.get("values")
        if not isinstance(row_values, Mapping):
            return None, complete
        rows.append(row_values)
    return rows, complete


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


_FUNCTION_CLAIM_REGISTRY: Mapping[str, ClaimProjector] = {
    "query.incident_evidence": _project_incident_evidence,
    "query.ontology_declaration": _project_ontology_declaration,
    "query.ontology_evidence_health": _project_ontology_evidence_health,
    "query.ontology_relationships": _project_ontology_relationships,
    "query.resource_current_state": _project_resource_current_state,
    "query.resource_health_inventory": _project_resource_health,
}


__all__ = [
    "SemanticAssuranceClaims",
    "project_function_claims",
]
