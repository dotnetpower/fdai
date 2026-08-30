"""Integrated ontology declaration catalog tests."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from fdai.core.ontology_platform import compile_interfaces
from fdai.rule_catalog.schema.action_type import ActionTypeCatalogError
from fdai.rule_catalog.schema.ontology_catalog import (
    _validate_interface_references,
    load_ontology_catalog,
)
from fdai.rule_catalog.schema.ontology_provenance import ontology_content_hash
from fdai.rule_catalog.schema.property_semantic import property_semantic_registry_content_hash
from fdai.rule_catalog.schema.rego_semantics import load_rego_semantics
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.models import (
    LinkCardinality,
    OntologyActionType,
    OntologyInterfaceType,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_missing_property_semantic_file_uses_stable_legacy_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "fdai.rule_catalog.schema.ontology_catalog.load_object_type_catalog",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        "fdai.rule_catalog.schema.ontology_catalog.load_link_type_catalog",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        "fdai.rule_catalog.schema.ontology_catalog.load_action_type_catalog",
        lambda *_args, **_kwargs: (),
    )

    catalog = load_ontology_catalog(
        tmp_path,
        schema_registry=PackageResourceSchemaRegistry(),
    )

    assert catalog.property_semantics.version == "0.0.0"
    assert catalog.property_semantics.semantics == ()
    assert catalog.property_semantics.content_digest == property_semantic_registry_content_hash(
        catalog.property_semantics
    )


def test_shipped_ontology_catalog_loads_as_one_graph() -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    assert {item.name for item in catalog.link_types} >= {"depends_on", "emits_to"}
    assert {item.name for item in catalog.action_types} >= {"remediate.enable-diagnostic-settings"}
    assert {item.name for item in catalog.interface_types} == {
        "CostBearing",
        "Identifiable",
        "ObjectiveBound",
        "Observable",
        "Operable",
        "Ownable",
        "Recoverable",
    }
    compiled_interfaces = compile_interfaces(
        interfaces=catalog.interface_types,
        implementations=catalog.interface_implementations,
        object_types=catalog.object_types,
        release=catalog.build_release(),
    )
    assert compiled_interfaces.release_digest == catalog.build_release().digest
    assert compiled_interfaces.resolve("Identifiable") == tuple(
        sorted(item.name for item in catalog.object_types)
    )
    assert compiled_interfaces.resolve("Ownable") == ("Workload",)
    assert compiled_interfaces.resolve("Operable") == ("Workload",)
    assert compiled_interfaces.resolve("Observable") == ("Observation",)
    assert compiled_interfaces.resolve("Recoverable") == ("RecoveryObjective",)
    assert compiled_interfaces.resolve("ObjectiveBound") == ("RecoveryPlan",)
    assert compiled_interfaces.resolve("CostBearing") == ("CostObjective",)
    assert compiled_interfaces.interfaces["Operable"].required_links == (
        "workload_owned_by",
        "workload_runs_on",
    )
    contains = next(item for item in catalog.link_types if item.name == "contains")
    assert contains.version == "2.1.0"
    assert contains.cardinality is LinkCardinality.ONE_TO_MANY
    assert {item.semantic_id for item in catalog.property_semantics.semantics} >= {
        "lifecycle.secret.age",
        "security.transport.minimum_tls",
        "utilization.cpu.p95",
    }


def test_interface_catalog_rejects_dangling_semantic_references() -> None:
    interface = OntologyInterfaceType(
        name="Broken",
        version="1.0.0",
        extends=("Missing",),
        required_links=("missing_link",),
        supported_actions=("missing.action",),
    )

    with pytest.raises(
        ValueError,
        match="unknown ActionType|unknown InterfaceType|unknown LinkType",
    ):
        _validate_interface_references(
            interface_types=(interface,),
            link_types=(),
            action_types=(),
        )


def test_documented_relationship_contract_is_backed_by_declarations() -> None:
    """Every documented contract row is a declared LinkType or a named union row.

    A documented relationship with no declaration claims a validated
    relationship that no query can traverse.
    """
    document = (REPO_ROOT / "docs/roadmap/architecture/operating-ontology.md").read_text(
        encoding="utf-8"
    )
    section = document.split("\n## Relationship contract\n", 1)[1].split("\n## ", 1)[0]
    documented = tuple(re.findall(r"^\| `([a-z_]+)` \|", section, re.MULTILINE))
    union_sentence = re.search(
        r"conceptual union rows (.+?) therefore compile", " ".join(section.split())
    )
    conceptual = set(re.findall(r"`([a-z_]+)`", union_sentence.group(1) if union_sentence else ""))
    declared = {
        path.stem for path in (REPO_ROOT / "rule-catalog/vocabulary/link-types").glob("*.yaml")
    }

    assert documented, "the relationship contract table MUST list relationships"
    assert conceptual, "the document MUST name its conceptual union rows"
    assert conceptual <= set(documented)
    assert [name for name in documented if name not in declared and name not in conceptual] == []


def _operating_ontology_document() -> str:
    return (REPO_ROOT / "docs/roadmap/architecture/operating-ontology.md").read_text(
        encoding="utf-8"
    )


_UNDECLARED_MARKER = "Not declared in the shipped catalog."


def _semantic_layer_object_rows(document: str) -> tuple[tuple[str, str], ...]:
    layers = document.split("\n## Semantic layers\n", 1)[1].split("\n## ", 1)[0]
    return tuple(re.findall(r"^\| `([A-Za-z]+)` \| (.+?) \|$", layers, re.MULTILINE))


def test_retired_relationship_plans_are_absent_from_the_catalog() -> None:
    """A retired relationship plan MUST remain outside the active catalog."""
    owner_document = (
        REPO_ROOT / "docs/roadmap/rules-and-detection/operational-learning-ontology.md"
    ).read_text(encoding="utf-8")
    retired_section = owner_document.split("\n### Retired relationship plans\n", 1)[1].split(
        "\n## ", 1
    )[0]
    retired = tuple(re.findall(r"^\| `([a-z_]+)` \|", retired_section, re.MULTILINE))
    link_root = REPO_ROOT / "rule-catalog/vocabulary/link-types"

    assert set(retired) == {"learned_as", "predicts_breach_of"}
    assert [name for name in retired if (link_root / f"{name}.yaml").exists()] == []
    # The relationship contract must keep naming both, or a reader of the contract alone
    # cannot tell that their absence is deliberate.
    contract = _operating_ontology_document().split("\n## Relationship contract\n", 1)[1]
    assert all(f"`{name}`" in contract.split("\n## ", 1)[0] for name in retired)


def test_documented_object_types_are_declared_or_deferred() -> None:
    """A semantic-layer row is declared in the catalog or marked undeclared.

    An unmarked row with no declaration claims a shipped object type that no
    query resolves; a marked row that is declared claims the opposite.
    """
    rows = _semantic_layer_object_rows(_operating_ontology_document())
    declared = {
        path.stem for path in (REPO_ROOT / "rule-catalog/vocabulary/object-types").glob("*.yaml")
    }
    marked = {name for name, purpose in rows if _UNDECLARED_MARKER in purpose}

    assert rows, "the semantic-layer tables MUST list object types"
    assert [name for name, _ in rows if name not in declared and name not in marked] == []
    assert sorted(name for name in marked if name in declared) == []


def test_shipped_resource_relationship_declarations_match_canonical_roles() -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    relationships = {
        item.name: item
        for item in catalog.link_types
        if item.name in {"attached_to", "contains", "depends_on", "peered_with", "routes_to"}
    }

    assert set(relationships) == {
        "attached_to",
        "contains",
        "depends_on",
        "peered_with",
        "routes_to",
    }
    assert all(
        relationship.from_type == "Resource" and relationship.to_type == "Resource"
        for relationship in relationships.values()
    )
    assert {
        name: (item.version, item.cardinality, item.is_transitive)
        for name, item in relationships.items()
    } == {
        "attached_to": ("1.2.0", LinkCardinality.MANY_TO_MANY, False),
        "contains": ("2.1.0", LinkCardinality.ONE_TO_MANY, True),
        "depends_on": ("1.1.0", LinkCardinality.MANY_TO_MANY, False),
        "peered_with": ("1.1.0", LinkCardinality.MANY_TO_MANY, False),
        "routes_to": ("1.1.0", LinkCardinality.MANY_TO_ONE, False),
    }
    assert {
        name: (
            item.forward_role,
            item.reverse_role,
            tuple(trait.value for trait in item.semantic_traits),
        )
        for name, item in relationships.items()
    } == {
        "attached_to": ("attached_to", "anchors_attachment", ("attachment",)),
        "contains": ("contains", "contained_by", ("containment",)),
        "depends_on": ("depends_on", "required_by", ("dependency",)),
        "peered_with": (
            "peers_with",
            "peers_with",
            ("connectivity", "reciprocal"),
        ),
        "routes_to": (
            "routes_to",
            "receives_route_from",
            ("connectivity", "traffic"),
        ),
    }


def test_shipped_rules_declare_concrete_semantic_axes() -> None:
    catalog_root = REPO_ROOT / "rule-catalog"
    registry = PackageResourceSchemaRegistry()
    ontology = load_ontology_catalog(
        catalog_root,
        schema_registry=registry,
        probes_root=catalog_root / "probes",
    )
    resource_types = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (catalog_root / "vocabulary" / "resource-types.yaml").read_text(encoding="utf-8")
        )
    )
    rules = load_rule_catalog(
        catalog_root / "catalog",
        schema_registry=registry,
        action_types=ontology.action_types,
        resource_types=resource_types,
        policies_root=REPO_ROOT / "policies",
    )

    wildcard_rules = {
        rule.id for rule in rules if "*" in rule.triggered_by or "*" in rule.evaluates
    }
    assert not wildcard_rules, f"rules retain wildcard semantic axes: {sorted(wildcard_rules)}"

    assert {item.name for item in ontology.object_types} >= {
        "PolicyArtifact",
        "Property",
        "ResourceType",
        "Rule",
        "SignalType",
    }
    assert {item.name for item in ontology.link_types} >= {
        "applies_to",
        "evaluates",
        "implemented_by_policy",
        "remediates",
        "triggered_by",
    }
    for rule in rules:
        semantics = load_rego_semantics(REPO_ROOT / rule.check_logic.reference)
        assert semantics.severity == rule.severity.value
        assert semantics.category == rule.category.value


def test_shipped_ontology_catalog_contains_operating_semantic_spine() -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )

    assert {item.name for item in catalog.object_types} >= {
        "BusinessCapability",
        "BusinessService",
        "Workload",
        "Environment",
        "ServiceObjective",
        "RecoveryObjective",
        "CostObjective",
        "ArchitectureConstraint",
        "Ownership",
    }
    assert {item.name for item in catalog.link_types} >= {
        "delivered_by",
        "implemented_by",
        "workload_runs_on",
        "workload_depends_on",
        "service_has_service_objective",
        "service_has_recovery_objective",
        "service_has_cost_objective",
        "service_has_architecture_constraint",
        "service_owned_by",
        "workload_owned_by",
        "objective_owned_by",
    }


def test_change_contract_carries_planning_and_lifecycle_evidence() -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    change = next(item for item in catalog.object_types if item.name == "Change")

    assert change.version == "1.1.0"
    assert set(change.properties) >= {
        "source_kind",
        "intent_kind",
        "desired_state_digest",
        "plan_receipt_ref",
        "window_ref",
        "incident_ref",
        "process_ref",
    }
    assert {item.name for item in catalog.object_types} >= {"ChangeWindow"}
    assert {item.name for item in catalog.link_types} >= {
        "change_targets_resource",
        "case_evaluates_change",
        "change_instantiates_process",
        "change_bounded_by_envelope",
        "change_scheduled_in_window",
        "change_conflicts_with_change",
        "change_resulted_in_outcome",
        "change_recovered_by_plan",
    }


def test_shipped_ontology_catalog_contains_execution_authorization_kernel() -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    assert {item.name for item in catalog.object_types} >= {
        "AuthorizationCapability",
        "AuthorizationRequirement",
        "ExecutionProfile",
        "AuthorizationPolicyAssignment",
        "ProviderPermissionSet",
        "AuthorizationObservation",
        "AccessGrantRequest",
        "AccessGrant",
        "AuthorizationDecision",
    }
    assert {item.name for item in catalog.link_types} >= {
        "requires_authorization",
        "demands_capability",
        "authorization_targets",
        "governs_capability",
        "permits_profile",
        "implements_capability",
        "satisfies_requirement",
        "attests_grant",
    }


def test_integrated_catalog_rejects_dangling_precondition_link(tmp_path: Path) -> None:
    catalog_root = tmp_path / "rule-catalog"
    vocabulary_root = catalog_root / "vocabulary"
    object_root = vocabulary_root / "object-types"
    link_root = vocabulary_root / "link-types"
    action_root = catalog_root / "action-types"
    object_root.mkdir(parents=True)
    link_root.mkdir()
    action_root.mkdir()
    (vocabulary_root / "object-type-lifecycle-classification.yaml").write_text(
        """
schema_version: "1.0.0"
categories:
  catalog_as_code:
    rationale: Catalog declarations remain authoritative for this test fixture.
    source_refs: [docs/roadmap/architecture/operating-ontology.md]
    object_types: []
  event_bus_registry:
    rationale: Event bus ownership remains authoritative for this test fixture.
    source_refs: [docs/roadmap/architecture/operating-ontology.md]
    object_types: []
  projection_owned:
    rationale: The Resource fixture is owned by its provider projection contract.
    source_refs: [docs/roadmap/architecture/operating-ontology.md]
    object_types: [Resource]
  owner_required:
    rationale: No additional agent lifecycle owner is required by this test fixture.
    source_refs: [docs/roadmap/architecture/operating-ontology.md]
    object_types: []
""".lstrip(),
        encoding="utf-8",
    )
    (object_root / "Resource.yaml").write_text(
        (REPO_ROOT / "rule-catalog/vocabulary/object-types/Resource.yaml").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    (link_root / "contains.yaml").write_text(
        (REPO_ROOT / "rule-catalog/vocabulary/link-types/contains.yaml").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    source = (
        REPO_ROOT / "rule-catalog" / "action-types" / "remediate.enable-diagnostic-settings.yaml"
    ).read_text(encoding="utf-8")
    action_raw = yaml.safe_load(source.replace("link_type: emits_to", "link_type: missing_link"))
    action = OntologyActionType.model_validate(action_raw)
    action_raw["provenance"]["content_hash"] = ontology_content_hash(action)
    (action_root / "remediate.enable-diagnostic-settings.yaml").write_text(
        yaml.safe_dump(action_raw, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ActionTypeCatalogError, match="missing_link"):
        load_ontology_catalog(
            catalog_root,
            schema_registry=PackageResourceSchemaRegistry(),
        )
