"""Build deterministic ontology and ActionType Operator projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai.core.ontology_explorer import render_ontology_mermaid
from fdai.delivery.ontology_console_projection import semantic_model_profile
from fdai.delivery.ontology_declaration_projection import (
    build_action_type_detail_projection,
    build_link_type_detail_projection,
    build_object_type_detail_projection,
)
from fdai.delivery.ontology_dependents_projection import build_declaration_dependents_projection
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.shared.contracts.models import CeilingRole


def ontology_snapshot(
    ontology: OntologyCatalog,
    *,
    resource_types: Sequence[Mapping[str, object]],
    rules: Sequence[Mapping[str, object]],
    workflows: Sequence[Mapping[str, object]],
    agents: Sequence[Mapping[str, object]],
    topology: Mapping[str, object],
) -> dict[str, object]:
    del resource_types, rules, workflows, agents
    object_types = sorted(ontology.object_types, key=lambda item: item.name)
    interface_types = sorted(ontology.interface_types, key=lambda item: item.name)
    link_types = sorted(ontology.link_types, key=lambda item: item.name)
    action_types = sorted(ontology.action_types, key=lambda item: item.name)
    function_types = sorted(ontology.function_types, key=lambda item: item.name)
    release = ontology.build_release()
    rendered = render_ontology_mermaid(object_types, link_types)
    return {
        "schema_version": "2.0.0",
        "ontology_release_digest": release.digest,
        "mutation_authority": False,
        "complete": True,
        "limitations": {
            "source_coverage": [],
            "query_truncation": [],
            "access_redaction": [],
            "presentation_omission": [],
        },
        "semantic_model": semantic_model_profile(ontology),
        "catalog_topology": topology,
        "mermaid": rendered.mermaid,
        "object_type_count": len(object_types),
        "interface_type_count": len(interface_types),
        "link_type_count": len(link_types),
        "action_type_count": len(action_types),
        "function_type_count": len(function_types),
        "object_types": [item.name for item in object_types],
        "interface_types": [
            item.model_dump(mode="json", exclude_none=True) for item in interface_types
        ],
        "link_types": [item.name for item in link_types],
        "action_types": [item.model_dump(mode="json", exclude_none=True) for item in action_types],
        "function_types": [
            item.model_dump(mode="json", exclude_none=True) for item in function_types
        ],
        "nodes": [
            {
                "name": item.name,
                "key": item.key,
                "property_count": len(item.properties),
                "properties": sorted(item.properties),
                "description": item.description,
                "lifecycle": (
                    item.lifecycle.model_dump(mode="json", exclude_none=True)
                    if item.lifecycle is not None
                    else None
                ),
            }
            for item in object_types
        ],
        "edges": [
            {
                "name": item.name,
                "from_type": item.from_type,
                "to_type": item.to_type,
                "cardinality": item.cardinality.value,
                "is_transitive": item.is_transitive,
                "is_causal": item.is_causal,
                "temporal_order": item.temporal_order,
                "forward_role": item.forward_role,
                "reverse_role": item.reverse_role,
                "semantic_traits": [trait.value for trait in item.semantic_traits],
                "description": item.description,
            }
            for item in link_types
        ],
    }


def ontology_declaration_snapshot(
    ontology: OntologyCatalog,
    *,
    topology: Mapping[str, object],
    role: CeilingRole,
) -> dict[str, object]:
    """Build one purpose-bound detail bundle for an ordinary Operator role."""
    purpose = "operations-review"
    release_digest = ontology.build_release().digest
    return {
        "schema_version": "1.0.0",
        "ontology_release_digest": release_digest,
        "role": role.value,
        "purpose": purpose,
        "mutation_authority": False,
        "details": {
            "object-types": {
                item.name: build_object_type_detail_projection(
                    ontology=ontology,
                    name=item.name,
                    role=role,
                    purpose=purpose,
                    expected_release_digest=release_digest,
                )
                for item in sorted(ontology.object_types, key=lambda value: value.name)
            },
            "link-types": {
                item.name: build_link_type_detail_projection(
                    ontology=ontology,
                    name=item.name,
                    expected_release_digest=release_digest,
                )
                for item in sorted(ontology.link_types, key=lambda value: value.name)
            },
            "action-types": {
                item.name: build_action_type_detail_projection(
                    ontology=ontology,
                    name=item.name,
                    expected_release_digest=release_digest,
                )
                for item in sorted(ontology.action_types, key=lambda value: value.name)
            },
        },
        "dependents": {
            "object-types": {
                item.name: build_declaration_dependents_projection(
                    topology=topology,
                    declaration_kind="object-types",
                    declaration_name=item.name,
                )
                for item in sorted(ontology.object_types, key=lambda value: value.name)
            }
        },
    }


def action_type_palette(action_types: Sequence[Any]) -> dict[str, object]:
    """Project reviewed ActionType declarations into the builder palette."""
    entries = [
        {
            "name": action.name,
            "operation": str(action.operation),
            "category": None if action.category is None else str(action.category),
            "rollback_contract": str(action.rollback_contract),
            "irreversible": action.irreversible,
            "default_mode": str(action.default_mode),
            "execution_path": (
                None if action.execution_path is None else str(action.execution_path)
            ),
            "env_scope": str(action.env_scope),
            "hil_tiers": _hil_tiers(action),
            "description": action.description,
        }
        for action in sorted(action_types, key=lambda item: item.name)
    ]
    return {"action_types": entries, "count": len(entries)}


def _hil_tiers(action: Any) -> list[str]:
    ceilings = action.ceiling_by_tier
    if ceilings is None:
        return []
    return [
        tier
        for tier in ("T0", "T1", "T2")
        if _ceiling_requires_hil(getattr(ceilings, tier.lower(), None))
    ]


def _ceiling_requires_hil(ceiling: Any) -> bool:
    return ceiling is not None and str(ceiling.max_autonomy) == "enforce_hil"


__all__ = ["action_type_palette", "ontology_declaration_snapshot", "ontology_snapshot"]
