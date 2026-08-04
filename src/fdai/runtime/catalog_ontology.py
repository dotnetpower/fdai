"""Runtime composition for the catalog-owned ontology subgraph."""

from __future__ import annotations

import shutil
from dataclasses import dataclass

import yaml

from fdai.core.control_loop import ControlLoop
from fdai.core.ontology_platform import (
    CatalogOntologyProjector,
    build_catalog_ontology_projection,
)
from fdai.rule_catalog.schema.rego_semantics import load_rego_semantics
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.signal_type import load_signal_type_registry_from_mapping
from fdai.runtime.configuration import _resolve_catalog_root


@dataclass(frozen=True, slots=True)
class CatalogOntologyProjectionResult:
    object_count: int
    link_count: int


async def project_catalog_ontology(
    control_loop: ControlLoop,
) -> CatalogOntologyProjectionResult | None:
    """Project the loaded catalogs when the ontology store and OPA are available."""

    store = control_loop.ontology_instance_store
    if store is None or shutil.which("opa") is None:
        return None
    catalog_root = _resolve_catalog_root()
    repo_root = catalog_root.parent
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (catalog_root / "vocabulary/resource-types.yaml").read_text(encoding="utf-8")
        )
    )
    signal_types = load_signal_type_registry_from_mapping(
        yaml.safe_load((catalog_root / "vocabulary/signal-types.yaml").read_text(encoding="utf-8"))
    )
    semantics = {
        rule.check_logic.reference: load_rego_semantics(repo_root / rule.check_logic.reference)
        for rule in control_loop.rules
    }
    projection = build_catalog_ontology_projection(
        rules=control_loop.rules,
        action_types=control_loop.action_types,
        resource_types=resource_types,
        signal_types=signal_types,
        policy_semantics=semantics,
    )
    await CatalogOntologyProjector(store).replace(projection)
    return CatalogOntologyProjectionResult(
        object_count=len(projection.objects),
        link_count=len(projection.links),
    )


__all__ = ["CatalogOntologyProjectionResult", "project_catalog_ontology"]
