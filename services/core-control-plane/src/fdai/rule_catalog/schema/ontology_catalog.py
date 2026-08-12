"""Composition-time loader for the complete ontology declaration graph."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.function_type import load_function_type_catalog
from fdai.rule_catalog.schema.interface_type import (
    load_interface_implementation_catalog,
    load_interface_type_catalog,
)
from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.rule_catalog.schema.property_semantic import (
    PropertySemanticRegistry,
    empty_property_semantic_registry,
    load_property_semantic_registry,
)
from fdai.shared.contracts.models import (
    OntologyActionType,
    OntologyFunctionType,
    OntologyInterfaceImplementation,
    OntologyInterfaceType,
    OntologyLinkType,
    OntologyObjectType,
    OntologyRelease,
)
from fdai.shared.contracts.registry import SchemaRegistry
from fdai.shared.ontology.release import build_ontology_release


@dataclass(frozen=True, slots=True)
class OntologyCatalog:
    """Complete reviewed declaration graph loaded from catalog-as-code."""

    object_types: tuple[OntologyObjectType, ...]
    interface_types: tuple[OntologyInterfaceType, ...]
    interface_implementations: tuple[OntologyInterfaceImplementation, ...]
    link_types: tuple[OntologyLinkType, ...]
    action_types: tuple[OntologyActionType, ...]
    property_semantics: PropertySemanticRegistry
    function_types: tuple[OntologyFunctionType, ...] = ()

    def build_release(self) -> OntologyRelease:
        """Build the canonical release over every owned declaration kind."""

        return build_ontology_release(
            object_types=self.object_types,
            link_types=self.link_types,
            action_types=self.action_types,
            interface_types=self.interface_types,
            function_types=self.function_types,
        )


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
    interface_types = load_interface_type_catalog(
        vocabulary_root / "interface-types",
        schema_registry=schema_registry,
    )
    function_types = load_function_type_catalog(
        vocabulary_root / "function-types",
        schema_registry=schema_registry,
    )
    interface_implementations = load_interface_implementation_catalog(
        vocabulary_root / "interface-implementations",
        schema_registry=schema_registry,
        interfaces=interface_types,
        object_types=object_types,
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
        else empty_property_semantic_registry()
    )
    return OntologyCatalog(
        object_types=object_types,
        interface_types=interface_types,
        interface_implementations=interface_implementations,
        link_types=link_types,
        action_types=action_types,
        property_semantics=property_semantics,
        function_types=function_types,
    )


__all__ = ["OntologyCatalog", "load_ontology_catalog"]
