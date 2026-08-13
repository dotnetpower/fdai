"""Grounded search-document projection for Rule catalog retrieval."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from fdai.rule_catalog.schema.control_objective import (
    ControlObjective,
    ControlObjectiveState,
    control_objective_content_hash,
)
from fdai.rule_catalog.schema.rego_semantics import RegoSemantics
from fdai.rule_catalog.schema.rule import rule_content_hash
from fdai.rule_catalog.schema.rule_objective_binding import (
    BindingState,
    RuleObjectiveBinding,
    rule_objective_binding_content_hash,
)
from fdai.rule_catalog.schema.rule_semantic_retrieval import (
    RuleSemanticManifest,
    RuleSemanticSurface,
)
from fdai.shared.contracts.models import OntologyActionType, Rule
from fdai.shared.providers.catalog_search import (
    CatalogSearchDocument,
)
from fdai.shared.providers.catalog_search import (
    catalog_search_document_digest as _provider_document_digest,
)


def build_discovery_catalog_search_documents(
    rules: Sequence[Rule],
) -> tuple[CatalogSearchDocument, ...]:
    """Project normalized candidates into an inert discovery-only corpus."""

    documents = []
    for rule in sorted(rules, key=lambda item: item.id):
        text = "\n".join(
            (
                rule.id,
                rule.resource_type,
                rule.category.value,
                rule.severity.value,
                rule.source.value,
                rule.check_logic.reference,
                rule.remediates,
                rule.provenance.source_url,
                rule.provenance.source_version or "",
                *rule.triggered_by,
                *rule.evaluates,
            )
        )
        neighbors = tuple(
            sorted(
                {
                    rule.resource_type,
                    rule.remediates,
                    rule.check_logic.reference,
                    rule.source.value,
                    *rule.triggered_by,
                    *rule.evaluates,
                }
            )
        )
        documents.append(
            CatalogSearchDocument(
                rule_id=rule.id,
                text=text,
                neighbor_ids=neighbors,
                corpus="discovery",
            )
        )
    return tuple(documents)


def build_catalog_search_documents(
    *,
    rules: Sequence[Rule],
    action_types: Sequence[OntologyActionType],
    policy_semantics: Mapping[str, RegoSemantics],
    semantic_manifests: Mapping[str, RuleSemanticManifest] | None = None,
    semantic_surfaces: Mapping[str, Sequence[RuleSemanticSurface]] | None = None,
    control_objectives: Sequence[ControlObjective] = (),
    objective_bindings: Sequence[RuleObjectiveBinding] = (),
) -> tuple[CatalogSearchDocument, ...]:
    actions = {item.name: item for item in action_types}
    abstraction_terms = _reviewed_policy_abstraction_terms(
        rules=rules,
        control_objectives=control_objectives,
        objective_bindings=objective_bindings,
    )
    documents = []
    for rule in sorted(rules, key=lambda item: item.id):
        policy = policy_semantics.get(rule.check_logic.reference)
        if policy is None or policy.rule_id != rule.id:
            raise ValueError(f"verified policy semantics unavailable for {rule.id!r}")
        action = actions.get(rule.remediates)
        if action is None:
            raise ValueError(f"ActionType unavailable for {rule.id!r}")
        manifest = semantic_manifests.get(rule.id) if semantic_manifests is not None else None
        if semantic_manifests is not None and manifest is None:
            raise ValueError(f"semantic manifest unavailable for {rule.id!r}")
        surfaces = tuple(semantic_surfaces.get(rule.id, ())) if semantic_surfaces else ()
        if manifest is not None and any(
            item.manifest_digest != manifest.digest for item in surfaces
        ):
            raise ValueError(f"semantic surface manifest mismatch for {rule.id!r}")
        action_description = action.description or ""
        objective_text, objective_neighbors = abstraction_terms.get(rule.id, ((), ()))
        text = "\n".join(
            (
                rule.id,
                rule.resource_type,
                rule.category.value,
                rule.severity.value,
                policy.title,
                policy.description,
                rule.remediates,
                action_description,
                *rule.triggered_by,
                *rule.evaluates,
                *(value for surface in surfaces for value in surface.intent_ids),
                *(value for surface in surfaces for value in surface.concept_refs),
                *(value for surface in surfaces for value in surface.aliases),
                *(value for surface in surfaces for value in surface.training_queries),
                *objective_text,
            )
        )
        neighbors = tuple(
            sorted(
                {
                    rule.resource_type,
                    rule.remediates,
                    rule.check_logic.reference,
                    *rule.triggered_by,
                    *rule.evaluates,
                    *(value for surface in surfaces for value in surface.intent_ids),
                    *(value for surface in surfaces for value in surface.concept_refs),
                    *objective_neighbors,
                }
            )
        )
        documents.append(
            CatalogSearchDocument(
                rule_id=rule.id,
                text=text,
                neighbor_ids=neighbors,
                manifest_digest=manifest.digest if manifest is not None else None,
                surface_digest=catalog_semantic_surface_digest(surfaces) if surfaces else None,
            )
        )
    return tuple(documents)


def _reviewed_policy_abstraction_terms(
    *,
    rules: Sequence[Rule],
    control_objectives: Sequence[ControlObjective],
    objective_bindings: Sequence[RuleObjectiveBinding],
) -> Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    objectives: dict[str, ControlObjective] = {}
    for catalog_objective in control_objectives:
        if catalog_objective.ref in objectives:
            raise ValueError(f"duplicate ControlObjective ref {catalog_objective.ref!r}")
        objectives[catalog_objective.ref] = catalog_objective

    rules_by_ref = {f"{rule.id}@{rule.version}": rule for rule in rules}
    terms: dict[str, list[str]] = {}
    neighbors: dict[str, set[str]] = {}
    seen_bindings: set[str] = set()
    for binding in sorted(objective_bindings, key=lambda item: item.ref):
        if binding.ref in seen_bindings:
            raise ValueError(f"duplicate RuleObjectiveBinding ref {binding.ref!r}")
        seen_bindings.add(binding.ref)
        if binding.state not in {BindingState.REVIEWED, BindingState.PROMOTED}:
            continue
        objective = objectives.get(binding.objective.ref)
        rule = rules_by_ref.get(binding.rule.ref)
        if objective is None or rule is None:
            continue
        if objective.state not in {
            ControlObjectiveState.REVIEWED,
            ControlObjectiveState.PROMOTED,
        }:
            continue
        if objective.content_digest != control_objective_content_hash(objective):
            raise ValueError(f"ControlObjective digest mismatch for {objective.ref!r}")
        if binding.content_digest != rule_objective_binding_content_hash(binding):
            raise ValueError(f"RuleObjectiveBinding digest mismatch for {binding.ref!r}")
        if binding.objective.content_digest != objective.content_digest:
            raise ValueError(f"ControlObjective pin mismatch for {binding.ref!r}")
        if binding.rule.content_digest != rule_content_hash(rule):
            raise ValueError(f"Rule pin mismatch for {binding.ref!r}")

        objective_terms = (
            objective.ref,
            objective.title,
            objective.description,
            objective.operating_domain,
            objective.predicate_family,
            binding.relationship.value,
            *objective.protected_outcome_refs,
            *objective.applicable_ontology.resource_types,
            *objective.applicable_ontology.property_refs,
            *binding.applicability_delta.provider_refs,
            *binding.applicability_delta.resource_subtype_refs,
            *binding.applicability_delta.evidence_shape_refs,
            *binding.applicability_delta.environment_constraint_refs,
            *binding.required_evidence_refs,
        )
        terms.setdefault(rule.id, []).extend(objective_terms)
        neighbors.setdefault(rule.id, set()).update(
            (
                objective.ref,
                objective.applicable_ontology.object_type,
                *objective.protected_outcome_refs,
                *objective.applicable_ontology.resource_types,
                *objective.applicable_ontology.property_refs,
            )
        )
    return {
        rule_id: (tuple(values), tuple(sorted(neighbors[rule_id])))
        for rule_id, values in terms.items()
    }


def catalog_search_document_digest(document: CatalogSearchDocument) -> str:
    """Hash grounded document content without a provider-specific embedding."""

    return _provider_document_digest(document)


def catalog_search_schema_digest() -> str:
    """Return the versioned projection formula identity."""

    return "sha256:" + hashlib.sha256(b"catalog-search-document:v4").hexdigest()


def catalog_semantic_surface_digest(surfaces: Sequence[RuleSemanticSurface]) -> str:
    """Hash the complete promoted surface set attached to one Rule."""

    digests = tuple(sorted(item.digest for item in surfaces))
    if not digests:
        raise ValueError("semantic surface digest requires at least one surface")
    encoded = json.dumps(digests, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def rule_reference_catalog_digest(rules: Sequence[Rule]) -> str:
    """Hash the OPA-free Rule reference fields shared by writers and readers."""

    payload = tuple(
        sorted(
            (
                rule.id,
                str(rule.version),
                rule.provenance.content_hash,
                rule.check_logic.reference,
                rule.remediates,
            )
            for rule in rules
        )
    )
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "build_discovery_catalog_search_documents",
    "build_catalog_search_documents",
    "catalog_search_document_digest",
    "catalog_search_schema_digest",
    "catalog_semantic_surface_digest",
    "rule_reference_catalog_digest",
]
