"""Runtime composition for the catalog-owned ontology subgraph."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fdai.core.control_loop import ControlLoop
from fdai.core.ontology_platform import (
    CatalogOntologyProjection,
    CatalogOntologyProjector,
    build_catalog_ontology_projection,
    merge_catalog_ontology_projections,
)
from fdai.core.ontology_platform.diagnostic_ledger import validate_diagnostic_ledger
from fdai.core.ontology_platform.diagnostic_projection import (
    build_diagnostic_catalog_projection,
)
from fdai.rule_catalog.schema.property_semantic import load_property_semantic_registry
from fdai.rule_catalog.schema.rego_semantics import load_rego_semantics
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.signal_type import load_signal_type_registry_from_mapping
from fdai.runtime.configuration import _resolve_catalog_root


@dataclass(frozen=True, slots=True)
class CatalogOntologyProjectionResult:
    object_count: int
    link_count: int


def load_diagnostic_catalog_projection(repo_root: Path) -> CatalogOntologyProjection:
    """Load the frozen SREGym mechanism ledger as a fail-closed catalog projection."""

    path = repo_root / "docs/internals/sregym-absorption-ledger.json"
    try:
        if path.stat().st_size > 2_000_000:
            raise RuntimeError("diagnostic mechanism ledger exceeds byte limit")
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("diagnostic mechanism ledger is unavailable or invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("diagnostic mechanism ledger MUST be an object")
    try:
        ledger = validate_diagnostic_ledger(payload)
    except ValueError as exc:
        raise RuntimeError("diagnostic mechanism ledger completeness check failed") from exc
    return build_diagnostic_catalog_projection(ledger.mechanisms, benchmark_id="sregym")


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
    base_projection = build_catalog_ontology_projection(
        rules=control_loop.rules,
        action_types=control_loop.action_types,
        resource_types=resource_types,
        signal_types=signal_types,
        policy_semantics=semantics,
        property_semantics=load_property_semantic_registry(
            catalog_root / "vocabulary/property-semantics.yaml"
        ),
    )
    projection = merge_catalog_ontology_projections(
        base_projection,
        load_diagnostic_catalog_projection(repo_root),
    )
    await CatalogOntologyProjector(store).replace(projection)
    return CatalogOntologyProjectionResult(
        object_count=len(projection.objects),
        link_count=len(projection.links),
    )


__all__ = [
    "CatalogOntologyProjectionResult",
    "load_diagnostic_catalog_projection",
    "project_catalog_ontology",
]
