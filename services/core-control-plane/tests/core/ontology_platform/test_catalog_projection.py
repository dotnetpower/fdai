from __future__ import annotations

from pathlib import Path

import yaml
from fdai.core.ontology_platform import (
    CatalogOntologyProjector,
    build_catalog_ontology_projection,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.rego_semantics import load_rego_semantics
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.rule_catalog.schema.signal_type import load_signal_type_registry_from_mapping
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

REPO_ROOT = Path(__file__).resolve().parents[5]


def _projection():  # type: ignore[no-untyped-def]
    catalog_root = REPO_ROOT / "rule-catalog"
    registry = PackageResourceSchemaRegistry()
    ontology = load_ontology_catalog(
        catalog_root,
        schema_registry=registry,
        probes_root=catalog_root / "probes",
    )
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (catalog_root / "vocabulary/resource-types.yaml").read_text(encoding="utf-8")
        )
    )
    signal_types = load_signal_type_registry_from_mapping(
        yaml.safe_load((catalog_root / "vocabulary/signal-types.yaml").read_text(encoding="utf-8"))
    )
    rules = load_rule_catalog(
        catalog_root / "catalog",
        schema_registry=registry,
        action_types=ontology.action_types,
        resource_types=resource_types,
        signal_types=signal_types,
        policies_root=REPO_ROOT / "policies",
    )
    semantics = {
        rule.check_logic.reference: load_rego_semantics(REPO_ROOT / rule.check_logic.reference)
        for rule in rules
    }
    projection = build_catalog_ontology_projection(
        rules=rules,
        action_types=ontology.action_types,
        resource_types=resource_types,
        signal_types=signal_types,
        policy_semantics=semantics,
        property_semantics=ontology.property_semantics,
    )
    return ontology, rules, projection


async def test_shipped_catalog_projects_as_one_atomic_typed_subgraph() -> None:
    ontology, rules, projection = _projection()
    store = InMemoryOntologyInstanceStore(
        object_types=ontology.object_types,
        link_types=ontology.link_types,
    )
    projector = CatalogOntologyProjector(store)

    await projector.replace(projection)
    await projector.replace(projection)

    graph = await store.query_objects(
        object_types=(
            "ActionType",
            "PolicyArtifact",
            "Property",
            "ResourceType",
            "Rule",
            "SignalType",
        ),
        limit=1000,
    )
    assert graph.truncated is False
    assert sum(item.object_type == "Rule" for item in graph.objects) == len(rules)
    assert sum(item.object_type == "PolicyArtifact" for item in graph.objects) == len(rules)
    assert sum(item.link_type == "implemented_by_policy" for item in graph.links) == len(rules)
    assert sum(item.link_type == "remediates" for item in graph.links) == len(rules)
    assert all(item.revision == 1 for item in graph.objects)
    policies = tuple(item for item in graph.objects if item.object_type == "PolicyArtifact")
    assert all(str(item.properties["decision_path"]).endswith(".deny") for item in policies)
    assert all(
        str(item.properties["normalized_semantic_digest"]).startswith("sha256:")
        for item in policies
    )


def test_property_semantics_project_deterministically_without_upgrading_legacy() -> None:
    ontology, rules, projection = _projection()
    catalog_root = REPO_ROOT / "rule-catalog"
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (catalog_root / "vocabulary/resource-types.yaml").read_text(encoding="utf-8")
        )
    )
    signal_types = load_signal_type_registry_from_mapping(
        yaml.safe_load((catalog_root / "vocabulary/signal-types.yaml").read_text(encoding="utf-8"))
    )
    semantics = {
        rule.check_logic.reference: load_rego_semantics(REPO_ROOT / rule.check_logic.reference)
        for rule in rules
    }

    repeated = build_catalog_ontology_projection(
        rules=rules,
        action_types=ontology.action_types,
        resource_types=resource_types,
        signal_types=signal_types,
        policy_semantics=semantics,
        property_semantics=ontology.property_semantics,
    )

    assert repeated == projection
    projected = {item.id: item for item in projection.objects if item.object_type == "Property"}
    cpu = projected["property.compute.vm.cpu_p95_percent"]
    assert cpu.properties["semantic_id"] == "utilization.cpu.p95"
    assert cpu.properties["value_type"] == "number"
    assert cpu.properties["canonical_unit"] == "percent"
    assert cpu.properties["range"] == {"minimum": "0", "maximum": "100"}
    assert cpu.properties["semantic_registry_version"] == ontology.property_semantics.version
    assert cpu.properties["semantic_registry_digest"] == ontology.property_semantics.content_digest
    assert cpu.properties["normalized_equivalence"] is True
    assert cpu.properties["equivalent_provider_paths"] == [
        {
            "provider": "azure",
            "resource_type": "compute.vm",
            "path": "cpu_p95_percent",
        },
        {
            "provider": "azure",
            "resource_type": "compute.vm-scale-set",
            "path": "cpu_p95_percent",
        },
        {
            "provider": "azure",
            "resource_type": "postgresql-server",
            "path": "cpu_p95_percent",
        },
    ]

    legacy = projected["property.compute.vm.memory_p95_percent"]
    assert "semantic_id" not in legacy.properties
    assert "normalized_equivalence" not in legacy.properties
