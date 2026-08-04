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

REPO_ROOT = Path(__file__).resolve().parents[3]


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
