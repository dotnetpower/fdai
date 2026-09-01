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
    expected_active = len(list((REPO_ROOT / "rule-catalog/catalog").glob("*.yaml")))
    expected_collected = len(list((REPO_ROOT / "rule-catalog/collected").rglob("*.yaml")))
    origins = [rule["origin"] for rule in rules["rules"]]
    assert len(rules["rules"]) == expected_active + expected_collected
    assert origins.count("active") == expected_active
    assert origins.count("collected") == expected_collected
    assert len(rules["details"]) == len(rules["rules"])
    assert list(rules["details"]) == sorted(rules["details"])
    selected = rules["rules"][0]
    detail = rules["details"][f"{selected['origin']}:{selected['id']}"]
    assert detail["check_logic_body"]
    assert detail["provenance"]["resolved_ref"]
    assert set(detail["explanation"]) == {"title", "description", "source", "details"}
    assert detail["explanation"]["source"] in {None, "rego_metadata"}

    best_practices = first[module.BEST_PRACTICE_LIST_KEY]
    assert best_practices["_revision"].startswith("sha256:")
    assert len(best_practices["controls"]) == 59
    assert all(control["status"] == "unknown" for control in best_practices["controls"])
    assert all(control["catalog_status"] == "present" for control in best_practices["controls"])
    assert all(control["mapping_status"] == "mapped" for control in best_practices["controls"])
    assert all(
        control["evaluation_status"] == "not_evaluated" for control in best_practices["controls"]
    )
    assert all(
        requirement["status"] == "unknown"
        for control in best_practices["controls"]
        for requirement in control["requirements"]
    )
    assert (
        sum(control["pillar"] == "operational_excellence" for control in best_practices["controls"])
        == 11
    )
    assert best_practices["evaluation_source"] == "repository-catalog"

    wara = first[module.WARA_LIST_KEY]
    assert wara["_revision"].startswith("sha256:")
    assert len(wara["controls"]) == 456
    assert wara["inventory"] == {
        "active_recommendations": 393,
        "disabled_recommendations": 63,
        "resource_types": 80,
        "automated_recommendations": 143,
        "manual_recommendations": 250,
    }
    assert all(control["source_url"].startswith("https://") for control in wara["controls"])
    assert all(control["source_license"] == "MIT" for control in wara["controls"])
    assert any(control["learn_more_url"] is not None for control in wara["controls"])
    assert wara["evaluation_source"] == "not_connected"

    mcsb = first[module.MCSB_LIST_KEY]
    assert mcsb["_revision"].startswith("sha256:")
    assert [catalog["benchmark"]["benchmark_version"] for catalog in mcsb["catalogs"]] == [
        "v1",
        "v2-preview",
    ]
    assert [catalog["benchmark"]["control_count"] for catalog in mcsb["catalogs"]] == [86, 81]
    assert all(
        control["evaluation_source"] == "catalog-crosswalk"
        for catalog in mcsb["catalogs"]
        for control in catalog["controls"]
    )

    capabilities = first[module.CAPABILITY_LIST_KEY]
    assert capabilities["_revision"].startswith("sha256:")
    assert capabilities["count"] == len(capabilities["capabilities"]) > 0
    assert capabilities["execution_eligibility"] is False

    onboarding = first[module.ONBOARDING_KEY]
    assert onboarding["probe_mode"] == "not-configured"
    assert onboarding["ready"] is onboarding["blocked"] is False
    assert onboarding["missing_resources"]
    assert onboarding["missing_role_assignments"]

    workflow_apps = first[module.WORKFLOW_APPS_KEY]
    assert workflow_apps["_revision"].startswith("sha256:")
    assert workflow_apps["count"] == len(workflow_apps["items"]) > 0
    assert all(item["lifecycle"] == "published" for item in workflow_apps["items"])

    ontology = first[module.ONTOLOGY_GRAPH_KEY]
    assert ontology["_revision"].startswith("sha256:")
    assert ontology["schema_version"] == "2.0.0"
    assert ontology["ontology_release_digest"].startswith("sha256:")
    assert ontology["mutation_authority"] is False
    assert ontology["complete"] is True
    assert ontology["limitations"] == {
        "source_coverage": [],
        "query_truncation": [],
        "access_redaction": [],
        "presentation_omission": [],
    }
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
    links_by_name = {edge["name"]: edge for edge in ontology["edges"]}
    assert links_by_name["contains"]["forward_role"] == "contains"
    assert links_by_name["contains"]["reverse_role"] == "contained_by"
    assert links_by_name["contains"]["semantic_traits"] == ["containment"]

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

    promotion = first[module.PROMOTION_GATE_LIST_KEY]
    assert promotion["_revision"].startswith("sha256:")
    assert promotion["ready_count"] == 0
    assert promotion["blocked_count"] == ontology["action_type_count"]
    assert len(promotion["rows"]) == ontology["action_type_count"]
    assert all(row["gaps"] for row in promotion["rows"])

    for role, key in module.ONTOLOGY_DECLARATION_KEYS.items():
        bundle = first[key]
        assert bundle["_revision"].startswith("sha256:")
        assert bundle["ontology_release_digest"] == ontology["ontology_release_digest"]
        assert bundle["role"] == role.value
        assert bundle["purpose"] == "operations-review"
        assert bundle["mutation_authority"] is False
        decision = bundle["details"]["object-types"]["Decision"]
        assert decision["ontology_release_digest"] == ontology["ontology_release_digest"]
        assert decision["declaration"]["key"] == "id"
        assert len(decision["declaration"]["properties"]) == 31
        assert decision["mutation_authority"] is False
        assert len(bundle["details"]["link-types"]) == ontology["link_type_count"]
        assert len(bundle["details"]["action-types"]) == ontology["action_type_count"]
        assert bundle["details"]["link-types"]["based_on"]["declaration_kind"] == "link_type"
        assert all(
            detail["mutation_authority"] is False
            for detail in bundle["details"]["action-types"].values()
        )
        decision_dependents = bundle["dependents"]["object-types"]["Decision"]
        assert decision_dependents["ontology_release_digest"] == ontology["ontology_release_digest"]
        assert decision_dependents["mutation_authority"] is False
        assert {item["name"] for item in decision_dependents["dependents"]} >= {
            "based_on",
            "resolved_by",
        }


def test_mock_and_authoritative_catalog_topologies_are_identical() -> None:
    materializer = _module()
    generator = _generator_module()

    authoritative = materializer.catalog_snapshots(REPO_ROOT)[materializer.ONTOLOGY_GRAPH_KEY]

    assert generator.build() == authoritative["catalog_topology"]


def test_stewardship_snapshot_satisfies_the_console_contract() -> None:
    """The console rejects the panel unless these exact invariants hold."""
    module = _module()

    snapshot = module.catalog_snapshots(REPO_ROOT)[module.STEWARDSHIP_KEY]
    steward_map = snapshot["map"]
    coverage = snapshot["coverage"]

    assert steward_map["version"] >= 1
    assert steward_map["hop_timeout_seconds"] >= 1
    assert steward_map["over_assigned_max"] >= 1
    assert steward_map["maintainer_count"] == len(steward_map["maintainers"]) >= 1
    assert len(steward_map["agents"]) == 15
    assert len({agent["name"] for agent in steward_map["agents"]}) == 15

    for agent in steward_map["agents"]:
        subjects = [(steward["kind"], steward["id"]) for steward in agent["stewards"]]
        assert len(set(subjects)) == len(subjects)
        accountable = {
            (steward["kind"], steward["id"])
            for steward in agent["stewards"]
            if steward["responsibility"] == "accountable"
        }
        assert agent["bus_factor"] == len(accountable)
        for steward in agent["stewards"]:
            assert steward["responsibility"] in {"accountable", "informed"}
            assert steward["duty"] in {None, "primary", "backup", "escalation"}

    assert coverage["total_agents"] == 15
    assert coverage["is_clean"] == all(
        finding["severity"] != "warn" for finding in coverage["findings"]
    )
    for finding in coverage["findings"]:
        assert finding["severity"] in {"warn", "info"}

    # An explicit null here fails the console's finite-number decode.
    assert "finding_count" not in snapshot["identity_health"]
    assert snapshot["identity_health"]["status"] == "not_configured"


def test_action_type_palette_matches_the_builder_contract() -> None:
    module = _module()

    palette = module.catalog_snapshots(REPO_ROOT)[module.ACTION_TYPE_LIST_KEY]
    entries = palette["action_types"]

    assert palette["count"] == len(entries) > 0
    assert [entry["name"] for entry in entries] == sorted(entry["name"] for entry in entries)
    for entry in entries:
        assert entry["name"] and entry["operation"] and entry["rollback_contract"]
        assert isinstance(entry["irreversible"], bool)
        assert entry["default_mode"] and entry["env_scope"]
        assert set(entry["hil_tiers"]) <= {"T0", "T1", "T2"}


def test_workflow_catalog_carries_reviewed_steps_and_source() -> None:
    module = _module()

    catalog = module.catalog_snapshots(REPO_ROOT)[module.WORKFLOW_CATALOG_KEY]
    workflows = catalog["workflows"]
    palette_names = {
        entry["name"]
        for entry in module.catalog_snapshots(REPO_ROOT)[module.ACTION_TYPE_LIST_KEY][
            "action_types"
        ]
    }

    assert catalog["count"] == len(workflows) > 0
    for workflow in workflows:
        assert workflow["step_count"] == len(workflow["steps"])
        assert workflow["yaml"].strip(), f"{workflow['name']} MUST carry its reviewed source"
        assert workflow["trigger"]["kind"]
        gate = workflow["promotion_gate"]
        assert gate["min_samples"] >= 0 and gate["min_shadow_days"] >= 0
        for step in workflow["steps"]:
            assert step["id"]
            # A structured step declares branches instead of an ActionType.
            if "action_type_ref" in step:
                assert step["action_type_ref"] in palette_names
            else:
                assert step.get("branches") or step.get("kind")
    architecture = next(
        workflow for workflow in workflows if workflow["name"] == "architecture-review"
    )
    steps = {step["id"]: step for step in architecture["steps"]}
    assert steps["evidence"] == {
        "id": "evidence",
        "kind": "wait",
        "wait_for": "evidence.updated",
        "timeout_seconds": 1209600,
    }
    assert steps["design_approval"] == {
        "id": "design_approval",
        "kind": "approval",
        "timeout_seconds": 604800,
        "approval_role": "approver",
        "quorum": 2,
        "no_self_approval": True,
    }
    assert steps["design_decision"]["outcomes"] == ["approved", "conditional", "rejected"]
    assert steps["production_gate"]["gate_ref"] == "architecture-review.production-ready"


def test_scope_snapshot_keeps_observation_separate_from_execution() -> None:
    module = _module()

    snapshot = module._scope_snapshot(
        "00000000-0000-0000-0000-000000000000,"
        "/subscriptions/00000000-0000-0000-0000-000000000000/"
        "resourceGroups/example-rg"
    )

    assert snapshot["monitoring"]["entries"] == [
        {
            "address": "00000000-0000-0000-0000-000000000000",
            "level": "subscription",
            "subscription": "00000000-0000-0000-0000-000000000000",
            "resource_group": None,
            "state": "included",
        },
        {
            "address": (
                "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example-rg"
            ),
            "level": "resource_group",
            "subscription": "00000000-0000-0000-0000-000000000000",
            "resource_group": "example-rg",
            "state": "included",
        },
    ]
    assert snapshot["action"]["entries"] == []
    assert snapshot["executor_boundary"]["resource_groups"] == []
