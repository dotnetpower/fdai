"""Composition-time loader for the complete ontology declaration graph."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.rule_catalog.schema.property_semantic import (
    PropertySemanticRegistry,
    load_property_semantic_registry,
)
from fdai.shared.contracts.models import (
    OntologyActionType,
    OntologyLinkType,
    OntologyObjectType,
)
from fdai.shared.contracts.registry import SchemaRegistry


@dataclass(frozen=True, slots=True)
class OntologyCatalog:
    object_types: tuple[OntologyObjectType, ...]
    link_types: tuple[OntologyLinkType, ...]
    action_types: tuple[OntologyActionType, ...]
    property_semantics: PropertySemanticRegistry


def load_ontology_catalog(
    root: Path,
    *,
    schema_registry: SchemaRegistry,
    action_overlay_root: Path | None = None,
    probes_root: Path | None = None,
) -> OntologyCatalog:
    """Load declarations in dependency order and validate every reference."""

    vocabulary_root = root / "vocabulary"
    object_types = load_object_type_catalog(
        vocabulary_root / "object-types",
        schema_registry=schema_registry,
    )
    link_types = load_link_type_catalog(
        vocabulary_root / "link-types",
        schema_registry=schema_registry,
        object_types=object_types,
    )
    action_types = load_action_type_catalog(
        root / "action-types",
        schema_registry=schema_registry,
        overlay_root=action_overlay_root,
        probes_root=probes_root,
        link_types=link_types,
    )
    property_semantics_path = vocabulary_root / "property-semantics.yaml"
    property_semantics = (
        load_property_semantic_registry(property_semantics_path)
        if property_semantics_path.exists()
        else PropertySemanticRegistry(
            schema_version="1.0.0",
            version="1.0.0",
            semantics=(),
        )
    )
    return OntologyCatalog(
        object_types=object_types,
        link_types=link_types,
        action_types=action_types,
        property_semantics=property_semantics,
    )


__all__ = ["OntologyCatalog", "load_ontology_catalog"]
