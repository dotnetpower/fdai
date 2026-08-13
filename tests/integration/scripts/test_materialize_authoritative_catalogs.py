from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/deployment/local/materialize-authoritative-catalogs.py"
GENERATOR = REPO_ROOT / "mocks/ui/scripts/generate-ontology-knowledge-graph.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("materialize_authoritative_catalogs", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _generator_module() -> ModuleType:
    sys.path.insert(0, str(GENERATOR.parent))
    try:
        spec = importlib.util.spec_from_file_location(
            "generate_ontology_knowledge_graph", GENERATOR
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(GENERATOR.parent))


def test_catalog_snapshots_are_deterministic_complete_reference_projections() -> None:
    module = _module()

    first = module.catalog_snapshots(REPO_ROOT)
    repeated = module.catalog_snapshots(REPO_ROOT)

    assert json.dumps(first, sort_keys=True) == json.dumps(repeated, sort_keys=True)

    rules = first[module.RULE_LIST_KEY]
    assert rules["_revision"].startswith("sha256:")
    assert rules["rules"]
    assert len(rules["details"]) == len(rules["rules"])
    assert list(rules["details"]) == sorted(rules["details"])
    selected = rules["rules"][0]
    detail = rules["details"][f"{selected['origin']}:{selected['id']}"]
    assert detail["check_logic_body"]
    assert detail["provenance"]["resolved_ref"]
    assert set(detail["explanation"]) == {"title", "description", "source", "details"}
    assert detail["explanation"]["source"] in {None, "rego_metadata"}

    ontology = first[module.ONTOLOGY_GRAPH_KEY]
    assert ontology["_revision"].startswith("sha256:")
    assert ontology["schema_version"] == "2.0.0"
    assert ontology["ontology_release_digest"].startswith("sha256:")
    assert ontology["mutation_authority"] is False
    assert ontology["object_type_count"] == len(ontology["object_types"])
    assert ontology["link_type_count"] == len(ontology["link_types"])
    assert ontology["action_type_count"] == len(ontology["action_types"])
    assert ontology["interface_type_count"] == len(ontology["interface_types"])
    assert ontology["function_type_count"] == len(ontology["function_types"])
    assert len(ontology["nodes"]) == ontology["object_type_count"]
    assert len(ontology["edges"]) == ontology["link_type_count"]
    assert ontology["mermaid"].startswith("classDiagram\n")
    assert all(node["name"] and node["key"] for node in ontology["nodes"])
    assert all(edge["from_type"] and edge["to_type"] for edge in ontology["edges"])

    semantic_model = ontology["semantic_model"]
    assert semantic_model["schema_version"] == "1.0.0"
    assert semantic_model["lenses"] == ["object", "relationship", "state", "context", "action"]
    assert [band["id"] for band in semantic_model["bands"]] == [
        "operating_scope",
        "operating_intent",
        "operating_reality",
        "decision_and_learning",
    ]
    profiled_types = {
        object_type for band in semantic_model["bands"] for object_type in band["object_types"]
    }
    assert profiled_types <= set(ontology["object_types"])

    topology = ontology["catalog_topology"]
    assert topology["schemaVersion"] == "2.0.0"
    assert topology["ontologyReleaseDigest"] == ontology["ontology_release_digest"]
    node_ids = {node["id"] for node in topology["nodes"]}
    assert (
        sum(node["kind"] == "object_type" for node in topology["nodes"])
        == ontology["object_type_count"]
    )
    assert (
        sum(node["kind"] == "interface_type" for node in topology["nodes"])
        == ontology["interface_type_count"]
    )
    assert (
        sum(node["kind"] == "function_type" for node in topology["nodes"])
        == ontology["function_type_count"]
    )
    assert all(
        edge["source"] in node_ids and edge["target"] in node_ids for edge in topology["edges"]
    )


def test_mock_and_authoritative_catalog_topologies_are_identical() -> None:
    materializer = _module()
    generator = _generator_module()

    authoritative = materializer.catalog_snapshots(REPO_ROOT)[materializer.ONTOLOGY_GRAPH_KEY]

    assert generator.build() == authoritative["catalog_topology"]
