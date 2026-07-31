"""Integrated ontology declaration catalog tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fdai.rule_catalog.schema.action_type import ActionTypeCatalogError
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.ontology_provenance import ontology_content_hash
from fdai.shared.contracts.models import OntologyActionType
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_shipped_ontology_catalog_loads_as_one_graph() -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    assert {item.name for item in catalog.link_types} >= {"depends_on", "emits_to"}
    assert {item.name for item in catalog.action_types} >= {"remediate.enable-diagnostic-settings"}


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
