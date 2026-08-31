"""Runtime composition for the catalog-owned ontology subgraph."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import yaml

from fdai.composition.readiness_catalog import load_runtime_best_practice_bindings
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
from fdai.core.ontology_platform.framework_projection import (
    build_framework_catalog_projection,
)
from fdai.rule_catalog.schema.control_objective import load_control_objective_catalog
from fdai.rule_catalog.schema.framework_catalog import load_framework_catalog
from fdai.rule_catalog.schema.rego_semantics import load_rego_semantics
from fdai.rule_catalog.schema.resource_class import load_resource_class_registry_from_mapping
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.signal_type import load_signal_type_registry_from_mapping
from fdai.runtime.configuration import _resolve_catalog_root


@dataclass(frozen=True, slots=True)
class CatalogOntologyProjectionResult:
    object_count: int
    link_count: int


@runtime_checkable
class _OntologyCatalogSynchronizer(Protocol):
    """Synchronize durable type declarations before writing graph instances."""

    async def sync_catalog(self) -> None: ...


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


async def sync_ontology_catalog(store: object) -> None:
    """Load the durable release history before any persisted instance is read.

    A persisted object pins the release digest it was written under. Reading one
    before this call fails closed on every release the process did not compute
    itself, so the first catalog change would make the runtime unstartable.
    """
    if isinstance(store, _OntologyCatalogSynchronizer):
        await store.sync_catalog()


async def project_catalog_ontology(
    control_loop: ControlLoop,
) -> CatalogOntologyProjectionResult | None:
    """Project the loaded catalogs when the ontology store and OPA are available."""

    store = control_loop.ontology_instance_store
    if store is None or shutil.which("opa") is None:
        return None
    await sync_ontology_catalog(store)
    catalog_root = _resolve_catalog_root()
    repo_root = catalog_root.parent
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (catalog_root / "vocabulary/resource-types.yaml").read_text(encoding="utf-8")
        )
    )
    resource_classes = load_resource_class_registry_from_mapping(
        yaml.safe_load(
            (catalog_root / "vocabulary/resource-classes.yaml").read_text(encoding="utf-8")
        ),
        resource_types=resource_types,
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
        property_semantics=control_loop.property_semantics,
        resource_classes=resource_classes,
    )
    release = control_loop.ontology_release
    object_type_names = (
        frozenset(
            declaration.name
            for declaration in release.declarations
            if declaration.kind.value == "object"
        )
        if release is not None
        else frozenset()
    )
    if control_loop.property_semantics is None:
        raise RuntimeError("framework objective projection requires property semantics")
    property_refs = frozenset(
        f"property.{path.resource_type}.{path.path}"
        for semantic in control_loop.property_semantics.semantics
        for path in semantic.equivalent_provider_paths
    )
    objectives = load_control_objective_catalog(
        catalog_root / "control-objectives",
        operating_domains=frozenset(
            {"reliability", "security", "cost", "config_drift", "compliance"}
        ),
        object_type_names=object_type_names,
        resource_type_ids=frozenset(item.id for item in resource_types),
        property_refs=property_refs,
    )
    best_practices, _ = load_runtime_best_practice_bindings(catalog_root)
    frameworks = load_framework_catalog(
        catalog_root / "frameworks",
        best_practices=best_practices,
        objective_refs=frozenset(item.ref for item in objectives),
        additional_roots=(catalog_root / "collected/wara-aprl",),
    )
    projection = merge_catalog_ontology_projections(
        base_projection,
        load_diagnostic_catalog_projection(repo_root),
    )
    await CatalogOntologyProjector(store).replace(projection)
    framework_projection = build_framework_catalog_projection(
        frameworks=frameworks,
        objectives=objectives,
    )
    await CatalogOntologyProjector(
        store,
        owned_object_types=("ControlObjective", "Framework", "FrameworkControl"),
    ).replace(framework_projection)
    return CatalogOntologyProjectionResult(
        object_count=len(projection.objects) + len(framework_projection.objects),
        link_count=len(projection.links) + len(framework_projection.links),
    )


__all__ = [
    "CatalogOntologyProjectionResult",
    "load_diagnostic_catalog_projection",
    "project_catalog_ontology",
]
